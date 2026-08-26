"""Disk cleanup for the Adobe_Downloads tree: scanning and classification.

Scanning and removal are deliberately two phases. ``scan()`` walks the tree and
returns a complete :class:`CleanupPlan` of per-file verdicts without touching
anything; a later phase executes that plan. Dry-run is therefore not a separate
code path -- it is simply phase 1 without phase 2 -- and evidence read during the
scan (job history, sibling CSVs, final outputs) cannot be invalidated by
deletions performed later in the same run.

Classification is by path shape, and only the shapes the pipeline actually
produces are recognised. Anything else is reported as ``unclassified`` and kept:
cleanup never removes a file it cannot name.
"""

from __future__ import annotations

import fnmatch
import os
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from adobe_downloader.config.schema import (
    CleanupCategory,
    CleanupJobConfig,
    CleanupProtect,
)
from adobe_downloader.utils.logging import get_logger

_log = get_logger("cleanup")

SECONDS_PER_DAY = 86_400.0

# A file touched this recently is treated as belonging to a live job even if the
# configured thresholds would allow its removal. In practice defaults.
# absolute_min_age_days is the real protection here; this only matters when a
# config drops that floor to zero.
RECENTLY_ACTIVE_SECONDS = 3_600.0

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

CATEGORY_STATE_DB = "state_db"
CATEGORY_LOGS = "logs"
CATEGORY_JSON = "json"
CATEGORY_INTERVAL_CSV = "interval_csv"
CATEGORY_PROCESSED_JSON = "processed_json"
CATEGORY_ZIP = "zip_archives"
CATEGORY_TRASH = "trash"
# Concatenated outputs are never removable, but they are reported so the kept
# totals account for the largest thing on disk rather than hiding it.
CATEGORY_FINAL_OUTPUT = "final_output"
CATEGORY_UNCLASSIFIED = "unclassified"

# ---------------------------------------------------------------------------
# Keep reasons -- every kept file carries one, so the report can explain itself
# ---------------------------------------------------------------------------

KEEP_PROTECTED_FINAL_OUTPUT = "protected:final_output"
KEEP_PROTECTED_PATTERN = "protected:pattern"
KEEP_BELOW_ABSOLUTE_MIN_AGE = "below_absolute_min_age"
KEEP_TOO_RECENT = "too_recent"
KEEP_CATEGORY_DISABLED = "category_disabled"
KEEP_NO_CSV_SIBLING = "no_csv_sibling"
KEEP_NO_FINAL_OUTPUT = "no_final_output"
KEEP_FINAL_OUTPUT_OLDER = "final_output_older_than_csv"
KEEP_JOB_NOT_COMPLETED = "job_not_completed"
KEEP_JOB_UNKNOWN = "job_unknown"
KEEP_IN_USE = "in_use"
KEEP_UNCLASSIFIED = "unclassified"

REMOVE_STALE = "stale"


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScannedFile:
    """One file the scan considered, with the metadata the decision needs."""

    path: Path
    size: int
    mtime: float
    category: str
    client: str
    job_name: str | None = None  # None = a client-level shared folder


@dataclass(frozen=True)
class Verdict:
    file: ScannedFile
    remove: bool
    reason: str


@dataclass
class CleanupPlan:
    """The complete outcome of a scan. Holds every file considered, not just doomed ones."""

    verdicts: list[Verdict] = field(default_factory=list)

    @property
    def to_remove(self) -> list[Verdict]:
        return [v for v in self.verdicts if v.remove]

    @property
    def to_keep(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.remove]

    @property
    def bytes_to_remove(self) -> int:
        return sum(v.file.size for v in self.verdicts if v.remove)

    @property
    def bytes_to_keep(self) -> int:
        return sum(v.file.size for v in self.verdicts if not v.remove)

    def by_category(self, *, remove: bool) -> dict[str, tuple[int, int]]:
        """Return {category: (file_count, total_bytes)} for removed or kept files."""
        out: dict[str, tuple[int, int]] = {}
        for v in self.verdicts:
            if v.remove is not remove:
                continue
            count, size = out.get(v.file.category, (0, 0))
            out[v.file.category] = (count + 1, size + v.file.size)
        return dict(sorted(out.items(), key=lambda kv: -kv[1][1]))

    def by_keep_reason(self) -> dict[str, tuple[int, int]]:
        """Return {reason: (file_count, total_bytes)} for kept files, largest first."""
        out: dict[str, tuple[int, int]] = {}
        for v in self.to_keep:
            count, size = out.get(v.reason, (0, 0))
            out[v.reason] = (count + 1, size + v.file.size)
        return dict(sorted(out.items(), key=lambda kv: -kv[1][1]))

    def largest_kept(self, n: int) -> list[Verdict]:
        return sorted(self.to_keep, key=lambda v: -v.file.size)[:n]


