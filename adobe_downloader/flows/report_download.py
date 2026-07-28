"""Download Adobe Analytics ranked reports with date, RSID, and segment iteration."""

import asyncio
import json
import logging
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DateRange, RsidSource, SegmentSource, TestLimits
from adobe_downloader.core.api_client import AdobeClient
from adobe_downloader.utils.filenames import sanitize_segment_name_for_filename

_log = logging.getLogger(__name__)


@dataclass
class ReportDownloadResult:
    job_id: str
    json_folder: Path
    downloaded: int = 0
    skipped: int = 0
    copied: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SegmentIteration:
    """One iteration of the segments dimension of a report_download loop.

    ids: segment IDs to apply as the request's segment filter.
    id: the real Adobe segment ID, embedded in the output filename via the
        DIMSEG token only when a step explicitly opts in
        (include_segment_id_in_filename=True).
    name: sanitized human-readable name (segment_list_file source only),
        embedded in the output filename by default via resolve_segment_file_name_extra.
    """

    ids: list[str]
    id: str | None = None
    name: str | None = None


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
    job_name: str | None = None,
    rsid: str | None = None,
) -> Path:
    """Return the canonical JSON output path for one report download.

    Matches JS convention:
      {base}/{client}/JSON/{client}_{report}_{rsid}{_extra}_{DIMSEG{id}_}{from}_{to}.json
    When job_name is set, a job-specific subfolder is inserted:
      {base}/{client}/{job_name}/JSON/...
    """
    folder = Path(base_folder) / client
    if job_name:
        folder = folder / job_name
    folder = folder / "JSON"
    rsid_part = f"_{rsid}" if rsid else ""
    extra_part = f"_{file_name_extra}" if file_name_extra else ""
    seg_part = f"DIMSEG{segment_id}_" if segment_id else ""
    filename = (
        f"{client}_{report_name}{rsid_part}{extra_part}_{seg_part}"
        f"{date_range.from_date}_{date_range.to}.json"
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
            if ln.strip() and not ln.strip().startswith("#")
        ]
        yield from lines


def load_segment_list(file_path: str | Path) -> list[tuple[str, str]]:
    """Return (id, name) pairs from a segment list JSON file (list of {id, name} objects).

    Raises ValueError eagerly if any entry's name is blank, or if two entries'
    sanitized names collide — either would otherwise make two segments' downloads
    silently overwrite the same output file on disk.
    """
    data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    entries = [(entry["id"], entry.get("name", "")) for entry in data]

    seen_by_sanitized: dict[str, str] = {}
    for seg_id, name in entries:
        if not name.strip():
            raise ValueError(
                f"{file_path}: segment {seg_id!r} has a blank/missing name — every entry "
                "needs a name so downloaded files for different segments don't collide"
            )
        sanitized = sanitize_segment_name_for_filename(name)
        if sanitized in seen_by_sanitized:
            raise ValueError(
                f"{file_path}: segments {seen_by_sanitized[sanitized]!r} and {seg_id!r} both "
                f"sanitize to filename component {sanitized!r} — rename one so their "
                "downloaded files don't overwrite each other"
            )
        seen_by_sanitized[sanitized] = seg_id

    return entries


def iterate_segments(
    segments_cfg: SegmentSource | None,
) -> Iterator[SegmentIteration]:
    """Yield one SegmentIteration per iteration of the segments dimension.

    None segments_cfg  → one iteration with no segment filter.
    source="inline"    → one iteration, all IDs passed together (no filename suffix).
    source="segment_list_file" → one iteration per segment ID in the file.
    source="step_output" / "latest_segment_list" → resolved at composite job level.
    """
    if segments_cfg is None:
        yield SegmentIteration(ids=[])
    elif segments_cfg.source == "inline":
        yield SegmentIteration(ids=segments_cfg.ids or [])
    elif segments_cfg.source == "segment_list_file":
        assert segments_cfg.file is not None
        for seg_id, name in load_segment_list(segments_cfg.file):
            yield SegmentIteration(
                ids=[seg_id], id=seg_id, name=sanitize_segment_name_for_filename(name)
            )
    else:
        raise NotImplementedError(
            f"Segment source {segments_cfg.source!r} must be resolved by the composite job runner"
        )


def resolve_segment_file_name_extra(
    file_name_extra: str | None, segment: SegmentIteration
) -> str | None:
    """Merge a job-level file_name_extra with a per-segment RULE{name} anchor.

    RULE anchors the sanitized segment/bot-rule name so downstream transforms can
    locate it regardless of what else appears in the filename (mirrors the
    DIMSEG{id} anchor convention used for the opt-in raw-ID token).
    """
    if segment.name is None:
        return file_name_extra
    rule_token = f"RULE{segment.name}"
    return f"{file_name_extra}-{rule_token}" if file_name_extra else rule_token


# ---------------------------------------------------------------------------
# Core download
# ---------------------------------------------------------------------------


