"""Report suite updater — fetch all suites, run topline metrics, filter by threshold."""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, RsidUpdateConfig
from adobe_downloader.core.api_client import AdobeClient

_log = logging.getLogger(__name__)


def clean_suite_name(name: str) -> str:
    """Derive a clean name from a report suite display name.

    Mirrors JS: remove all spaces → remove all dots → remove '-Production' suffix.
    After removing spaces, ' - Production' becomes '-Production', so the final
    regex matches the hyphen form.
    """
    result = re.sub(r"\s+", "", name)
    result = result.replace(".", "")
    result = re.sub(r"-\s*Production", "", result, flags=re.IGNORECASE)
    return result


def load_exclusion_list(exclusion_file: str | Path | None) -> set[str]:
    """Load a plain-text list of clean names to exclude (one per line)."""
    if exclusion_file is None:
        return set()
    path = Path(exclusion_file)
    if not path.exists():
        _log.warning("Exclusion file not found: %s", path)
        return set()
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            names.add(stripped)
    return names


@dataclass
class RsidWithVisits:
    rsid: str
    clean_name: str
    visits: int
    error: str | None = None


@dataclass
class RsidUpdateResult:
    investigation_list: Path
    validation_list: Path
    suite_pairs_file: Path | None
    total_suites: int
    investigation_count: int
    validation_count: int
    failed: int


def _archive_file(path: Path, today_str: str) -> None:
    """Copy *path* to an archive subdir with a date suffix (if it exists)."""
    if not path.exists():
        return
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"{path.stem}_{today_str}{path.suffix}"
    import shutil

    shutil.copy2(path, dest)
    _log.info("Archived %s -> %s", path.name, dest.name)


