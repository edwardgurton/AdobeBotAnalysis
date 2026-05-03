"""Search for a dimension value across RSIDs and update the local lookup file."""

import logging
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, ReportDefinitionInline
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.core.request_builder import build_request
from adobe_downloader.segments.create_segment import load_lookup_file
from adobe_downloader.segments.lookup_generator import clean_dim_name, merge_into_lookup_file

_log = logging.getLogger(__name__)


async def search_lookup_value(
    client: AdobeClient,
    client_name: str,
    dimension: str,
    value: str,
    rsid_list: list[str],
    date_range: DateRange,
    lookup_base: Path,
) -> str | None:
    """Search for *value* in the local lookup file, then across RSIDs if not found.

    Merges any newly discovered pairs into the local lookup file.
    Returns the numeric ID string if found, or ``None``.
    """
    clean = clean_dim_name(dimension)
    lookup_path = lookup_base / clean / "lookup.txt"
    existing = load_lookup_file(lookup_path)

    if value in existing:
        _log.info("Value %r found in local lookup: %s", value, existing[value])
        return existing[value]

    _log.info("Value %r not found locally; searching %d RSID(s)", value, len(rsid_list))

    report_def = ReportDefinitionInline(
        name=f"Lookup{clean}",
        dimension=dimension,
        row_limit=50000,
        segments=[],
        metrics=[],
        csv_headers=[],
    )

    for rsid in rsid_list:
        request_body = build_request(report_def, date_range, rsid)
        rows: list[dict[str, Any]] = []
        try:
            response = await client.get_report(request_body)
            rows = response.get("rows", [])
        except Exception:
            _log.warning("Failed to fetch data for RSID %s, skipping", rsid)
            continue

        new_pairs: dict[str, str] = {}
        for row in rows:
            sv = row.get("value")
            ni = row.get("itemId")
            if sv and ni and sv not in existing:
                new_pairs[sv] = str(ni)

        if new_pairs:
            _log.info("RSID %s: discovered %d new value(s)", rsid, len(new_pairs))
            existing = merge_into_lookup_file(lookup_path, new_pairs, dimension, client_name)

        if value in existing:
            found_id = existing[value]
            _log.info("Value %r found in RSID %s: %s", value, rsid, found_id)
            return found_id

    _log.warning("Value %r not found in any of %d RSID(s)", value, len(rsid_list))
    return None