# ---------------------------------------------------------------------------
# Job history -- links a state DB or log file to a real completion status
# ---------------------------------------------------------------------------


def _config_stem(config_path: str) -> str:
    """Filename stem of a config path recorded on any platform.

    job_history.jsonl stores whatever separator the writing machine used, so a
    Windows-recorded "jobs\\x.yaml" must still resolve when the scan runs on POSIX.
    """
    return PurePosixPath(config_path.replace("\\", "/")).stem


@dataclass
class JobHistoryIndex:
    """Latest known status per job, keyed both by job_id and by config stem.

    State DBs are named ``<job_id>.db`` (state_manager.state_db_path) while logs
    are named ``<config stem>.log`` (cli.run passes ``config.stem``), so the two
    categories need different keys into the same history.
    """

    status_by_job_id: dict[str, str] = field(default_factory=dict)
    status_by_stem: dict[str, str] = field(default_factory=dict)

    def status_for_job_id(self, job_id: str) -> str | None:
        return self.status_by_job_id.get(job_id)

    def status_for_stem(self, stem: str) -> str | None:
        return self.status_by_stem.get(stem)


def load_job_history_index(base_folder: Path, client: str) -> JobHistoryIndex:
    """Build a status index from ``<base>/<client>/.history/job_history.jsonl``.

    Records are appended chronologically, so a later run of the same job
    overwrites the earlier verdict -- a job that failed then succeeded reads as
    completed.
    """
    from adobe_downloader.utils.post_process import read_job_history

    index = JobHistoryIndex()
    for record in read_job_history(base_folder, client):
        status = record.get("status")
        if not isinstance(status, str):
            continue
        job_id = record.get("job_id")
        if isinstance(job_id, str) and job_id:
            index.status_by_job_id[job_id] = status
        config_path = record.get("config_path")
        if isinstance(config_path, str) and config_path:
            index.status_by_stem[_config_stem(config_path)] = status
    return index


# ---------------------------------------------------------------------------
# Directory walking
# ---------------------------------------------------------------------------


def _scan_dir(directory: Path) -> Iterator[tuple[Path, int, float]]:
    """Yield (path, size, mtime) for each file directly inside *directory*.

    Uses os.scandir because DirEntry.stat() is served from the directory entry on
    Windows -- with 13k+ files per job folder on a OneDrive-backed tree, a
    per-file stat() syscall is the difference between seconds and minutes. Never
    reads file contents, so cloud-only placeholders stay dehydrated.
    """
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError as exc:  # torn-down file, permission, bad reparse point
                    _log.debug("Skipping unreadable entry in %s: %s", directory, exc)
                    continue
                yield Path(entry.path), stat.st_size, stat.st_mtime
    except (FileNotFoundError, NotADirectoryError):
        return
    except OSError as exc:
        _log.warning("Cannot scan %s: %s", directory, exc)
        return


def _subdirectories(directory: Path) -> list[Path]:
    try:
        with os.scandir(directory) as entries:
            return sorted(Path(e.path) for e in entries if e.is_dir(follow_symlinks=False))
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Protection
# ---------------------------------------------------------------------------


def is_final_output(name: str, protect: CleanupProtect) -> bool:
    """True if *name* looks like a concatenated final output.

    Two shapes exist. With output.job_name set, transform_concat writes
    ``<PREFIX>_<job_name>...csv`` into the job folder root. Without it, the
    fallback is ``<step_id>_concat.csv`` written *inside* the CSV/ folder among
    the disposable per-interval files -- hence the suffix check, which is
    location-independent on purpose.
    """
    if not protect.final_outputs:
        return False
    if not name.lower().endswith(".csv"):
        return False
    if any(name.endswith(suffix) for suffix in protect.final_output_suffixes):
        return True
    return any(name.startswith(f"{prefix}_") for prefix in protect.final_output_prefixes)


def matches_protected_pattern(name: str, protect: CleanupProtect) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in protect.patterns)


# ---------------------------------------------------------------------------
# The age gate, shared by every category
# ---------------------------------------------------------------------------


def _age_days(mtime: float, now: float) -> float:
    return (now - mtime) / SECONDS_PER_DAY


