"""RSID×country full bot investigation flow.

Given a matrix of (rsid, country, segment) pairs (see flows/country_matrix.py),
downloads the full report_group (bot_investigation by default) for each pair —
one segment-filtered download per pair, not a cross product of every RSID against
every country. Files are named ``{rsid}-{country}_{investigation_label}`` — an
underscore ahead of the label, matching how a plain report_download separates
rsid from its file_name_extra — so transform_concat can split_by_rsid_country
or, for totals, concatenate every pair together into one file (RSID+country
stay identifiable via the fileName column, same as a plain per-RSID bot
investigation).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, TestLimits
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.flows.country_matrix import load_matrix_file
from adobe_downloader.flows.report_download import download_report, make_output_path
from adobe_downloader.utils.filenames import sanitize_segment_name_for_filename

_log = logging.getLogger(__name__)


@dataclass
class CountryInvestigationResult:
    job_id: str
    json_folder: Path
    downloaded: int = 0
    skipped: int = 0
    copied: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def combo_label(rsid_clean_name: str, country: str, investigation_label: str) -> str:
    """Build the ``{rsid}-{country}[_{investigation_label}]`` filename token.

    The rsid-country combination itself stays hyphen-joined; an underscore
    separates it from investigation_label, matching how report_download's
    make_output_path separates rsid from file_name_extra.
    """
    country_token = sanitize_segment_name_for_filename(country).replace(" ", "-")
    combo = f"{rsid_clean_name}-{country_token}"
    return f"{combo}_{investigation_label}" if investigation_label else combo


async def run_country_investigation(
    client: AdobeClient,
    client_name: str,
    matrix_file: Path,
    rsid_lookup_file: Path,
    report_group: str,
    date_range: DateRange,
    interval: str,
    investigation_label: str,
    output_base: str | Path,
    sm: Any,
    file_name_extra: str | None = None,
    no_resume: bool = False,
    step_id: str | None = None,
    test_limits: TestLimits | None = None,
    job_name: str | None = None,
    batch_size: int = 12,
) -> CountryInvestigationResult:
    """Download the full *report_group* for each RSID×country pair in *matrix_file*."""
    from adobe_downloader.config.report_definitions import load_report_group
    from adobe_downloader.flows.report_download import iterate_dates
    from adobe_downloader.utils.rsid_lookup import load_rsid_lookup

    rsid_map = load_rsid_lookup(rsid_lookup_file)
    report_defs = load_report_group(report_group)
    pairs = load_matrix_file(matrix_file)
    date_intervals = list(iterate_dates(date_range, interval))

    if test_limits is not None:
        from adobe_downloader.utils.test_mode import apply_date_limit

        pairs = pairs[: test_limits.max_rsids]
        date_intervals = apply_date_limit(date_intervals, test_limits)

    json_folder = Path(output_base) / client_name
    if job_name:
        json_folder = json_folder / job_name
    json_folder = json_folder / "JSON"

    result = CountryInvestigationResult(job_id=sm.job_id, json_folder=json_folder)
    semaphore = asyncio.Semaphore(batch_size)
    tasks = []

    for pair in pairs:
        rsid = rsid_map.get(pair.rsid_clean_name)
        if rsid is None:
            _log.warning("No RSID found for clean name %r — skipping", pair.rsid_clean_name)
            result.failed += 1
            result.errors.append(f"No RSID for clean name {pair.rsid_clean_name!r}")
            continue

        label = combo_label(pair.rsid_clean_name, pair.country, investigation_label)
        extra = f"{label}-{file_name_extra}" if file_name_extra else label

        for report_def in report_defs:
            for date_interval in date_intervals:
                tasks.append(
                    _download_one(
                        client=client,
                        client_name=client_name,
                        report_def=report_def,
                        date_range=date_interval,
                        rsid=rsid,
                        segment_id=pair.segment_id,
                        file_name_extra=extra,
                        output_base=output_base,
                        sm=sm,
                        no_resume=no_resume,
                        step_id=step_id,
                        result=result,
                        label=f"{pair.rsid_clean_name}/{pair.country}/{report_def.name}",
                        job_name=job_name,
                        semaphore=semaphore,
                    )
                )

    await asyncio.gather(*tasks)
    return result


async def _download_one(
    client: AdobeClient,
    client_name: str,
    report_def: Any,
    date_range: DateRange,
    rsid: str,
    segment_id: str,
    file_name_extra: str,
    output_base: str | Path,
    sm: Any,
    no_resume: bool,
    step_id: str | None,
    result: CountryInvestigationResult,
    label: str,
    semaphore: asyncio.Semaphore,
    job_name: str | None = None,
) -> None:
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.state_manager import compute_request_key
    from adobe_downloader.utils.winpath import to_long_path

    out_path = make_output_path(
        base_folder=output_base,
        client=client_name,
        report_name=report_def.name,
        date_range=date_range,
        file_name_extra=file_name_extra,
        segment_id=segment_id,
        job_name=job_name,
    )

    req_key = compute_request_key(
        rsid, report_def.name, date_range.from_date, date_range.to, [segment_id]
    )

    if not no_resume and sm.is_complete(req_key, step_id=step_id):
        _log.debug("SKIP %s (already done)", label)
        result.skipped += 1
        return

    req_body = build_request(
        report_def=report_def, date_range=date_range, rsid=rsid, segments=[segment_id]
    )

    async with semaphore:
        req_id, canonical_id = sm.track_request(req_key, req_body, out_path, step_id=step_id)
        sm.mark_started(req_id)

        try:
            if canonical_id is not None:
                canonical_path = sm.get_canonical_output_path(canonical_id)
                if canonical_path and to_long_path(canonical_path).exists():
                    to_long_path(out_path).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(to_long_path(canonical_path), to_long_path(out_path))
                    sm.mark_complete(req_id, out_path)
                    _log.info("COPY %s -> %s", label, out_path.name)
                    result.copied += 1
                    return

            await download_report(client, req_body, out_path)
            sm.mark_complete(req_id, out_path)
            _log.info("OK   %s -> %s", label, out_path.name)
            result.downloaded += 1

        except Exception as exc:
            sm.mark_failed(req_id, str(exc))
            _log.error("FAIL %s: %s", label, exc)
            result.failed += 1
            result.errors.append(f"{label}: {exc}")
