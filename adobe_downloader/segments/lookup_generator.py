"""Generate dimension lookup files by downloading all values from Adobe Analytics."""

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, ReportDefinitionInline
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.core.request_builder import build_request

_log = logging.getLogger(__name__)


def clean_dim_name(dimension: str) -> str:
    """Remove non-alphanumeric chars from dimension name for use in file paths."""
    return re.sub(r"[^a-zA-Z0-9]", "", dimension)


def write_lookup_file(
    lookup_path: Path,
    pairs: dict[str, str],
    dimension: str,
    client: str,
    rsid: str,
    from_date: str,
    to_date: str,
) -> None:
    """Write (or overwrite) a lookup file with sorted value|id pairs."""
    last_updated = date.today().isoformat()
    header = (
        f"/**\n"
        f" * Lookup Table for {dimension}\n"
        f" *\n"
        f" * Maps string values to their numeric IDs for use in Adobe Analytics segments.\n"
        f" *\n"
        f" * Client: {client}\n"
        f" * RSID: {rsid}\n"
        f" * Date Range: {from_date} to {to_date}\n"
        f" * Last Updated: {last_updated}\n"
        f" *\n"
        f" * Format: stringValue|numericId\n"
        f" */\n\n"
    )
    lookup_path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{k}|{v}\n" for k, v in sorted(pairs.items()))
    lookup_path.write_text(header + lines, encoding="utf-8")


def merge_into_lookup_file(
    lookup_path: Path,
    new_pairs: dict[str, str],
    dimension: str,
    client: str,
) -> dict[str, str]:
    """Merge *new_pairs* into the existing lookup file, return the combined dict."""
    from adobe_downloader.segments.create_segment import load_lookup_file

    existing = load_lookup_file(lookup_path)
    existing.update(new_pairs)

    last_updated = date.today().isoformat()
    header = (
        f"/**\n"
        f" * Lookup Table for {dimension}\n"
        f" *\n"
        f" * Maps string values to their numeric IDs for use in Adobe Analytics segments.\n"
        f" *\n"
        f" * Client: {client}\n"
        f" * Last Updated: {last_updated}\n"
        f" *\n"
        f" * Format: stringValue|numericId\n"
        f" */\n\n"
    )
    lookup_path.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(f"{k}|{v}\n" for k, v in sorted(existing.items()))
    lookup_path.write_text(header + lines, encoding="utf-8")
    return existing


def _rows_to_pairs(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Extract value→itemId pairs from API response rows, skipping incomplete rows."""
    return {
        row["value"]: str(row["itemId"])
        for row in rows
        if "value" in row and "itemId" in row
    }


async def generate_lookup_file(
    client: AdobeClient,
    client_name: str,
    dimension: str,
    rsid: str,
    date_range: DateRange,
    segments: list[str],
    lookup_base: Path,
    output_path: Path | None = None,
) -> Path:
    """Download all dimension values for *dimension* and write to a lookup file.

    Returns the path to the generated lookup file.
    """
    clean = clean_dim_name(dimension)
    report_def = ReportDefinitionInline(
        name=f"Lookup{clean}",
        dimension=dimension,
        row_limit=50000,
        segments=segments,
        metrics=[],
        csv_headers=[],
    )
    request_body = build_request(report_def, date_range, rsid)
    _log.info("Fetching lookup data for %s from %s", dimension, rsid)

    response = await client.get_report(request_body)
    rows: list[dict[str, Any]] = response.get("rows", [])
    _log.info("Retrieved %d dimension values", len(rows))

    pairs = _rows_to_pairs(rows)
    dest = output_path or (lookup_base / clean / "lookup.txt")
    write_lookup_file(dest, pairs, dimension, client_name, rsid, date_range.from_date, date_range.to)
    _log.info("Lookup file written: %s (%d pairs)", dest, len(pairs))
    return dest