def _age_gate(
    scanned: ScannedFile,
    category: CleanupCategory,
    cfg: CleanupJobConfig,
    now: float,
    *,
    older_than_days: float | None = None,
) -> str | None:
    """Return a keep-reason if the file fails a universal gate, else None.

    absolute_min_age_days is a floor no per-category threshold can undercut, so a
    category configured with ``older_than_days: 0`` still cannot reach a file
    written minutes ago.
    """
    if not category.enabled:
        return KEEP_CATEGORY_DISABLED
    age = _age_days(scanned.mtime, now)
    if age < cfg.defaults.absolute_min_age_days:
        return KEEP_BELOW_ABSOLUTE_MIN_AGE
    threshold = category.older_than_days if older_than_days is None else older_than_days
    if age < threshold:
        return KEEP_TOO_RECENT
    return None


def _looks_in_use(mtime: float, now: float, protect: CleanupProtect) -> bool:
    return protect.running_jobs and (now - mtime) < RECENTLY_ACTIVE_SECONDS


# ---------------------------------------------------------------------------
# Per-area scanners
# ---------------------------------------------------------------------------


def _scan_state_dbs(
    client_dir: Path,
    client: str,
    cfg: CleanupJobConfig,
    history: JobHistoryIndex,
    now: float,
) -> Iterator[Verdict]:
    category = cfg.categories.state_db
    for path, size, mtime in _scan_dir(client_dir / ".state"):
        if path.suffix.lower() != ".db":
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_UNCLASSIFIED, client),
                remove=False,
                reason=KEEP_UNCLASSIFIED,
            )
            continue
        scanned = ScannedFile(path, size, mtime, CATEGORY_STATE_DB, client)
        gate = _age_gate(scanned, category, cfg, now)
        if gate:
            yield Verdict(scanned, remove=False, reason=gate)
            continue
        if _looks_in_use(mtime, now, cfg.protect):
            yield Verdict(scanned, remove=False, reason=KEEP_IN_USE)
            continue
        status = history.status_for_job_id(path.stem)
        reason = _job_status_gate(status, category.require_job_status, category.keep_unknown)
        yield Verdict(scanned, remove=reason is None, reason=reason or REMOVE_STALE)


def _scan_logs(
    client_dir: Path,
    client: str,
    cfg: CleanupJobConfig,
    history: JobHistoryIndex,
    now: float,
) -> Iterator[Verdict]:
    category = cfg.categories.logs
    for path, size, mtime in _scan_dir(client_dir / ".logs"):
        # RotatingFileHandler produces "<stem>.log" plus "<stem>.log.1" .. ".log.5".
        rotated = ".log." in path.name
        if not (path.name.endswith(".log") or rotated):
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_UNCLASSIFIED, client),
                remove=False,
                reason=KEEP_UNCLASSIFIED,
            )
            continue
        scanned = ScannedFile(path, size, mtime, CATEGORY_LOGS, client)
        # Rotations are superseded by the live log and hold no unique summary.
        threshold = category.rotated_older_than_days if rotated else category.older_than_days
        gate = _age_gate(scanned, category, cfg, now, older_than_days=threshold)
        if gate:
            yield Verdict(scanned, remove=False, reason=gate)
            continue
        if _looks_in_use(mtime, now, cfg.protect):
            yield Verdict(scanned, remove=False, reason=KEEP_IN_USE)
            continue
        stem = path.name.split(".log")[0]
        status = history.status_for_stem(stem)
        reason = _job_status_gate(status, category.require_job_status, category.keep_unknown)
        yield Verdict(scanned, remove=reason is None, reason=reason or REMOVE_STALE)


def _job_status_gate(status: str | None, required: Sequence[str], keep_unknown: bool) -> str | None:
    """Return a keep-reason if the owning job's status forbids removal, else None."""
    if status is None:
        return KEEP_JOB_UNKNOWN if keep_unknown else None
    if "any" in required:
        return None
    return None if status in required else KEEP_JOB_NOT_COMPLETED


def _scan_job_folder(
    job_dir: Path,
    client: str,
    job_name: str | None,
    cfg: CleanupJobConfig,
    now: float,
) -> Iterator[Verdict]:
    """Scan one job folder: its JSON/, CSV/, _processed/ and root-level artefacts."""
    protect = cfg.protect
    csv_dir = job_dir / "CSV"
    json_dir = job_dir / "JSON"

    # Evidence gathered once per folder, not once per file.
    final_outputs = _collect_final_outputs(job_dir, csv_dir, protect)
    newest_final_mtime = max((m for _, m in final_outputs), default=None)
    csv_stems = {p.stem for p, _, _ in _scan_dir(csv_dir)} if csv_dir.is_dir() else set()

    yield from _scan_json(json_dir, client, job_name, cfg, now, csv_stems)
    yield from _scan_processed_json(json_dir / "_processed", client, job_name, cfg, now)
    yield from _scan_interval_csvs(csv_dir, client, job_name, cfg, now, newest_final_mtime)
    yield from _scan_job_root(job_dir, client, job_name, cfg, now)


