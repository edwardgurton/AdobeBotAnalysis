"""Post-run enrichment of segment records (MDL plan A7).

Runs after the validation and compare downloads of a round. It:

1. back-fills the real segment ID into any record still holding ``UPDATE-SEGMENT-ID``
   (Special rows, once their segment has been created in Adobe and the list edited);
2. warns about any validate segment that is not tagged with the candidate tag (the
   technical account cannot tag segments it does not own, see MDL plan D9);
3. sums each validate rule's visits for the 12 calendar months ending with the month
   of ``date_to``, across every RSID in the run, from the ``VALIDATION_*`` outputs,
   and writes the total into the YAML record (compares keep ``null``);
4. writes ``{RoundID}_segment_records.csv`` (the Decision Log import) and one
   ``{RuleID}_segment_details.csv`` per compare (the Bot Rule Compare input tab).
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DEFAULT_CANDIDATE_TAG, DEFAULT_VISITS_REPORT
from adobe_downloader.segments.segment_records import (
    PLACEHOLDER_SEGMENT_ID,
    load_record,
    record_filename,
    save_record,
)
from adobe_downloader.utils.filenames import sanitize_segment_name_for_filename

logger = logging.getLogger(__name__)

VALIDATE = "Validate"
COMPARE = "Compare"

RECORDS_CSV_COLUMNS = [
    "RuleID",
    "RoundID",
    "CompareValidate",
    "SegmentId",
    "SegmentName",
    "BotRuleName",
    "BotRuleNumber",
    "RSIDCleanName",
    "Dimension1",
    "Dimension1Item",
    "Dimension2",
    "Dimension2Item",
    "Dimension3",
    "Dimension3Item",
    "Dimension4",
    "Dimension4Item",
    "Visits12m",
    "VisitsFrom",
    "VisitsTo",
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ListEntry:
    kind: str  # VALIDATE or COMPARE (the list it came from)
    segment_id: str
    bot_rule_name: str


@dataclass
class _Matched:
    entry: ListEntry
    path: Path | None
    record: dict[str, Any] | None


@dataclass
class SegmentRecordsResult:
    records_updated: int = 0
    # "botRuleName: segment_id" for each record whose placeholder ID was replaced.
    backfilled: list[str] = field(default_factory=list)
    # Validate segments in the run that are not tagged with the candidate tag.
    untagged: list[str] = field(default_factory=list)
    # Set when the tag lookup failed; the run carries on without the check.
    tag_check_error: str | None = None
    # Validate segments still holding the placeholder (no visits, no tag check).
    still_placeholder: list[str] = field(default_factory=list)
    # List rows with no YAML record (e.g. lists made before records existed).
    missing_records: list[str] = field(default_factory=list)
    # Validate rules with no rows of the visits report in the outputs.
    missing_visits: list[str] = field(default_factory=list)
    records_csv: Path | None = None
    details_files: list[Path] = field(default_factory=list)
    window: tuple[date, date] | None = None


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def read_list(path: Path, kind: str) -> list[ListEntry]:
    """Read a compare or validate list CSV (``DimSegmentId``, ``botRuleName``)."""
    entries: list[ListEntry] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("botRuleName") or "").strip()
            if not name:
                continue
            entries.append(
                ListEntry(
                    kind=kind,
                    segment_id=(row.get("DimSegmentId") or "").strip(),
                    bot_rule_name=name,
                )
            )
    return entries


def _index_records(records_path: Path) -> dict[str, list[tuple[Path, dict[str, Any]]]]:
    """Map ``bot_rule_name`` to the record(s) carrying it."""
    index: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    if not records_path.is_dir():
        return index
    for path in sorted(records_path.glob("*.yaml")):
        try:
            record = load_record(path)
        except Exception as exc:
            logger.warning("Skipping unreadable segment record %s: %s", path, exc)
            continue
        name = record.get("bot_rule_name")
        if name:
            index[str(name)].append((path, record))
    return index


def _match(entry: ListEntry, index: dict[str, list[tuple[Path, dict[str, Any]]]]) -> _Matched:
    candidates = index.get(entry.bot_rule_name, [])
    if not candidates:
        return _Matched(entry, None, None)
    if len(candidates) > 1:
        # Prefer the record with this segment ID, then the newest.
        same_id = [c for c in candidates if c[1].get("segment_id") == entry.segment_id]
        pool = same_id or candidates
        pool.sort(key=lambda c: str(c[1].get("created_at") or ""))
        logger.warning(
            "%d records share botRuleName %r; using %s",
            len(candidates),
            entry.bot_rule_name,
            pool[-1][0].name,
        )
        return _Matched(entry, *pool[-1])
    return _Matched(entry, *candidates[0])


# ---------------------------------------------------------------------------
# Visits
# ---------------------------------------------------------------------------


def twelve_month_window(date_to: date) -> tuple[date, date]:
    """First day of the month 11 months before *date_to*'s month, and *date_to*.

    The validation reports are monthly, so the window is 12 whole calendar months:
    a *date_to* of 2026-08-25 gives 2025-09-01 to 2026-08-25.
    """
    months = date_to.year * 12 + (date_to.month - 1) - 11
    year, month0 = divmod(months, 12)
    return date(year, month0 + 1, 1), date_to


def _month_start(row: dict[str, str]) -> date | None:
    """Month of a validation row, from ``month`` ("Sep 2025") or Adobe's ``id`` (1YYMMDD)."""
    label = (row.get("month") or "").strip()
    try:
        return datetime.strptime(label, "%b %Y").date()
    except ValueError:
        pass
    item_id = (row.get("id") or "").strip()
    # daterangemonth item IDs are 1YYMMDD with a 0-based month: 1250801 is Sep 2025.
    if len(item_id) == 7 and item_id.isdigit() and item_id[0] == "1":
        try:
            return date(2000 + int(item_id[1:3]), int(item_id[3:5]) + 1, 1)
        except ValueError:
            return None
    return None


