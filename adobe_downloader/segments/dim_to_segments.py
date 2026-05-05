"""Create one segment per dimension value; save a segment list JSON."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DimSegmentsResult:
    segment_list_file: Path
    segments: list[dict[str, str]] = field(default_factory=list)


def _build_dim_segment_def(dimension: str, item_id: str, value: str, rsid: str) -> dict[str, Any]:
    """Build a hits-context numeric-equality segment for one dimension value."""
    return {
        "name": f"{dimension} = {value}",
        "description": "Created via API",
        "definition": {
            "container": {
                "func": "container",
                "context": "hits",
                "pred": {
                    "val": {"func": "attr", "name": dimension},
                    "func": "eq",
                    "num": int(item_id),
                    "description": "Dimension value",
                },
            },
            "func": "segment",
            "version": [1, 0, 0],
        },
        "isPostShardId": True,
        "rsid": rsid,
    }


async def dim_to_segments(
    client: Any,
    dimension: str,
    rsid: str,
    date_range: Any,  # DateRange
    output_path: Path,
    additional_segments: list[str] | None = None,
    num_pairs: int = 1,
    name_prefix: str = "CompatabilityPrefix",
) -> DimSegmentsResult:
    """Download dimension values, create one segment per value, save list JSON.

    Args:
        client: ``AdobeClient`` instance.
        dimension: Adobe variable ID (e.g. ``variables/geocountry``).
        rsid: Report suite ID used for the lookup request and segment definitions.
        date_range: DateRange used for the dimension-value lookup request.
        output_path: Where to write the segment list JSON.
        additional_segments: Extra segment IDs to include in the lookup request.
        num_pairs: Maximum number of dimension values to process.
        name_prefix: Unused — kept for API compatibility.

    Returns:
        :class:`DimSegmentsResult` with ``segment_list_file`` and ``segments``.
    """
    from adobe_downloader.config.schema import ReportDefinitionInline
    from adobe_downloader.core.request_builder import build_request

    # --- Step 1: fetch dimension values ---
    lookup_def = ReportDefinitionInline(
        name="dim_lookup",
        dimension=dimension,
        metrics=[],
        csv_headers=[],
        row_limit=num_pairs,
    )
    request_body = build_request(
        report_def=lookup_def,
        date_range=date_range,
        rsid=rsid,
        segments=additional_segments or [],
    )
    # Raise the limit in settings to match num_pairs
    request_body["settings"]["limit"] = num_pairs

    logger.info("Fetching dimension values for %s from %s", dimension, rsid)
    response = await client.get_report(request_body)

    rows = response.get("rows", [])
    pairs = [
        {"value": row["value"], "itemId": row["itemId"]}
        for row in rows
        if row.get("value") and row.get("itemId")
    ]
    logger.info("Extracted %d pairs (limit %d)", len(pairs), num_pairs)

    # --- Step 2: create segments ---
    segments: list[dict[str, str]] = []
    for pair in pairs:
        value = pair["value"]
        item_id = pair["itemId"]
        seg_def = _build_dim_segment_def(dimension, item_id, value, rsid)
        try:
            result = await client.create_segment(seg_def)
            seg_id = result["id"]
            raw_name = result["name"]
            formatted_name = re.sub(r"\s+", "", raw_name.replace(":", "-"))
            segments.append({"id": seg_id, "name": formatted_name})
            logger.info("Created segment %s → %s", seg_id, formatted_name)
        except Exception as exc:
            logger.error("Failed to create segment for %r: %s", value, exc)

    # --- Step 3: save segment list ---
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")
    logger.info("Saved %d segments → %s", len(segments), output_path)

    return DimSegmentsResult(segment_list_file=output_path, segments=segments)
