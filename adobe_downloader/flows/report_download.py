"""Download a single Adobe Analytics ranked report and save to disk."""

import json
import logging
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange
from adobe_downloader.core.api_client import AdobeClient

_log = logging.getLogger(__name__)


def make_output_path(
    base_folder: str | Path,
    client: str,
    report_name: str,
    date_range: DateRange,
    file_name_extra: str | None = None,
    segment_id: str | None = None,
) -> Path:
    """Return the canonical JSON output path for one report download.

    Matches JS convention:
      {base}/{client}/JSON/{client}_{report}{_extra}_{DIMSEG{id}_}{from}_{to}.json
    """
    folder = Path(base_folder) / client / "JSON"
    extra_part = f"_{file_name_extra}" if file_name_extra else ""
    seg_part = f"DIMSEG{segment_id}_" if segment_id else ""
    filename = (
        f"{client}_{report_name}{extra_part}_"
        f"{seg_part}{date_range.from_date}_{date_range.to}.json"
    )
    return folder / filename


async def download_report(
    client: AdobeClient,
    request_body: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Submit one ranked report request and write the JSON response to output_path."""
    _log.info("Downloading → %s", output_path.name)
    data = await client.get_report(request_body)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    row_count = len(data.get("rows", []))
    _log.info("Saved %d rows → %s", row_count, output_path)
    return data