def _to_float(value: str | None) -> float:
    try:
        number = float(value or 0)
    except ValueError:
        return 0.0
    return 0.0 if number != number else number  # NaN -> 0


def sum_visits(
    csv_files: list[Path], report_name: str, window: tuple[date, date]
) -> dict[str, float]:
    """Sum ``visits`` of *report_name* rows inside *window*, keyed by ``botRuleName``.

    Every RSID's rows count towards the same rule. A rule with rows of the report but
    none inside the window gets 0; a rule with no rows of the report is absent.
    """
    start, end = window
    totals: dict[str, float] = {}
    for path in csv_files:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                if (row.get("requestName") or "").strip() != report_name:
                    continue
                rule = (row.get("botRuleName") or "").strip()
                if not rule:
                    continue
                totals.setdefault(rule, 0.0)
                month = _month_start(row)
                if month is None:
                    logger.warning("%s: row with unreadable month %r skipped", path.name, row)
                    continue
                if start <= month <= end:
                    totals[rule] += _to_float(row.get("visits"))
    return totals


def validation_outputs(output_folder: Path, job_name: str) -> list[Path]:
    """The ``VALIDATION_{job_name}*.csv`` files written by the validation transform."""
    return sorted(output_folder.glob(f"VALIDATION_{job_name}*.csv"))


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def _dimensions(record: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    conditions = (record or {}).get("conditions") or []
    for i in range(4):
        cond = conditions[i] if i < len(conditions) else {}
        out[f"Dimension{i + 1}"] = str(cond.get("dimension") or "")
        out[f"Dimension{i + 1}Item"] = str(cond.get("item") or "")
    return out


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def _records_row(m: _Matched, round_id: str) -> dict[str, str]:
    rec = m.record or {}
    window = rec.get("visits_window") or {}
    visits = rec.get("visits_last_12_months")
    return {
        "RuleID": _cell(rec.get("rule_id")),
        "RoundID": _cell(rec.get("round_id") or round_id),
        "CompareValidate": _cell(rec.get("compare_validate") or m.entry.kind),
        "SegmentId": m.entry.segment_id,
        "SegmentName": _cell(rec.get("segment_name")),
        "BotRuleName": m.entry.bot_rule_name,
        "BotRuleNumber": _cell(rec.get("bot_rule_number")),
        "RSIDCleanName": _cell(rec.get("rsid_clean_name")),
        **_dimensions(m.record),
        "Visits12m": _cell(visits),
        "VisitsFrom": _cell(window.get("from")),
        "VisitsTo": _cell(window.get("to")),
    }


def _write_records_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RECORDS_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _write_details_csv(
    folder: Path, m: _Matched, round_id: str, last_bot_rule_number: int | None
) -> Path:
    """Key/value rows for the Bot Rule Compare ``Segment Details Input`` tab."""
    rec = m.record or {}
    rows = [
        ("RuleID", _cell(rec.get("rule_id"))),
        ("RoundID", _cell(rec.get("round_id") or round_id)),
        ("SegmentId", m.entry.segment_id),
        ("SegmentName", _cell(rec.get("segment_name"))),
        ("RSIDCleanName", _cell(rec.get("rsid_clean_name"))),
        ("LastBotRuleNumber", _cell(last_bot_rule_number)),
        *_dimensions(m.record).items(),
    ]
    stem = Path(record_filename(rec.get("rule_id"), m.entry.bot_rule_name)).stem
    path = folder / f"{stem}_segment_details.csv"
    folder.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Key", "Value"])
        writer.writerows(rows)
    return path


# ---------------------------------------------------------------------------
# Tag check
# ---------------------------------------------------------------------------


async def _tagged_segments(client: Any, tag: str) -> list[dict[str, Any]]:
    from adobe_downloader.segments.bot_rule_numbers import list_tagged_segments

    return await list_tagged_segments(client, tag)


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def run_segment_records(
    *,
    client: Any,
    round_id: str,
    output_folder: Path,
    records_path: Path,
    validate_list: Path | None,
    compare_list: Path | None,
    date_to: date | None,
    visits_report: str = DEFAULT_VISITS_REPORT,
    candidate_tag: str = DEFAULT_CANDIDATE_TAG,
) -> SegmentRecordsResult:
    """Enrich the records of one round and write the Decision Log / compare CSVs.

    Args:
        client: ``AdobeClient`` for the tag check, or ``None`` to skip it.
        round_id: Round ID; also the run's ``job_name``, so it names the outputs.
        output_folder: The run's job folder (``{base}/{client}/{job_name}``).
        records_path: Folder holding the per-segment YAML records.
        validate_list / compare_list: The list CSVs the run used.
        date_to: End of the 12-month visits window (the run's ``date_range.to``).
            Required when there is a validate list.
        visits_report: Validation report whose ``visits`` are summed.
        candidate_tag: Tag every validate segment should carry.
    """
    result = SegmentRecordsResult()
    entries: list[ListEntry] = []
    if validate_list is not None:
        entries += read_list(validate_list, VALIDATE)
    if compare_list is not None:
        entries += read_list(compare_list, COMPARE)

    index = _index_records(records_path)
    matched = [_match(e, index) for e in entries]
    dirty: set[int] = set()

    # 1. Back-fill segment IDs.
    for i, m in enumerate(matched):
        if m.record is None:
            result.missing_records.append(f"{m.entry.kind}: {m.entry.bot_rule_name}")
            continue
        if m.entry.segment_id == PLACEHOLDER_SEGMENT_ID:
            if m.entry.kind == VALIDATE:
                result.still_placeholder.append(m.entry.bot_rule_name)
            continue
        old = m.record.get("segment_id")
        if old == m.entry.segment_id:
            continue
        if old not in (None, "", PLACEHOLDER_SEGMENT_ID):
            logger.warning(
                "%s: record segment_id %s differs from the list (%s); using the list's",
                m.entry.bot_rule_name,
                old,
                m.entry.segment_id,
            )
        else:
            result.backfilled.append(f"{m.entry.bot_rule_name}: {m.entry.segment_id}")
        m.record["segment_id"] = m.entry.segment_id
        dirty.add(i)

    # 2. Tag check on validate segments (never tags anything; see MDL plan D9).
    validate_ids = {
        m.entry.segment_id: m.entry.bot_rule_name
        for m in matched
        if m.entry.kind == VALIDATE and m.entry.segment_id not in ("", PLACEHOLDER_SEGMENT_ID)
    }
    last_bot_rule_number: int | None = None
    if client is not None and (validate_ids or compare_list is not None):
        from adobe_downloader.segments.bot_rule_numbers import highest_bot_rule_number

        try:
            tagged = await _tagged_segments(client, candidate_tag)
        except Exception as exc:
            result.tag_check_error = str(exc)
            logger.warning("Could not check %s tags: %s", candidate_tag, exc)
        else:
            tagged_ids = {str(s.get("id")) for s in tagged}
            result.untagged = [
                f"{name} ({seg_id})"
                for seg_id, name in validate_ids.items()
                if seg_id not in tagged_ids
            ]
            last_bot_rule_number = highest_bot_rule_number(str(s.get("name", "")) for s in tagged)
    if last_bot_rule_number is None:
        numbers = [
            int(m.record["bot_rule_number"])
            for m in matched
            if m.record is not None and m.record.get("bot_rule_number") is not None
        ]
        last_bot_rule_number = max(numbers, default=None)

    # 3. Visits for validate rules.
    if any(m.entry.kind == VALIDATE for m in matched):
        if date_to is None:
            raise ValueError("segment_records needs date_to (the run's date_range.to)")
        window = twelve_month_window(date_to)
        result.window = window
        totals = sum_visits(validation_outputs(output_folder, round_id), visits_report, window)
        for i, m in enumerate(matched):
            if m.entry.kind != VALIDATE or m.record is None:
                continue
            if m.entry.segment_id == PLACEHOLDER_SEGMENT_ID:
                continue
            key = sanitize_segment_name_for_filename(m.entry.bot_rule_name)
            if key not in totals:
                result.missing_visits.append(m.entry.bot_rule_name)
                continue
            m.record["visits_last_12_months"] = int(round(totals[key]))
            m.record["visits_window"] = {
                "from": window[0].isoformat(),
                "to": window[1].isoformat(),
            }
            dirty.add(i)

    for i in sorted(dirty):
        m = matched[i]
        assert m.path is not None and m.record is not None
        save_record(m.path, m.record)
    result.records_updated = len(dirty)

    # 4. Outputs.
    if matched:
        result.records_csv = output_folder / f"{round_id}_segment_records.csv"
        _write_records_csv(result.records_csv, [_records_row(m, round_id) for m in matched])
    for m in matched:
        if m.entry.kind == COMPARE:
            result.details_files.append(
                _write_details_csv(output_folder, m, round_id, last_bot_rule_number)
            )

    _log_result(result, candidate_tag, visits_report)
    return result


def _log_result(result: SegmentRecordsResult, candidate_tag: str, visits_report: str) -> None:
    logger.info("Segment records updated: %d", result.records_updated)
    if result.window:
        logger.info(
            "Visits window: %s to %s (%s)",
            result.window[0].isoformat(),
            result.window[1].isoformat(),
            visits_report,
        )
    for item in result.backfilled:
        logger.info("  Back-filled segment ID: %s", item)
    if result.records_csv:
        logger.info("Decision Log import -> %s", result.records_csv)
    for path in result.details_files:
        logger.info("Segment details -> %s", path)
    if result.untagged:
        logger.warning(
            "%d validate segment(s) are not tagged %s; tag them in Adobe so the next "
            "bot rule number lookup sees them:",
            len(result.untagged),
            candidate_tag,
        )
        for item in result.untagged:
            logger.warning("  %s", item)
    if result.still_placeholder:
        logger.warning(
            "%d validate row(s) still have %s in the list:",
            len(result.still_placeholder),
            PLACEHOLDER_SEGMENT_ID,
        )
        for item in result.still_placeholder:
            logger.warning("  %s", item)
    if result.missing_records:
        logger.warning("%d list row(s) have no segment record:", len(result.missing_records))
        for item in result.missing_records:
            logger.warning("  %s", item)
    if result.missing_visits:
        logger.warning(
            "%d validate rule(s) have no %s rows in the outputs; visits left empty:",
            len(result.missing_visits),
            visits_report,
        )
        for item in result.missing_visits:
            logger.warning("  %s", item)


def parse_date_to(value: str | None) -> date | None:
    """Parse a ``date_range.to`` value (``YYYY-MM-DD`` or ``today``)."""
    if value is None:
        return None
    if value == "today":
        return date.today()
    return date.fromisoformat(value)