async def download_report(
    client: AdobeClient,
    request_body: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    """Submit one ranked report request and write the JSON response to output_path."""
    from adobe_downloader.utils.winpath import to_long_path

    _log.info("Downloading -> %s", output_path.name)
    data = await client.get_report(request_body)
    long_path = to_long_path(output_path)
    long_path.parent.mkdir(parents=True, exist_ok=True)
    long_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    row_count = len(data.get("rows", []))
    _log.info("Saved %d rows -> %s", row_count, output_path)
    return data


async def run_report_download(
    client: AdobeClient,
    client_name: str,
    report_defs: list[Any],
    rsids: RsidSource,
    date_range: DateRange,
    interval: str,
    output_base: str | Path,
    sm: Any,  # StateManager — avoid circular import
    segments: SegmentSource | None = None,
    segment_iterations: list[SegmentIteration] | None = None,
    file_name_extra: str | None = None,
    include_segment_id_in_filename: bool = False,
    no_resume: bool = False,
    step_id: str | None = None,
    test_limits: TestLimits | None = None,
    on_progress: Callable[[str, str, str], None] | None = None,
    job_name: str | None = None,
) -> ReportDownloadResult:
    """Execute the full RSIDs x date_intervals x segments x report_defs download loop.

    Returns a ReportDownloadResult with counts and the json_folder path.
    When step_id is supplied, request keys are namespaced to that step (composite jobs).
    When test_limits is supplied, each dimension is capped before iteration begins.
    on_progress(status, rsid, report_name) is called after each request.

    By default, a segment_list_file's per-segment name (not the raw segment ID) is
    what disambiguates otherwise-identical filenames across segments — pass
    include_segment_id_in_filename=True to also embed the raw ID via DIMSEG.

    segment_iterations, when given, is used verbatim instead of resolving `segments`
    — composite jobs pass this when a report_download step derives its per-rule
    filter and RULE{name} filename anchor straight from a bot_rules list.
    """
    from adobe_downloader.core.request_builder import build_request
    from adobe_downloader.state_manager import compute_request_key
    from adobe_downloader.utils.rsid_lookup import resolve_rsid_names
    from adobe_downloader.utils.winpath import to_long_path

    date_intervals = list(iterate_dates(date_range, interval))
    rsid_clean_names = list(iterate_rsids(rsids))
    rsid_list = resolve_rsid_names(rsid_clean_names)
    # Filenames use the readable clean name (e.g. "Casinoorg"), not the resolved
    # RSID (e.g. "tribecasinoorg.test") used for the API request itself.
    clean_name_by_rsid = dict(zip(rsid_list, rsid_clean_names, strict=True))
    all_segments = (
        segment_iterations if segment_iterations is not None else list(iterate_segments(segments))
    )

    if test_limits is not None:
        from adobe_downloader.utils.test_mode import apply_all_limits

        rsid_list, date_intervals, all_segments = apply_all_limits(
            rsid_list, date_intervals, all_segments, test_limits
        )

    json_folder = Path(output_base) / client_name
    if job_name:
        json_folder = json_folder / job_name
    json_folder = json_folder / "JSON"

    result = ReportDownloadResult(job_id=sm.job_id, json_folder=json_folder)
    semaphore = asyncio.Semaphore(rsids.batch_size)

    async def _process_one(
        rsid: str, date_interval: DateRange, segment: SegmentIteration, rd: Any
    ) -> None:
        req_key = compute_request_key(
            rsid,
            rd.name,
            date_interval.from_date,
            date_interval.to,
            segment.ids,
        )

        if not no_resume and sm.is_complete(req_key, step_id=step_id):
            _log.debug("SKIP %s / %s (already done)", rsid, rd.name)
            result.skipped += 1
            if on_progress:
                on_progress("SKIP", rsid, rd.name)
            return

        req_body = build_request(
            report_def=rd,
            date_range=date_interval,
            rsid=rsid,
            # A shared report def (rd.shared) ignores whichever segment this
            # iteration is looping over — its request body is then identical across
            # iterations, so the canonical-request dedup below downloads it once and
            # copies the rest, even though each iteration still gets its own
            # per-name output path.
            segments=[] if rd.shared else segment.ids,
        )
        out_path = make_output_path(
            base_folder=output_base,
            client=client_name,
            report_name=rd.name,
            date_range=date_interval,
            file_name_extra=resolve_segment_file_name_extra(file_name_extra, segment),
            segment_id=segment.id if include_segment_id_in_filename else None,
            job_name=job_name,
            rsid=clean_name_by_rsid.get(rsid, rsid),
        )

        # The semaphore bounds how many requests are in flight at once (rsids.batch_size);
        # tracking happens just inside it so "tracked before it executes" stays tight even
        # when far more items are queued than can run concurrently.
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
                        _log.info("COPY %s / %s -> %s", rsid, rd.name, out_path.name)
                        result.copied += 1
                        if on_progress:
                            on_progress("COPY", rsid, rd.name)
                        return

                await download_report(client, req_body, out_path)
                sm.mark_complete(req_id, out_path)
                _log.info("OK   %s / %s -> %s", rsid, rd.name, out_path.name)
                result.downloaded += 1
                if on_progress:
                    on_progress("OK", rsid, rd.name)

            except Exception as exc:
                sm.mark_failed(req_id, str(exc))
                _log.error("FAIL %s / %s: %s", rsid, rd.name, exc)
                result.failed += 1
                result.errors.append(f"{rsid}/{rd.name}: {exc}")
                if on_progress:
                    on_progress("FAIL", rsid, rd.name)

    await asyncio.gather(
        *(
            _process_one(rsid, date_interval, segment, rd)
            for rsid in rsid_list
            for date_interval in date_intervals
            for segment in all_segments
            for rd in report_defs
        )
    )

    return result
