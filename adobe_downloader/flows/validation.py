"""Validation flow — enumerate expected output files and optionally re-download missing ones."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, RsidSource, SegmentSource
from adobe_downloader.flows.report_download import (
    iterate_dates,
    iterate_rsids,
    iterate_segments,
    make_output_path,
)

_log = logging.getLogger(__name__)


def enumerate_expected_paths(
    client_name: str,
    report_defs: list[Any],
    rsids: RsidSource,
    date_range: DateRange,
    interval: str,
    output_base: Path,
    segments: SegmentSource | None = None,
    file_name_extra: str | None = None,
) -> list[Path]:
    """Return every JSON output path that a report_download run would produce."""
    paths: list[Path] = []
    for rsid in iterate_rsids(rsids):
        for dr in iterate_dates(date_range, interval):
            for seg_id, _ in iterate_segments(segments):
                for rd in report_defs:
                    paths.append(
                        make_output_path(
                            base_folder=output_base,
                            client=client_name,
                            report_name=rd.name,
                            date_range=dr,
                            file_name_extra=file_name_extra,
                            segment_id=seg_id,
                        )
                    )
    return paths


def check_output_files(
    expected_paths: list[Path],
) -> tuple[list[Path], list[Path]]:
    """Return (valid, missing_or_empty) partitions of expected_paths."""
    valid: list[Path] = []
    missing_or_empty: list[Path] = []
    for p in expected_paths:
        if p.exists() and p.stat().st_size > 0:
            valid.append(p)
        else:
            missing_or_empty.append(p)
    return valid, missing_or_empty


async def run_validate_output(
    job: Any,  # ReportDownloadConfig
    retry: bool,
    dry_run: bool,
    ac: Any | None = None,
    sm: Any | None = None,
) -> dict[str, Any]:
    """Validate all expected output files for a report_download job config.

    If retry=True and not dry_run, re-downloads any missing or empty files.
    Returns a summary dict with keys: total, valid, missing_count, missing.
    """
    from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
    from adobe_downloader.flows.report_download import run_report_download

    registry = load_report_registry()
    if job.report_group:
        report_defs = load_report_group(job.report_group, registry)
    elif job.report_ref:
        if job.report_ref not in registry:
            raise KeyError(f"report_ref {job.report_ref!r} not found in registry")
        report_defs = [registry[job.report_ref]]
    else:
        report_defs = [job.report]

    output_base = Path(job.output.base_folder)

    expected = enumerate_expected_paths(
        client_name=job.client,
        report_defs=report_defs,
        rsids=job.rsids,
        date_range=job.date_range,
        interval=job.interval,
        output_base=output_base,
        segments=job.segments,
        file_name_extra=job.file_name_extra,
    )

    valid, missing = check_output_files(expected)

    _log.info(
        "validate-output: %d expected, %d valid, %d missing/empty",
        len(expected), len(valid), len(missing),
    )
    for p in missing[:10]:
        _log.warning("  missing: %s", p)

    if missing and retry and not dry_run:
        if ac is None or sm is None:
            raise ValueError("ac and sm must be provided when retry=True")
        # Reset any completed-but-missing files so the downloader re-fetches them.
        for p in missing:
            if sm.reset_completed_for_path(p):
                _log.debug("reset completed→pending for lost file: %s", p.name)
        # Reset failed/in_progress requests so they're picked up on resume.
        reset_n = sm.reset_all()
        _log.info("reset %d non-completed request(s) to pending", reset_n)

        await run_report_download(
            client=ac,
            client_name=job.client,
            report_defs=report_defs,
            rsids=job.rsids,
            date_range=job.date_range,
            interval=job.interval,
            output_base=output_base,
            sm=sm,
            segments=job.segments,
            file_name_extra=job.file_name_extra,
        )

        valid, missing = check_output_files(expected)
        _log.info(
            "post-retry: %d valid, %d still missing", len(valid), len(missing)
        )

    return {
        "total": len(expected),
        "valid": len(valid),
        "missing_count": len(missing),
        "missing": [str(p) for p in missing],
    }
