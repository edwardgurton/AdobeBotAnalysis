"""Final bot rule metrics flow.

For each RSID × each segment in the validated segment list:
  - LegendFinalBotMetricsUnfilteredVisitsByYear: one download per RSID × segment
    (segment applied to request; rsidName + botRuleName encoded in file_name_extra)
  - LegendFinalBotMetricsCurrentIncludeByYear and DevelopmentIncludeByYear:
    one download per RSID only (baked-in segment from report def; job_name in file_name_extra)
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, RsidSource
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.flows.report_download import download_report, make_output_path

_log = logging.getLogger(__name__)

# Reports that are downloaded once per RSID × segment.
# All other reports in the group are downloaded once per RSID (aggregate).
_PER_SEGMENT_REPORTS: frozenset[str] = frozenset(
    {"LegendFinalBotMetricsUnfilteredVisitsByYear"}
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class SegmentEntry:
    id: str
    name: str
    suffix: str  # part after '=' in name, stripped and spaces replaced with hyphens


@dataclass
class FinalBotMetricsResult:
    job_id: str
    json_folder: Path
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Segment list loading
# ---------------------------------------------------------------------------


def load_segment_list_with_names(file_path: Path) -> list[SegmentEntry]:
    """Load a segment list JSON file, extracting suffix from name.

    Segment name format: ``PrefixKey=SuffixValue``
    The suffix is the part after ``=``, stripped of whitespace, with spaces
    replaced by hyphens so it is safe to embed in a filename.
    """
    data = json.loads(file_path.read_text(encoding="utf-8"))
    entries: list[SegmentEntry] = []
    for item in data:
        name: str = item["name"]
        if "=" in name:
            raw_suffix = name.split("=", 1)[1].strip()
        else:
            raw_suffix = name.strip()
        suffix = raw_suffix.replace(" ", "-")
        entries.append(SegmentEntry(id=item["id"], name=name, suffix=suffix))
    return entries


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def run_final_bot_metrics(
    client: AdobeClient,
    client_name: str,
    rsids: RsidSource,
    rsid_lookup_file: Path,
    segment_list_file: Path,
    job_name: str,
    date_range: DateRange,
    interval: str,
    output_base: str | Path,
    sm: Any,
    no_resume: bool = False,
    step_id: str | None = None,
) -> FinalBotMetricsResult:
    """Download final bot metrics for all RSIDs.

    Per-segment reports (Unfiltered): iterate RSIDs × segments, applying the
    segment from the list to each request.  file_name_extra encodes
    ``{job_name}_{clean_name}_{seg_suffix}`` so the transform can extract
    rsidName (parts[3]) and botRuleName (parts[4]).

    Aggregate reports (Current/Development Include): iterate RSIDs only.
    The baked-in segments from the report definition are used; no per-segment
    iteration.  file_name_extra is just ``{job_name}``.
    """
    from adobe_downloader.config.report_definitions import load_report_group
    from adobe_downloader.flows.report_download import iterate_dates, iterate_rsids
    from adobe_downloader.utils.rsid_lookup import load_rsid_lookup

    rsid_map = load_rsid_lookup(rsid_lookup_file)
    report_defs = load_report_group("final_bot_metrics")
    segments = load_segment_list_with_names(segment_list_file)
    date_intervals = list(iterate_dates(date_range, interval))
    json_folder = Path(output_base) / client_name / "JSON"

    result = FinalBotMetricsResult(job_id=sm.job_id, json_folder=json_folder)

    for clean_name in iterate_rsids(rsids):
        rsid = rsid_map.get(clean_name)
        if rsid is None:
            _log.warning("No RSID found for clean name %r — skipping", clean_name)
            result.failed += 1
            result.errors.append(f"No RSID for clean name {clean_name!r}")
            continue

        for report_def in report_defs:
            if report_def.name in _PER_SEGMENT_REPORTS:
                for seg in segments:
                    file_extra = f"{job_name}_{clean_name}_{seg.suffix}"
                    for date_interval in date_intervals:
                        await _download_one(
                            client=client,
                            client_name=client_name,
                            report_def=report_def,
                            date_range=date_interval,
                            rsid=rsid,
                            segments=[seg.id],
                            file_name_extra=file_extra,
                            output_base=output_base,
                            sm=sm,
                            no_resume=no_resume,
                            step_id=step_id,
                            result=result,
                            label=f"{clean_name}/{report_def.name}/{seg.suffix}",
                        )
            else:
                file_extra = job_name
                for date_interval in date_intervals:
                    await _download_one(
                        client=client,
                        client_name=client_name,
                        report_def=report_def,
                        date_range=date_interval,
                        rsid=rsid,
                        segments=[],
                        file_name_extra=file_extra,
                        output_base=output_base,
                        sm=sm,
                        no_resume=no_resume,
                        step_id=step_id,
                        result=result,
                        label=f"{clean_name}/{report_def.name}",
                    )

    return result


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


async def _download_one(
    client: AdobeClient,
    client_name: str,
    report_def: Any,
    date_range: DateRange,
    rsid: str,
    segments: list[str],
    file_name_extra: str | None,
    output_base: str | Path,
    sm: Any,
    no_resume: bool,
    step_id: str | None,
    result: FinalBotMetricsResult,
    label: str,
) -> None:
    """Download one report variant, updating *result* in place.

    segment_id is intentionally NOT passed to make_output_path — the segment
    information is encoded in file_name_extra so the transform can extract
    rsidName and botRuleName from positional filename parts.
    """
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.state_manager import compute_request_key

    out_path = make_output_path(
        base_folder=output_base,
        client=client_name,
        report_name=report_def.name,
        date_range=date_range,
        file_name_extra=file_name_extra,
        segment_id=None,
    )

    req_key = compute_request_key(
        rsid,
        report_def.name,
        date_range.from_date,
        date_range.to,
        segments,
    )

    if not no_resume and sm.is_complete(req_key, step_id=step_id):
        _log.debug("SKIP %s (already done)", label)
        result.skipped += 1
        return

    req_body = build_request(
        report_def=report_def,
        date_range=date_range,
        rsid=rsid,
        segments=segments,
    )

    req_id, canonical_id = sm.track_request(req_key, req_body, out_path, step_id=step_id)
    sm.mark_started(req_id)

    try:
        if canonical_id is not None:
            canonical_path = sm.get_canonical_output_path(canonical_id)
            if canonical_path and canonical_path.exists():
                out_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(canonical_path, out_path)
                sm.mark_complete(req_id, out_path)
                _log.info("COPY %s -> %s", label, out_path.name)
                result.downloaded += 1
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