def _collect_final_outputs(
    job_dir: Path, csv_dir: Path, protect: CleanupProtect
) -> list[tuple[Path, float]]:
    """Final concatenated outputs for a job, from both places they can land."""
    found: list[tuple[Path, float]] = []
    for path, _size, mtime in _scan_dir(job_dir):
        if is_final_output(path.name, protect):
            found.append((path, mtime))
    for path, _size, mtime in _scan_dir(csv_dir):
        if is_final_output(path.name, protect):
            found.append((path, mtime))
    return found


def _scan_json(
    json_dir: Path,
    client: str,
    job_name: str | None,
    cfg: CleanupJobConfig,
    now: float,
    csv_stems: set[str],
) -> Iterator[Verdict]:
    category = cfg.categories.json_files
    for path, size, mtime in _scan_dir(json_dir):
        if path.suffix.lower() != ".json":
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_UNCLASSIFIED, client, job_name),
                remove=False,
                reason=KEEP_UNCLASSIFIED,
            )
            continue
        scanned = ScannedFile(path, size, mtime, CATEGORY_JSON, client, job_name)
        gate = _age_gate(scanned, category, cfg, now)
        if gate:
            yield Verdict(scanned, remove=False, reason=gate)
            continue
        # make_csv_output_path is a pure path rewrite (JSON/x.json -> CSV/x.csv),
        # so the sibling's presence proves this exact file was transformed.
        if category.require_csv_sibling and path.stem not in csv_stems:
            yield Verdict(scanned, remove=False, reason=KEEP_NO_CSV_SIBLING)
            continue
        yield Verdict(scanned, remove=True, reason=REMOVE_STALE)


def _scan_processed_json(
    processed_dir: Path,
    client: str,
    job_name: str | None,
    cfg: CleanupJobConfig,
    now: float,
) -> Iterator[Verdict]:
    category = cfg.categories.processed_json
    for path, size, mtime in _scan_dir(processed_dir):
        scanned = ScannedFile(path, size, mtime, CATEGORY_PROCESSED_JSON, client, job_name)
        gate = _age_gate(scanned, category, cfg, now)
        yield Verdict(scanned, remove=gate is None, reason=gate or REMOVE_STALE)


def _scan_interval_csvs(
    csv_dir: Path,
    client: str,
    job_name: str | None,
    cfg: CleanupJobConfig,
    now: float,
    newest_final_mtime: float | None,
) -> Iterator[Verdict]:
    category = cfg.categories.interval_csv
    protect = cfg.protect
    for path, size, mtime in _scan_dir(csv_dir):
        # The no-job_name concat fallback lives in here alongside its own inputs.
        if is_final_output(path.name, protect):
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_FINAL_OUTPUT, client, job_name),
                remove=False,
                reason=KEEP_PROTECTED_FINAL_OUTPUT,
            )
            continue
        if matches_protected_pattern(path.name, protect):
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_INTERVAL_CSV, client, job_name),
                remove=False,
                reason=KEEP_PROTECTED_PATTERN,
            )
            continue
        if path.suffix.lower() != ".csv":
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_UNCLASSIFIED, client, job_name),
                remove=False,
                reason=KEEP_UNCLASSIFIED,
            )
            continue
        scanned = ScannedFile(path, size, mtime, CATEGORY_INTERVAL_CSV, client, job_name)
        gate = _age_gate(scanned, category, cfg, now)
        if gate:
            yield Verdict(scanned, remove=False, reason=gate)
            continue
        if category.require_final_output:
            if newest_final_mtime is None:
                yield Verdict(scanned, remove=False, reason=KEEP_NO_FINAL_OUTPUT)
                continue
            # A final output predating this CSV cannot contain it -- the job was
            # re-run and this interval never made it into the concatenation.
            if category.require_final_output_newer and newest_final_mtime < mtime:
                yield Verdict(scanned, remove=False, reason=KEEP_FINAL_OUTPUT_OLDER)
                continue
        yield Verdict(scanned, remove=True, reason=REMOVE_STALE)