def _write_clean_name_list(
    path: Path,
    clean_names: list[str],
    threshold: int,
    date_range: DateRange,
    today_str: str,
) -> None:
    """Write a plain-text RSID clean name list with header comment lines."""
    lines = [
        f"# Minimum threshold = {threshold}",
        f"# Date range = {date_range.from_date} to {date_range.to}",
        f"# File generated on {today_str}",
        "",
    ]
    lines.extend(clean_names)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_suite_pairs_file(
    path: Path,
    pairs: list[tuple[str, str]],
) -> None:
    """Write rsid:cleanName pairs file for RSID lookup."""
    content = "\n".join(f"{rsid}:{clean}" for rsid, clean in pairs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")


async def _fetch_visits(
    client: AdobeClient,
    rsid: str,
    date_range: DateRange,
) -> int | None:
    """Download topline metrics for *rsid* and return visit count (or None on failure)."""
    from adobe_downloader.config.report_definitions import load_report_registry
    from adobe_downloader.core.request_builder import build_request

    registry = load_report_registry()
    report_def = registry.get("toplineMetricsForRsidValidation")
    if report_def is None:
        raise RuntimeError("toplineMetricsForRsidValidation not found in report registry")

    req_body = build_request(report_def=report_def, date_range=date_range, rsid=rsid)
    try:
        data: dict[str, Any] = await client.get_report(req_body)
        totals = data.get("summaryData", {}).get("totals", [])
        if len(totals) >= 2:
            return int(totals[1])  # index 1 = visits (0 = unique_visitors)
        _log.warning("Unexpected totals shape for %s: %s", rsid, totals)
        return None
    except Exception as exc:
        _log.warning("Failed to fetch visits for %s: %s", rsid, exc)
        return None


async def run_rsid_update(
    client: AdobeClient,
    rsid_update_cfg: RsidUpdateConfig,
    date_range: DateRange,
    output_base: str | Path,
    exclusion_file: str | Path | None = None,
    suite_pairs_dir: str | Path | None = None,
    on_progress: Callable[[str, str], None] | None = None,
) -> RsidUpdateResult:
    """Fetch report suites, run topline metrics, filter by threshold, write RSID lists.

    Args:
        client: Authenticated AdobeClient.
        rsid_update_cfg: Thresholds and virtual-suite flag.
        date_range: Date range used for the topline metrics request.
        output_base: Directory to write botInvestigation/botValidation list files.
        exclusion_file: Optional path to plain-text exclusion list (one clean name per line).
        suite_pairs_dir: If set, write a dated rsid:cleanName pairs file here.
        on_progress: Optional callback (rsid, status) for per-RSID progress updates.
    """
    today_str = date.today().strftime("%Y%m%d")
    base = Path(output_base)

    # 1. Fetch all report suites from the API
    _log.info("Fetching report suites...")
    raw = await client.get_report_suites()
    suites: list[dict[str, Any]] = raw.get("content", [])
    _log.info("Fetched %d report suites", len(suites))

    # 2. Filter virtual report suites
    if not rsid_update_cfg.include_virtual:
        before = len(suites)
        suites = [s for s in suites if not s["rsid"].startswith("vrs_")]
        _log.info(
            "Filtered out %d virtual suites (%d remaining)",
            before - len(suites),
            len(suites),
        )

    # 3. Generate clean names
    pairs: list[tuple[str, str]] = [
        (s["rsid"], clean_suite_name(s["name"])) for s in suites
    ]

    # 4. Load exclusion list
    excluded: set[str] = load_exclusion_list(exclusion_file)
    if excluded:
        _log.info("Exclusion list: %d entries", len(excluded))

    # 5. Write suite pairs file (rsid:cleanName) for downstream lookups
    suite_pairs_path: Path | None = None
    if suite_pairs_dir is not None:
        suite_pairs_path = (
            Path(suite_pairs_dir) / f"legendReportSuites{today_str}.txt"
        )
        _write_suite_pairs_file(suite_pairs_path, pairs)
        _log.info("Suite pairs file: %s", suite_pairs_path)

    # 6. Fetch topline visit counts for each RSID
    results: list[RsidWithVisits] = []
    for rsid, clean_name in pairs:
        visits = await _fetch_visits(client, rsid, date_range)
        if visits is None:
            _log.warning("Could not get visits for %s (%s)", rsid, clean_name)
            results.append(RsidWithVisits(rsid=rsid, clean_name=clean_name, visits=0, error="fetch_failed"))
        else:
            results.append(RsidWithVisits(rsid=rsid, clean_name=clean_name, visits=visits))
        status = "FAIL" if visits is None else "OK"
        if on_progress:
            on_progress(rsid, status)
        _log.debug("%s  %s  visits=%s", status, clean_name, visits)

    failed_count = sum(1 for r in results if r.error)

    # 7. Filter by exclusion list and thresholds
    non_excluded = [r for r in results if r.clean_name not in excluded]
    excluded_count = len(results) - len(non_excluded)
    if excluded_count:
        _log.info("Excluded %d suites from exclusion list", excluded_count)

    investigation_names = [
        r.clean_name
        for r in non_excluded
        if r.error is None and r.visits >= rsid_update_cfg.investigation_threshold
    ]
    validation_names = [
        r.clean_name
        for r in non_excluded
        if r.error is None and r.visits >= rsid_update_cfg.validation_threshold
    ]

    _log.info(
        "Investigation: %d/%d, Validation: %d/%d (threshold %d/%d)",
        len(investigation_names),
        len(non_excluded),
        len(validation_names),
        len(non_excluded),
        rsid_update_cfg.investigation_threshold,
        rsid_update_cfg.validation_threshold,
    )

    # 8. Archive existing files and write new ones
    investigation_path = base / "botInvestigationMinThresholdVisits.txt"
    validation_path = base / "botValidationRsidList.txt"

    _archive_file(investigation_path, today_str)
    _archive_file(validation_path, today_str)

    _write_clean_name_list(
        investigation_path,
        investigation_names,
        rsid_update_cfg.investigation_threshold,
        date_range,
        today_str,
    )
    _write_clean_name_list(
        validation_path,
        validation_names,
        rsid_update_cfg.validation_threshold,
        date_range,
        today_str,
    )

    _log.info("Written: %s (%d)", investigation_path.name, len(investigation_names))
    _log.info("Written: %s (%d)", validation_path.name, len(validation_names))

    return RsidUpdateResult(
        investigation_list=investigation_path,
        validation_list=validation_path,
        suite_pairs_file=suite_pairs_path,
        total_suites=len(pairs),
        investigation_count=len(investigation_names),
        validation_count=len(validation_names),
        failed=failed_count,
    )
