"""Post-processing utilities: move JSONs to _processed/, zip CSVs, job history, config archival."""

import json
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _history_dir(base_folder: Path, client: str) -> Path:
    return base_folder / client / ".history"


# ---------------------------------------------------------------------------
# File lifecycle helpers
# ---------------------------------------------------------------------------


def move_json_to_processed(json_path: Path) -> Path:
    """Move *json_path* into a ``_processed/`` sub-directory of its parent.

    Creates the target directory if needed. Returns the new path.
    """
    dest_dir = json_path.parent / "_processed"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / json_path.name
    shutil.move(str(json_path), dest)
    return dest


def zip_csv_folder(csv_folder: Path, zip_dest: Path) -> int:
    """Zip all ``*.csv`` files in *csv_folder* into *zip_dest*.

    Returns the number of files zipped (0 if none found).
    """
    csv_files = sorted(csv_folder.glob("*.csv"))
    if not csv_files:
        return 0
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in csv_files:
            zf.write(f, f.name)
    return len(csv_files)


# ---------------------------------------------------------------------------
# Job history
# ---------------------------------------------------------------------------


def log_job_history(base_folder: Path, client: str, record: dict) -> None:  # type: ignore[type-arg]
    """Append one JSON line to ``<base_folder>/<client>/.history/job_history.jsonl``."""
    hdir = _history_dir(base_folder, client)
    hdir.mkdir(parents=True, exist_ok=True)
    log_file = hdir / "job_history.jsonl"
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def read_job_history(
    base_folder: Path,
    client: str,
    last: int | None = None,
    status: str | None = None,
    since: str | None = None,
) -> list[dict]:  # type: ignore[type-arg]
    """Read job history records from ``job_history.jsonl``.

    Filters: *status* (exact match), *since* (ISO date prefix, e.g. ``"2025-06-01"``).
    Returns the last *last* records after filtering (most-recent at end).
    """
    log_file = _history_dir(base_folder, client) / "job_history.jsonl"
    if not log_file.exists():
        return []
    records: list[dict] = []  # type: ignore[type-arg]
    with open(log_file, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if status:
        records = [r for r in records if r.get("status") == status]
    if since:
        records = [r for r in records if (r.get("started_at") or "") >= since]
    if last is not None:
        records = records[-last:]
    return records


# ---------------------------------------------------------------------------
# Config archival
# ---------------------------------------------------------------------------


def archive_config(
    base_folder: Path,
    client: str,
    config_path: Path,
    date_prefix: str,
) -> Path:
    """Copy *config_path* to ``<base_folder>/<client>/.history/configs/<date_prefix>_<name>``.

    Returns the path of the archived copy.
    """
    configs_dir = _history_dir(base_folder, client) / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"{date_prefix}_{config_path.name}"
    dest = configs_dir / archive_name
    shutil.copy2(str(config_path), dest)
    return dest


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

_CLEANUP_TYPES = ("processed-json", "logs", "state")


def cleanup_old_files(
    base_folder: Path,
    client: str,
    older_than_days: int,
    file_type: str,
) -> int:
    """Delete files of *file_type* older than *older_than_days* days.

    *file_type* must be one of: ``processed-json``, ``logs``, ``state``.
    Returns the count of deleted files.
    """
    if file_type not in _CLEANUP_TYPES:
        raise ValueError(
            f"Unknown file_type {file_type!r}. Must be one of: {', '.join(_CLEANUP_TYPES)}"
        )

    client_dir = base_folder / client
    if file_type == "processed-json":
        target_dir = client_dir / "JSON" / "_processed"
        pattern = "*.json"
    elif file_type == "logs":
        target_dir = client_dir / ".logs"
        pattern = "*.log"
    else:  # state
        target_dir = client_dir / ".state"
        pattern = "*.db"

    if not target_dir.exists():
        return 0

    cutoff = time.time() - older_than_days * 86_400
    count = 0
    for f in target_dir.glob(pattern):
        if f.is_file() and f.stat().st_mtime < cutoff:
            f.unlink()
            count += 1
    return count


# ---------------------------------------------------------------------------
# Convenience: build a history record from a StateManager summary
# ---------------------------------------------------------------------------


def build_history_record(
    job_id: str,
    config_path: Path,
    summary: dict,  # type: ignore[type-arg]
    output_folder: str,
    archived_config_rel: str,
) -> dict:  # type: ignore[type-arg]
    """Construct the dict that gets written to ``job_history.jsonl``."""
    started_at: str | None = summary.get("started_at")
    completed_at: str | None = summary.get("completed_at")

    duration_minutes: float | None = None
    if started_at and completed_at:
        try:
            t0 = datetime.fromisoformat(started_at)
            t1 = datetime.fromisoformat(completed_at)
            duration_minutes = round((t1 - t0).total_seconds() / 60, 1)
        except ValueError:
            pass

    return {
        "job_id": job_id,
        "config_path": str(config_path),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_minutes": duration_minutes,
        "status": summary.get("job_status", "unknown"),
        "total_requests": summary.get("total", 0),
        "completed_requests": summary.get("completed", 0),
        "failed_requests": summary.get("failed", 0),
        "output_folder": output_folder,
        "archived_config": archived_config_rel,
    }