def _scan_job_root(
    job_dir: Path,
    client: str,
    job_name: str | None,
    cfg: CleanupJobConfig,
    now: float,
) -> Iterator[Verdict]:
    """Root-level artefacts: final outputs (always kept) and zip archives."""
    category = cfg.categories.zip_archives
    protect = cfg.protect
    for path, size, mtime in _scan_dir(job_dir):
        if is_final_output(path.name, protect):
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_FINAL_OUTPUT, client, job_name),
                remove=False,
                reason=KEEP_PROTECTED_FINAL_OUTPUT,
            )
            continue
        if matches_protected_pattern(path.name, protect):
            yield Verdict(
                ScannedFile(path, size, mtime, CATEGORY_UNCLASSIFIED, client, job_name),
                remove=False,
                reason=KEEP_PROTECTED_PATTERN,
            )
            continue
        if path.suffix.lower() == ".zip":
            scanned = ScannedFile(path, size, mtime, CATEGORY_ZIP, client, job_name)
            gate = _age_gate(scanned, category, cfg, now)
            yield Verdict(scanned, remove=gate is None, reason=gate or REMOVE_STALE)
            continue
        yield Verdict(
            ScannedFile(path, size, mtime, CATEGORY_UNCLASSIFIED, client, job_name),
            remove=False,
            reason=KEEP_UNCLASSIFIED,
        )


def _scan_quarantine(
    client_dir: Path,
    client: str,
    cfg: CleanupJobConfig,
    now: float,
) -> Iterator[Verdict]:
    """Purge quarantine batches from earlier runs.

    This is the only path by which cleanup destroys a file permanently, and it
    only ever reaches files a previous run already listed in its report.
    """
    category = cfg.categories.trash
    quarantine_root = client_dir / cfg.defaults.quarantine_folder
    if not quarantine_root.is_dir():
        return
    for batch in _subdirectories(quarantine_root):
        for path, size, mtime in _walk_files(batch):
            scanned = ScannedFile(path, size, mtime, CATEGORY_TRASH, client)
            gate = _age_gate(scanned, category, cfg, now)
            yield Verdict(scanned, remove=gate is None, reason=gate or REMOVE_STALE)


def _walk_files(root: Path) -> Iterator[tuple[Path, int, float]]:
    """Recursively yield every file under *root*."""
    yield from _scan_dir(root)
    for sub in _subdirectories(root):
        yield from _walk_files(sub)


# ---------------------------------------------------------------------------
# Top-level scan
# ---------------------------------------------------------------------------


def _job_folders(client_dir: Path, cfg: CleanupJobConfig) -> list[tuple[Path, str | None]]:
    """Job folders to scan, as (path, job_name).

    The client folder itself is included with job_name None: jobs that set no
    output.job_name write into the shared <client>/JSON and <client>/CSV folders.
    """
    folders: list[tuple[Path, str | None]] = [(client_dir, None)]
    reserved = {".state", ".logs", ".history", "JSON", "CSV", cfg.defaults.quarantine_folder}
    allow = set(cfg.target.jobs)
    exclude = set(cfg.target.exclude_jobs)
    for sub in _subdirectories(client_dir):
        name = sub.name
        if name in reserved or name.startswith("."):
            continue
        if allow and name not in allow:
            continue
        if name in exclude:
            continue
        folders.append((sub, name))
    return folders


def _client_folders(base: Path, cfg: CleanupJobConfig) -> list[Path]:
    wanted = set(cfg.target.clients)
    out = []
    for sub in _subdirectories(base):
        if sub.name.startswith("."):
            continue
        if wanted and sub.name not in wanted:
            continue
        out.append(sub)
    return out


def scan(cfg: CleanupJobConfig, *, now: float | None = None) -> CleanupPlan:
    """Walk the configured tree and classify every file. Touches nothing.

    ``.history/`` is never entered at all -- job_history.jsonl and the archived
    configs are the audit trail, and are read as evidence, never as candidates.
    """
    base = Path(cfg.target.base_folder)
    moment = time.time() if now is None else now
    plan = CleanupPlan()

    if not base.is_dir():
        _log.warning("Base folder does not exist: %s", base)
        return plan

    for client_dir in _client_folders(base, cfg):
        client = client_dir.name
        history = load_job_history_index(base, client)
        _log.info("Scanning client %s", client)

        plan.verdicts.extend(_scan_state_dbs(client_dir, client, cfg, history, moment))
        plan.verdicts.extend(_scan_logs(client_dir, client, cfg, history, moment))
        plan.verdicts.extend(_scan_quarantine(client_dir, client, cfg, moment))

        for job_dir, job_name in _job_folders(client_dir, cfg):
            plan.verdicts.extend(_scan_job_folder(job_dir, client, job_name, cfg, moment))

    _log.info(
        "Scan complete: %d file(s) considered, %d to remove",
        len(plan.verdicts),
        len(plan.to_remove),
    )
    return plan
