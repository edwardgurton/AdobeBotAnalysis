"""Fetch a segment definition from the Adobe API and save it locally."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_API_BASE = "https://analytics.adobe.io/api"


async def save_segment(
    client: Any,
    segment_id: str,
    output_path: Path,
) -> dict:
    """Fetch *segment_id* from the API and write the JSON to *output_path*.

    Returns the raw segment dict from the API.
    """
    resp = await client._get(  # type: ignore[attr-defined]
        f"{_API_BASE}/{client._company_id}/segments/{segment_id}",
        params={"expansion": "definition,rsid,owner,tags"},
    )
    data: dict = resp.json()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Saved segment %s -> %s", segment_id, output_path)
    return data
