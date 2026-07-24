"""Generate an RSID×country matrix for the full-run country investigation flow.

For each RSID in scope, downloads the SegmentsBuilderCountry50 report (visits by
country) and keeps every (rsid, country) pair whose visits exceed a threshold.
Countries above threshold get a `variables/geocountry` segment — reused from
country_lookup_file if one already exists for that country, created via the API
otherwise. Writes the resulting pairs to a matrix JSON file for
country_investigation to consume.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, RsidSource, TestLimits
from adobe_downloader.core.api_client import AdobeClient

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RsidCountryPair:
    rsid_clean_name: str
    country: str
    segment_id: str
    visits: int


@dataclass
class CountryMatrixResult:
    job_id: str
    matrix_file: Path
    pairs: list[RsidCountryPair] = field(default_factory=list)
    segments_created: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Country segment lookup (shared JSON file, keyed by numeric DimValueId)
# ---------------------------------------------------------------------------


def load_country_lookup(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")))


def save_country_lookup(path: Path, entries: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _find_segment_id(entries: list[dict[str, str]], dim_value_id: str) -> str | None:
    for entry in entries:
        if entry.get("DimValueId") == dim_value_id:
            return entry.get("SegmentId")
    return None


# ---------------------------------------------------------------------------
# Matrix file I/O
# ---------------------------------------------------------------------------


def write_matrix_file(path: Path, pairs: list[RsidCountryPair]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "rsid_clean_name": p.rsid_clean_name,
            "country": p.country,
            "segment_id": p.segment_id,
            "visits": p.visits,
        }
        for p in pairs
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


_LEGACY_KEY_MAP = {
    "rsidCleanName": "rsid_clean_name",
    "geocountry": "country",
    "segmentId": "segment_id",
    "visits": "visits",
}


def load_matrix_file(path: Path) -> list[RsidCountryPair]:
    """Load a matrix JSON file.

    Accepts both this tool's field names (rsid_clean_name/country/segment_id/visits)
    and the legacy JS tool's (rsidCleanName/geocountry/segmentId/visits) — e.g.
    data/rsid_country_thresholds/botInvestigationRsidCountriesMinThreshold.json,
    migrated as-is from the old BotInvestigationGenerateCountrySegments.js output.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = []
    for item in data:
        if "rsidCleanName" in item:
            item = {_LEGACY_KEY_MAP[k]: v for k, v in item.items() if k in _LEGACY_KEY_MAP}
        pairs.append(RsidCountryPair(**item))
    return pairs


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def run_generate_country_matrix(
    client: AdobeClient,
    client_name: str,
    rsids: RsidSource,
    rsid_lookup_file: Path,
    date_range: DateRange,
    visit_threshold: int,
    country_lookup_file: Path,
    matrix_file: Path,
    sm: Any,
    share_with_users: list[str] | None = None,
    no_resume: bool = False,
    step_id: str | None = None,
    test_limits: TestLimits | None = None,
    job_name: str | None = None,
    output_base: str | Path = "",
) -> CountryMatrixResult:
    """Build the RSID×country matrix, creating segments for newly-qualifying countries.

    Downloads SegmentsBuilderCountry50 once per RSID (tracked via *sm* like any
    other API request). Countries with visits > visit_threshold are kept; a
    country segment is reused from country_lookup_file if one already exists for
    that country's DimValueId, otherwise created via the API and appended so the
    next run (any RSID, any job) reuses it instead of creating a duplicate.
    """
    from adobe_downloader.config.report_definitions import load_report_registry
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.flows.report_download import (
        download_report,
        iterate_rsids,
        make_output_path,
    )
    from adobe_downloader.segments.create_segment import build_single_condition_segment
    from adobe_downloader.state_manager import compute_request_key
    from adobe_downloader.utils.rsid_lookup import load_rsid_lookup
    from adobe_downloader.utils.winpath import to_long_path

    rsid_map = load_rsid_lookup(rsid_lookup_file)
    report_def = load_report_registry()["SegmentsBuilderCountry50"]
    rsid_list = list(iterate_rsids(rsids))

    if test_limits is not None:
        from adobe_downloader.utils.test_mode import apply_rsid_limit

        rsid_list = apply_rsid_limit(rsid_list, test_limits)

    lookup_entries = load_country_lookup(country_lookup_file)
    lookup_modified = False

    result = CountryMatrixResult(job_id=sm.job_id, matrix_file=matrix_file)
    seen_pairs: set[tuple[str, str]] = set()

    for clean_name in rsid_list:
        rsid = rsid_map.get(clean_name)
        if rsid is None:
            _log.warning("No RSID found for clean name %r — skipping", clean_name)
            result.failed += 1
            result.errors.append(f"No RSID for clean name {clean_name!r}")
            continue

        req_body = build_request(
            report_def=report_def, date_range=date_range, rsid=rsid, segments=[]
        )
        out_path = make_output_path(
            base_folder=output_base,
            client=client_name,
            report_name=report_def.name,
            date_range=date_range,
            rsid=clean_name,
            job_name=job_name,
        )
        req_key = compute_request_key(
            rsid, report_def.name, date_range.from_date, date_range.to, []
        )

        if not no_resume and sm.is_complete(req_key, step_id=step_id):
            data = json.loads(to_long_path(out_path).read_text(encoding="utf-8"))
        else:
            req_id, _canonical_id = sm.track_request(req_key, req_body, out_path, step_id=step_id)
            sm.mark_started(req_id)
            try:
                data = await download_report(client, req_body, out_path)
                sm.mark_complete(req_id, out_path)
            except Exception as exc:
                sm.mark_failed(req_id, str(exc))
                _log.error("FAIL SegmentsBuilderCountry50/%s: %s", clean_name, exc)
                result.failed += 1
                result.errors.append(f"{clean_name}: {exc}")
                continue

        for row in data.get("rows", []):
            visits = row.get("data", [0, 0])[1] if len(row.get("data", [])) > 1 else 0
            if visits <= visit_threshold:
                continue

            country = str(row.get("value", ""))
            item_id = str(row.get("itemId", ""))
            if not country or not item_id:
                continue

            pair_key = (clean_name, country)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            segment_id = _find_segment_id(lookup_entries, item_id)
            if segment_id is None:
                seg_def = build_single_condition_segment(
                    name=f"variables/geocountry = {country}",
                    rsid=rsid,
                    dimension="Country",
                    value=item_id,
                    is_numeric=True,
                )
                try:
                    api_result = await client.create_segment(seg_def)
                    segment_id = api_result["id"]
                    if share_with_users:
                        await client.share_segment(segment_id, share_with_users)
                    lookup_entries.append(
                        {
                            "SegmentId": segment_id,
                            "SegmentName": seg_def["name"],
                            "DimValueId": item_id,
                            "DimValueName": country,
                        }
                    )
                    lookup_modified = True
                    result.segments_created += 1
                    _log.info("Created country segment for %s: %s", country, segment_id)
                except Exception as exc:
                    _log.error("FAIL create segment for %s: %s", country, exc)
                    result.failed += 1
                    result.errors.append(f"segment for {country!r}: {exc}")
                    continue

            result.pairs.append(
                RsidCountryPair(
                    rsid_clean_name=clean_name,
                    country=country,
                    segment_id=segment_id,
                    visits=int(visits),
                )
            )

    if lookup_modified:
        save_country_lookup(country_lookup_file, lookup_entries)

    write_matrix_file(matrix_file, result.pairs)
    return result
