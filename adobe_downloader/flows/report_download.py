"""Download Adobe Analytics ranked reports with date, RSID, and segment iteration."""

import json
import logging
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, RsidSource, SegmentSource
from adobe_downloader.core.api_client import AdobeClient

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output path construction
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Iteration helpers
# ---------------------------------------------------------------------------


def iterate_dates(date_range: DateRange, interval: str) -> Iterator[DateRange]:
    """Yield DateRange sub-intervals split according to interval.

    interval="full"  → one item (the whole range unchanged)
    interval="month" → one item per calendar month boundary
    interval="day"   → one item per day
    """
    if interval == "full":
        yield date_range
        return

    start = date.fromisoformat(date_range.from_date)
    end = date.fromisoformat(date_range.to)

    current = start
    while current < end:
        if interval == "day":
            period_end = min(current + timedelta(days=1), end)
        else:  # month
            if current.month == 12:
                next_month = date(current.year + 1, 1, 1)
            else:
                next_month = date(current.year, current.month + 1, 1)
            period_end = min(next_month, end)
        yield DateRange.model_validate({"from": current.isoformat(), "to": period_end.isoformat()})
        current = period_end


def iterate_rsids(rsids_cfg: RsidSource) -> Iterator[str]:
    """Yield all RSID strings from the configured source."""
    if rsids_cfg.source == "single":
        assert rsids_cfg.single is not None
        yield rsids_cfg.single
    elif rsids_cfg.source == "list":
        assert rsids_cfg.rsid_list is not None
        yield from rsids_cfg.rsid_list
    else:  # file
        assert rsids_cfg.file is not None
        lines = [
            ln.strip()
            for ln in Path(rsids_cfg.file).read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        yield from lines


def load_segment_list(file_path: str | Path) -> list[str]:
    """Return segment IDs from a segment list JSON file (list of {id, name} objects)."""
    data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    return [entry["id"] for entry in data]


def iterate_segments(
    segments_cfg: SegmentSource | None,
) -> Iterator[tuple[str | None, list[str]]]:
    """Yield (segment_id_for_filename, segment_ids_for_request) pairs.

    None segments_cfg  → one iteration with no segment filter.
    source="inline"    → one iteration, all IDs passed together (no filename suffix).
    source="segment_list_file" → one iteration per segment ID in the file.
    source="step_output" / "latest_segment_list" → resolved at composite job level.
    """
    if segments_cfg is None:
        yield None, []
    elif segments_cfg.source == "inline":
        yield None, segments_cfg.ids or []
    elif segments_cfg.source == "segment_list_file":
        assert segments_cfg.file is not None
        for seg_id in load_segment_list(segments_cfg.file):
            yield seg_id, [seg_id]
    else:
        raise NotImplementedError(
            f"Segment source {segments_cfg.source!r} must be resolved by the composite job runner"
        )


# ---------------------------------------------------------------------------
# Core download
# ---------------------------------------------------------------------------


async def download_report(
    client: AdobeClient,
    request_body: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Submit one ranked report request and write the JSON response to output_path."""
    _log.info("Downloading -> %s", output_path.name)
    data = await client.get_report(request_body)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    row_count = len(data.get("rows", []))
    _log.info("Saved %d rows -> %s", row_count, output_path)
    return data
