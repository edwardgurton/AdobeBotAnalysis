"""Bot rule comparison flow.

For each RSID × bot rule, downloads 9 of 10 bot-investigation dimensions
(skipping the one used to build the rule) in two variants:
  - Segment:    with the rule's segment ID   → unique per rule
  - AllTraffic: no segment filter             → canonical dedup via StateManager
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.flows.report_download import download_report, make_output_path

_log = logging.getLogger(__name__)

# Maps the short dimension names used in CSV files to full report names.
DIMENSION_MAPPING: dict[str, str] = {
    "UserAgent": "botInvestigationMetricsByUserAgent",
    "Region": "botInvestigationMetricsByRegion",
    "MonitorResolution": "botInvestigationMetricsByMonitorResolution",
    "PageURL": "botInvestigationMetricsByPageURL",
    "Domain": "botInvestigationMetricsByDomain",
    "BrowserType": "botInvestigationMetricsByBrowserType",
    "OperatingSystem": "botInvestigationMetricsByOperatingSystem",
    "Operating System": "botInvestigationMetricsByOperatingSystem",
    "MobileManufacturer": "botInvestigationMetricsByMobileManufacturer",
    "HourOfDay": "botInvestigationMetricsByHourOfDay",
    "MarketingChannel": "botInvestigationMetricsByMarketingChannel",
    "ReferringDomain": "botInvestigationMetricsByMarketingChannel",
    "Marketing Channel": "botInvestigationMetricsByMarketingChannel",
    "Referring Domain": "botInvestigationMetricsByMarketingChannel",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class BotRule:
    segment_id: str
    segment_name: str
    report_to_skip: str  # full report name, e.g. "botInvestigationMetricsByDomain"


@dataclass
class BotRuleCompareResult:
    job_id: str
    json_folder: Path
    downloaded: int = 0
    skipped: int = 0
    copied: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def parse_bot_rule_csv(csv_path: Path) -> list[BotRule]:
    """Parse a bot-rule CSV into a list of BotRule objects.

    Expected columns: DimSegmentId, botRuleName, reportToIgnore
    reportToIgnore may be a short name (e.g. "Domain") or a full report name.
    """
    text = csv_path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError(f"CSV must have a header row and at least one data row: {csv_path}")

    header = [h.strip() for h in lines[0].split(",")]
    try:
        seg_id_idx = header.index("DimSegmentId")
        rule_name_idx = header.index("botRuleName")
        ignore_idx = header.index("reportToIgnore")
    except ValueError as exc:
        raise ValueError(
            f"CSV {csv_path} must have columns: DimSegmentId, botRuleName, reportToIgnore"
        ) from exc

    rules: list[BotRule] = []
    for i, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        values = [v.strip() for v in line.split(",")]
        seg_id = values[seg_id_idx]
        rule_name = values[rule_name_idx]
        short_name = values[ignore_idx]

        # Map short dimension name → full report name; fall back to constructed name
        full_report = DIMENSION_MAPPING.get(short_name)
        if full_report is None:
            if short_name.startswith("botInvestigationMetricsBy"):
                full_report = short_name
            else:
                _log.warning("Row %d: unknown reportToIgnore %r — constructing name", i, short_name)
                full_report = f"botInvestigationMetricsBy{short_name}"

        rules.append(BotRule(segment_id=seg_id, segment_name=rule_name, report_to_skip=full_report))

    return rules


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def run_bot_rule_compare(
    client: AdobeClient,
    client_name: str,
    rsid_clean_names: list[str],
    rsid_lookup_file: Path,
    bot_rules: list[BotRule],
    date_range: DateRange,
    comparison_round: float,
    output_base: str | Path,
    sm: Any,
    no_resume: bool = False,
    step_id: str | None = None,
) -> BotRuleCompareResult:
    """Download Segment + AllTraffic comparison files for each RSID × bot rule.

    AllTraffic files are deduplicated via StateManager's canonical_request_id: the
    second AllTraffic request for the same RSID+report+date has an identical request
    body, so StateManager returns a canonical_id and the file is copied rather than
    re-downloaded.
    """
    from adobe_downloader.config.report_definitions import load_report_group
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.state_manager import compute_request_key
    from adobe_downloader.utils.rsid_lookup import load_rsid_lookup

    rsid_map = load_rsid_lookup(rsid_lookup_file)
    report_defs = load_report_group("bot_rule_compare")
    json_folder = Path(output_base) / client_name / "JSON"

    result = BotRuleCompareResult(job_id=sm.job_id, json_folder=json_folder)

    for clean_name in rsid_clean_names:
        rsid = rsid_map.get(clean_name)
        if rsid is None:
            _log.warning("No RSID found for clean name %r — skipping", clean_name)
            result.failed += 1
            result.errors.append(f"No RSID for clean name {clean_name!r}")
            continue

        for bot_rule in bot_rules:
            investigation_name = (
                f"{clean_name}-{bot_rule.segment_name}-Compare-V{comparison_round}"
            )

            for report_def in report_defs:
                if report_def.name == bot_rule.report_to_skip:
                    _log.debug("SKIP report %s (reportToSkip for rule %s)", report_def.name, bot_rule.segment_name)
                    continue

                # --- Segment download (unique per rule) ---
                await _download_variant(
                    client=client,
                    client_name=client_name,
                    report_def=report_def,
                    date_range=date_range,
                    rsid=rsid,
                    segments=[bot_rule.segment_id],
                    file_name_extra=f"{investigation_name}-Segment",
                    segment_id_for_path=bot_rule.segment_id,
                    output_base=output_base,
                    sm=sm,
                    no_resume=no_resume,
                    step_id=step_id,
                    result=result,
                    label=f"{clean_name}/{report_def.name}/Segment",
                )

                # --- AllTraffic download (canonical dedup across rules) ---
                await _download_variant(
                    client=client,
                    client_name=client_name,
                    report_def=report_def,
                    date_range=date_range,
                    rsid=rsid,
                    segments=[],
                    file_name_extra=f"{investigation_name}-AllTraffic",
                    segment_id_for_path=None,
                    output_base=output_base,
                    sm=sm,
                    no_resume=no_resume,
                    step_id=step_id,
                    result=result,
                    label=f"{clean_name}/{report_def.name}/AllTraffic",
                )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _download_variant(
    client: AdobeClient,
    client_name: str,
    report_def: Any,
    date_range: DateRange,
    rsid: str,
    segments: list[str],
    file_name_extra: str,
    segment_id_for_path: str | None,
    output_base: str | Path,
    sm: Any,
    no_resume: bool,
    step_id: str | None,
    result: BotRuleCompareResult,
    label: str,
) -> None:
    """Download one Segment or AllTraffic variant, updating *result* in place.

    The request key includes the output filename so that AllTraffic files for
    different bot rules (same body, different investigation names) each get their
    own DB row — enabling the canonical dedup to trigger for the second+ rule.
    """
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.state_manager import compute_request_key

    out_path = make_output_path(
        base_folder=output_base,
        client=client_name,
        report_name=report_def.name,
        date_range=date_range,
        file_name_extra=file_name_extra,
        segment_id=segment_id_for_path,
    )

    # Include output filename in the key so each AllTraffic investigation name
    # gets its own DB row (enabling canonical copy detection via body hash).
    base_key = compute_request_key(
        rsid,
        report_def.name,
        date_range.from_date,
        date_range.to,
        segments,
    )
    req_key = f"{base_key}|{out_path.name}"

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
