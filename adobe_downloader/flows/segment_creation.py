"""Create Adobe Analytics segments from a CSV list."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from adobe_downloader.config.schema import DEFAULT_CANDIDATE_TAG
from adobe_downloader.segments.rule_ids import (
    RULE_ID_RE,
    build_compare_bot_rule_name,
    build_compare_segment_name,
    build_validate_segment_name,
    parse_rule_id,
)
from adobe_downloader.segments.segment_records import PLACEHOLDER_SEGMENT_ID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSV row constants
# ---------------------------------------------------------------------------

COMPARE_VALIDATE_VALUES = frozenset(
    ["Compare", "Validate", "Compare - Special", "Validate - Special"]
)


@dataclass
class _CsvRow:
    compare_validate: str
    segment_name: str
    rsid_clean_name: str
    dimension1: str
    dimension1_item: str
    dimension2: str
    dimension2_item: str
    dimension3: str
    dimension3_item: str
    dimension4: str
    dimension4_item: str
    row_num: int
    # Optional Master Decision Log columns (MDL plan A4). Empty when absent.
    rule_id: str = ""
    round_id: str = ""
    parent_rule_id: str = ""
    super_investigation: str = ""
    next_step: str = ""
    prior_rules: list[str] = field(default_factory=list)
    has_prior_step: bool | None = None
    has_following_step: bool | None = None
    # Columns that held an Excel error value (#REF! etc.), reported by _validate_row.
    error_columns: list[str] = field(default_factory=list)

    def dimensions(self) -> list[tuple[str, str]]:
        """Return the (dimension, item) pairs set on this row, in tier order."""
        return [
            (dim, item)
            for dim, item in (
                (self.dimension1, self.dimension1_item),
                (self.dimension2, self.dimension2_item),
                (self.dimension3, self.dimension3_item),
                (self.dimension4, self.dimension4_item),
            )
            if dim
        ]


@dataclass
class SegmentCreationResult:
    segment_list_file: Path | None
    compare_list_file: Path | None
    validate_list_file: Path | None
    created_count: int = 0
    special_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    # Created validate segments that could not be tagged with the candidate tag.
    # The segment exists and is in the output lists; tag it by hand in Adobe.
    tag_failures: list[str] = field(default_factory=list)
    # Final names of Validate - Special rows, to be created by hand in Adobe.
    special_validate_names: list[str] = field(default_factory=list)
    # YAML records written to segment_records_path (one per successful row).
    record_files: list[Path] = field(default_factory=list)
    # Generated {RoundID}_run.yaml (MDL plan A6), when a run template was given.
    run_config_file: Path | None = None


# ---------------------------------------------------------------------------
# Bot rule numbering
# ---------------------------------------------------------------------------

VALIDATE_TYPES = frozenset(["Validate", "Validate - Special"])
_LEADING_NUMBER_RE = re.compile(r"^\d{4}(?!\d)")


def apply_bot_rule_number(segment_name: str, number: int) -> str:
    """Return *segment_name* with its leading 4-digit number set to *number*.

    A name that already starts with 4 digits has them replaced; any other name
    gets ``NNNN `` prepended.
    """
    formatted = f"{number:04d}"
    if _LEADING_NUMBER_RE.match(segment_name):
        return formatted + segment_name[4:]
    return f"{formatted} {segment_name}"


def renumber_validate_rows(rows: list[_CsvRow], start: int) -> int:
    """Number every Validate / Validate - Special row in list order from *start*.

    Mutates ``segment_name`` on those rows. Compare rows are left alone.
    Returns the number of rows renumbered.
    """
    number = start
    for row in rows:
        if row.compare_validate not in VALIDATE_TYPES:
            continue
        new_name = apply_bot_rule_number(row.segment_name, number)
        if new_name != row.segment_name:
            logger.debug("Row %d renamed: %r -> %r", row.row_num, row.segment_name, new_name)
        row.segment_name = new_name
        number += 1
    return number - start


async def _renumber_from_adobe(client: Any, rows: list[_CsvRow], candidate_tag: str) -> None:
    """Renumber validate rows from the highest tagged number in Adobe.

    On any failure the Excel numbers are kept and a warning is logged (backup path).
    """
    from adobe_downloader.segments.bot_rule_numbers import get_highest_bot_rule_candidate_number

    if not any(row.compare_validate in VALIDATE_TYPES for row in rows):
        return
    try:
        highest = await get_highest_bot_rule_candidate_number(client, candidate_tag)
    except Exception as exc:
        logger.warning(
            "Could not look up the highest %s number (%s); keeping the numbers from the input CSV",
            candidate_tag,
            exc,
        )
        return
    count = renumber_validate_rows(rows, highest + 1)
    logger.info(
        "Bot rule numbers: %04d-%04d (highest tagged %s was %04d)",
        highest + 1,
        highest + count,
        candidate_tag,
        highest,
    )


# ---------------------------------------------------------------------------
# Bot rule name transformation (ported from createSegmentFromList.js)
# ---------------------------------------------------------------------------

_ABBREVIATIONS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"OperatingSystems", re.IGNORECASE), "OS"),
    (re.compile(r"OperatingSystem", re.IGNORECASE), "OS"),
    (re.compile(r"Operating Systems", re.IGNORECASE), "OS"),
    (re.compile(r"Operating System", re.IGNORECASE), "OS"),
    (re.compile(r"MonitorResolution", re.IGNORECASE), "MonRes"),
    (re.compile(r"Monitor Resolution", re.IGNORECASE), "MonRes"),
    (re.compile(r"MarketingChannel", re.IGNORECASE), "MarCha"),
    (re.compile(r"Marketing Channel", re.IGNORECASE), "MarCha"),
    (re.compile(r"ReferringDomain", re.IGNORECASE), "RefDom"),
    (re.compile(r"Referring Domain", re.IGNORECASE), "RefDom"),
    (re.compile(r"MobileManufacturer", re.IGNORECASE), "MobMan"),
    (re.compile(r"Mobile Manufacturer", re.IGNORECASE), "MobMan"),
    (re.compile(r"BrowserType", re.IGNORECASE), "BrowType"),
    (re.compile(r"Browser Type", re.IGNORECASE), "BrowType"),
    (re.compile(r"UserAgent", re.IGNORECASE), "UsAg"),
    (re.compile(r"User Agent", re.IGNORECASE), "UsAg"),
    (re.compile(r"PageURL", re.IGNORECASE), "URL"),
    (re.compile(r"Page URL", re.IGNORECASE), "URL"),
    (re.compile(r"Regions", re.IGNORECASE), "Reg"),
    (re.compile(r"Region", re.IGNORECASE), "Reg"),
    (re.compile(r"Domain", re.IGNORECASE), "Dom"),
]


def _ensure_max_length(name: str) -> str:
    """Shorten *name* to <=95 chars using abbreviations, vowel removal, truncation."""
    if len(name) <= 95:
        return name

    result = name
    for pattern, repl in _ABBREVIATIONS:
        result = pattern.sub(repl, result)
    if len(result) <= 95:
        return result

    # Remove vowels from 4th segment (split by _ then -)
    for sep in ("_", "-"):
        parts = result.split(sep)
        if len(parts) >= 4:
            parts[3] = re.sub(r"[aeiouAEIOU]", "", parts[3])
            result = sep.join(parts)
            break

    if len(result) <= 95:
        return result
    return result[:95]


def transform_to_bot_rule_name(segment_name: str) -> str:
    """Transform *segment_name* to the Compare botRuleName format."""
    result = segment_name
    result = re.sub(r"UserAgent = .*?(?=\s+AND\s+|$)", "UserAgent", result, flags=re.IGNORECASE)
    result = re.sub(r"UserAgent=.*?(?=\s+AND\s+|$)", "UserAgent", result, flags=re.IGNORECASE)
    result = re.sub(r"[\s:./,\-]", "", result)
    return _ensure_max_length(result)


def transform_to_validate_bot_rule_name(segment_name: str) -> str:
    """Transform *segment_name* to the Validate botRuleName format."""
    result = segment_name
    result = result.replace(" ", "").replace(":", "").replace("-", "")
    result = re.sub(r"UserAgent = .*?(?=\s+AND\s+|$)", "UserAgent", result, flags=re.IGNORECASE)
    result = re.sub(r"UserAgent=.*?(?=\s+AND\s+|$)", "UserAgent", result, flags=re.IGNORECASE)
    result = result.replace("/", "").replace(",", "")
    result = re.sub(r"[^a-zA-Z0-9_]", "-", result)
    return _ensure_max_length(result)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


_EMPTY_CELL_VALUES = frozenset(["", "none"])
_EXCEL_ERROR_RE = re.compile(r"^#(REF!|N/A|VALUE!|NAME\?|DIV/0!|NUM!|NULL!|SPILL!|CALC!)$", re.I)

# Optional columns read by normalised header (case, spaces and underscores ignored),
# so both ``RuleID`` and the workbook's ``Rule ID`` are accepted.
_OPTIONAL_TEXT_COLUMNS = {
    "ruleid": "rule_id",
    "roundid": "round_id",
    "parentruleid": "parent_rule_id",
    "superinvestigation": "super_investigation",
    "nextstep": "next_step",
}
_PRIOR_RULE_COLUMNS = ("priorrule1", "priorrule2", "priorrule3")
_BOOL_COLUMNS = {"haspriorstep": "has_prior_step", "hasfollowingstep": "has_following_step"}


def _normalise_header(name: str) -> str:
    return re.sub(r"[\s_]", "", name).lower()


def _parse_bool(value: str) -> bool | None:
    v = value.strip().lower()
    if v in ("true", "yes", "1"):
        return True
    if v in ("false", "no", "0"):
        return False
    return None


def _read_csv(file_path: Path) -> list[_CsvRow]:
    rows: list[_CsvRow] = []
    with file_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, raw in enumerate(reader, start=1):
            row = {_normalise_header(k): (v or "").strip() for k, v in raw.items() if k}
            csv_row = _CsvRow(
                compare_validate=row.get("comparevalidate", ""),
                segment_name=row.get("segmentname", ""),
                rsid_clean_name=row.get("rsidcleanname", ""),
                dimension1=row.get("dimension1", ""),
                dimension1_item=row.get("dimension1item", ""),
                dimension2=row.get("dimension2", ""),
                dimension2_item=row.get("dimension2item", ""),
                dimension3=row.get("dimension3", ""),
                dimension3_item=row.get("dimension3item", ""),
                dimension4=row.get("dimension4", ""),
                dimension4_item=row.get("dimension4item", ""),
                row_num=i,
            )

            def optional(key: str) -> str:
                value = row.get(key, "")
                if _EXCEL_ERROR_RE.match(value):
                    csv_row.error_columns.append(key)
                    return ""
                return "" if value.lower() in _EMPTY_CELL_VALUES else value

            for key, attr in _OPTIONAL_TEXT_COLUMNS.items():
                setattr(csv_row, attr, optional(key))
            csv_row.prior_rules = [p for p in (optional(k) for k in _PRIOR_RULE_COLUMNS) if p]
            for key, attr in _BOOL_COLUMNS.items():
                setattr(csv_row, attr, _parse_bool(optional(key)))
            rows.append(csv_row)
    return rows


def _validate_rule_id(row: _CsvRow) -> list[str]:
    """Check the Rule ID grammar and that any supplied derived columns agree with it."""
    if not row.rule_id:
        return []
    try:
        parts = parse_rule_id(row.rule_id)
    except ValueError as exc:
        return [f"Row {row.row_num}: {exc}"]
    errors: list[str] = []
    for label, given, derived in (
        ("RoundID", row.round_id, parts.round_id),
        ("ParentRuleID", row.parent_rule_id, parts.parent_rule_id or ""),
        ("SuperInvestigation", row.super_investigation, parts.super_investigation),
    ):
        if given and given != derived:
            errors.append(
                f"Row {row.row_num}: {label} {given!r} does not match Rule ID "
                f"{row.rule_id!r} (expected {derived!r})"
            )
    for prior in row.prior_rules:
        if not RULE_ID_RE.match(prior):
            errors.append(f"Row {row.row_num}: Prior rule {prior!r} is not a valid Rule ID")
    return errors


def _validate_row(row: _CsvRow) -> list[str]:
    errors: list[str] = []
    for col in row.error_columns:
        errors.append(f"Row {row.row_num}: column {col!r} holds an Excel error value")
    errors.extend(_validate_rule_id(row))
    if not row.segment_name and not row.rule_id:
        errors.append(f"Row {row.row_num}: Missing SegmentName")
    if row.compare_validate not in COMPARE_VALIDATE_VALUES:
        errors.append(
            f"Row {row.row_num}: CompareValidate must be one of "
            f"{sorted(COMPARE_VALIDATE_VALUES)!r}, got {row.compare_validate!r}"
        )
    is_special = row.compare_validate in ("Compare - Special", "Validate - Special")
    # With a Rule ID the name is built from RSID + dimensions, so Specials need them too.
    if not is_special or row.rule_id:
        if not row.rsid_clean_name:
            errors.append(f"Row {row.row_num}: Missing RSIDCleanName")
        if not row.dimension1:
            errors.append(f"Row {row.row_num}: Missing Dimension1")
        if not row.dimension1_item:
            errors.append(f"Row {row.row_num}: Missing Dimension1Item")
        tiers = (
            (2, row.dimension2, row.dimension2_item, row.dimension1),
            (3, row.dimension3, row.dimension3_item, row.dimension2),
            (4, row.dimension4, row.dimension4_item, row.dimension3),
        )
        for n, dim, item, prior_dim in tiers:
            if dim and not item:
                errors.append(f"Row {row.row_num}: Dimension{n} set but Dimension{n}Item missing")
            if dim and not prior_dim:
                errors.append(f"Row {row.row_num}: Dimension{n} set but Dimension{n - 1} missing")
    return errors


def _write_csv(file_path: Path, rows: list[dict[str, str]]) -> None:
    """Write rows to CSV, with columns matching the first row's keys.

    Compare rows include reportToIgnore (bot_rule_compare uses it to skip the
    report a rule was built from); validate rows don't, since bot_validation
    never reads that column.
    """
    if not rows:
        return
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_segment_list(file_path: Path, segments: list[dict[str, str]]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Rule ID naming (MDL plan A4) and segment records (A5)
# ---------------------------------------------------------------------------


def apply_rule_id_names(rows: list[_CsvRow]) -> int:
    """Build the segment name of every row that has a Rule ID; returns how many.

    Validate names keep the number from the input ``SegmentName`` (if any) so the
    Excel number survives as the backup when renumbering is off or fails. Rows
    without a Rule ID keep their ``SegmentName`` unchanged.
    """
    count = 0
    for row in rows:
        if not row.rule_id:
            continue
        if row.compare_validate in VALIDATE_TYPES:
            m = _LEADING_NUMBER_RE.match(row.segment_name)
            number = int(m.group()) if m else None
            name = build_validate_segment_name(row.rsid_clean_name, row.dimensions(), number)
        else:
            name = build_compare_segment_name(row.rule_id, row.rsid_clean_name, row.dimensions())
        if row.segment_name and name != row.segment_name:
            logger.debug(
                "Row %d name built from Rule ID: %r -> %r", row.row_num, row.segment_name, name
            )
        row.segment_name = name
        count += 1
    return count


def bot_rule_name_for(row: _CsvRow) -> str:
    """``botRuleName`` for *row*: Rule ID compares keep the Rule ID verbatim."""
    if row.compare_validate in VALIDATE_TYPES:
        return transform_to_validate_bot_rule_name(row.segment_name)
    if row.rule_id:
        return build_compare_bot_rule_name(row.rule_id, row.rsid_clean_name, row.dimensions())
    return transform_to_bot_rule_name(row.segment_name)


def _record_conditions(
    row: _CsvRow, resolved: list[tuple[str, str, bool]] | None, lookup_base: Path
) -> list[dict[str, Any]]:
    from adobe_downloader.segments.create_segment import get_dimension_id, resolve_dimension_value

    conditions: list[dict[str, Any]] = []
    for i, (dim, item) in enumerate(row.dimensions()):
        value: str | None
        if resolved is not None:
            value = resolved[i][1]
        else:
            try:
                value = resolve_dimension_value(dim, item, lookup_base)[0]
            except Exception:
                value = None
        conditions.append(
            {
                "dimension": dim,
                "adobe_variable": get_dimension_id(dim),
                "item": item,
                "resolved_value": value,
                "operator": "equals",
            }
        )
    return conditions


def _build_row_record(
    row: _CsvRow,
    *,
    bot_rule_name: str,
    segment_id: str | None,
    rsid: str | None,
    resolved: list[tuple[str, str, bool]] | None,
    lookup_base: Path,
    job_name: str,
) -> dict[str, Any]:
    from adobe_downloader.segments.segment_records import build_record

    parts = parse_rule_id(row.rule_id) if row.rule_id else None
    number: int | None = None
    if row.compare_validate in VALIDATE_TYPES:
        m = _LEADING_NUMBER_RE.match(row.segment_name)
        number = int(m.group()) if m else None
    return build_record(
        rule_id=row.rule_id or None,
        round_id=row.round_id or (parts.round_id if parts else None),
        super_investigation=row.super_investigation
        or (parts.super_investigation if parts else None),
        parent_rule_id=row.parent_rule_id or (parts.parent_rule_id if parts else None),
        compare_validate=row.compare_validate,
        next_step=row.next_step or None,
        segment_name=row.segment_name,
        bot_rule_name=bot_rule_name,
        bot_rule_number=number,
        segment_id=segment_id,
        rsid=rsid,
        rsid_clean_name=row.rsid_clean_name,
        conditions=_record_conditions(row, resolved, lookup_base),
        prior_rules=row.prior_rules,
        has_prior_step=row.has_prior_step,
        has_following_step=row.has_following_step,
        created_by_job=job_name,
    )


def _write_row_record(records_path: Path | None, record: dict[str, Any]) -> Path | None:
    """Write one record; a failure is logged, never fatal (the segment already exists)."""
    if records_path is None:
        return None
    from adobe_downloader.segments.segment_records import write_record

    try:
        return write_record(records_path, record)
    except Exception as exc:
        logger.warning("Could not write segment record for %s: %s", record["segment_name"], exc)
        return None


def round_id_for(rows: list[_CsvRow], list_name: str) -> str:
    """The single Round ID of *rows*, or *list_name* when no row has a Rule ID.

    Raises ``ValueError`` when the rows span more than one round: a run config (and
    its output folder) covers exactly one round.
    """
    round_ids = sorted(
        {row.round_id or parse_rule_id(row.rule_id).round_id for row in rows if row.rule_id}
    )
    if len(round_ids) > 1:
        raise ValueError(
            "A run config covers one round, but this list has rows from "
            f"{len(round_ids)}: {', '.join(round_ids)}. Split the list by round, or "
            "remove run_template from the config."
        )
    return round_ids[0] if round_ids else list_name


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


async def run_segment_creation(
    client: Any,
    input_csv: Path,
    share_with_users: list[str],
    compare_list_path: Path | None,
    validate_list_path: Path | None,
    segment_list_path: Path | None,
    lookup_base: Path,
    rsid_lookup_file: Path,
    test_mode_row: int | None = None,
    renumber_validates: bool = True,
    candidate_tag: str = DEFAULT_CANDIDATE_TAG,
    segment_records_path: Path | None = None,
    run_template: Path | None = None,
    run_config_path: Path | None = None,
    client_name: str = "",
) -> SegmentCreationResult:
    """Create segments from *input_csv* and write the 3 output files.

    Args:
        client: ``AdobeClient`` instance.
        input_csv: Path to the input CSV file.
        share_with_users: Adobe user IDs to share each created segment with.
        compare_list_path: Folder for the compare CSV output (or ``None`` to skip).
        validate_list_path: Folder for the validate CSV output (or ``None`` to skip).
        segment_list_path: Folder for the segment list JSON (or ``None`` to skip).
        lookup_base: Base directory containing ``{dim}/lookup.txt`` files.
        rsid_lookup_file: Path to the ``rsid:CleanName`` lookup file.
        test_mode_row: If set, only process this 1-indexed row (no API calls made).
        renumber_validates: Replace the leading bot rule number on every Validate and
            Validate - Special row with the next free number from Adobe (highest
            number among segments tagged *candidate_tag*, plus one).
        candidate_tag: Tag added to every created Validate segment, and used to
            find the highest existing bot rule number.
        segment_records_path: Folder for the per-segment YAML records (or ``None``
            to skip). Rows with a ``RuleID`` are written as ``{RuleID}.yaml``.
        run_template: Run template YAML. When set, ``{RoundID}_run.yaml`` is written
            to *run_config_path* after the lists (MDL plan A6). Not in test mode.
        run_config_path: Folder for the generated run config (default
            ``jobs/generated``).
        client_name: Client written into the generated run config.

    Returns:
        :class:`SegmentCreationResult` with output paths and counters.
    """
    from adobe_downloader.segments.create_segment import (
        build_condition_segment,
        resolve_dimension_value,
    )
    from adobe_downloader.utils.rsid_lookup import lookup_rsid

    rows = _read_csv(input_csv)

    # Validate all rows before touching the API
    all_errors: list[str] = []
    for row in rows:
        all_errors.extend(_validate_row(row))
    if all_errors:
        raise ValueError("CSV validation errors:\n" + "\n".join(all_errors))

    list_name = input_csv.stem

    # Check the run template and round before any segment is created.
    template = None
    round_id = list_name
    if run_template is not None and test_mode_row is None:
        from adobe_downloader.segments.run_config import load_run_template

        round_id = round_id_for(rows, list_name)
        template = load_run_template(run_template)
        if not client_name:
            raise ValueError("client_name is required to write a run config")

    built = apply_rule_id_names(rows)
    if built:
        logger.info("Built %d segment name(s) from Rule IDs", built)

    if test_mode_row is not None:
        if test_mode_row < 1 or test_mode_row > len(rows):
            raise ValueError(f"test_mode_row {test_mode_row} out of range (1-{len(rows)})")
        row = rows[test_mode_row - 1]
        logger.info("Test mode: row %d — %s", test_mode_row, row.segment_name)
        test_rsid = _log_row_resolved(row, lookup_base, rsid_lookup_file)
        test_result = SegmentCreationResult(
            segment_list_file=None,
            compare_list_file=None,
            validate_list_file=None,
        )
        test_record = _write_row_record(
            segment_records_path,
            _build_row_record(
                row,
                bot_rule_name=bot_rule_name_for(row),
                segment_id=None,
                rsid=test_rsid,
                resolved=None,
                lookup_base=lookup_base,
                job_name=list_name,
            ),
        )
        if test_record is not None:
            test_result.record_files.append(test_record)
        return test_result

    if renumber_validates:
        await _renumber_from_adobe(client, rows, candidate_tag)

    compare_rows: list[dict[str, str]] = []
    validate_rows: list[dict[str, str]] = []
    all_segments: list[dict[str, str]] = []
    result = SegmentCreationResult(
        segment_list_file=None,
        compare_list_file=None,
        validate_list_file=None,
    )

    for row in rows:
        logger.info("Processing row %d/%d: %s", row.row_num, len(rows), row.segment_name)
        is_special = row.compare_validate in ("Compare - Special", "Validate - Special")
        is_compare = row.compare_validate in ("Compare", "Compare - Special")
        rsid: str | None = None
        conditions: list[tuple[str, str, bool]] | None = None

        try:
            if is_special:
                seg_id = PLACEHOLDER_SEGMENT_ID
                bot_rule_name = bot_rule_name_for(row)
                report_to_ignore = "|".join(dim for dim, _ in row.dimensions())
                if row.rsid_clean_name:
                    rsid = lookup_rsid(row.rsid_clean_name.replace(".", ""), rsid_lookup_file)
            else:
                # Resolve RSID
                clean_rsid_name = row.rsid_clean_name.replace(".", "")
                rsid = lookup_rsid(clean_rsid_name, rsid_lookup_file)
                if rsid is None:
                    raise ValueError(f"RSID not found for clean name: {row.rsid_clean_name!r}")

                # Resolve dimension values
                conditions = [
                    (dim, *resolve_dimension_value(dim, item, lookup_base))
                    for dim, item in row.dimensions()
                ]
                seg_def = build_condition_segment(
                    row.segment_name, rsid, conditions, description=row.rule_id
                )

                # Create via API
                api_result = await client.create_segment(seg_def)
                seg_id = api_result["id"]
                logger.info("  Created: %s", seg_id)

                # Share
                if share_with_users:
                    await client.share_segment(seg_id, share_with_users)

                # Tag validates so the next run's number lookup sees them. A failure
                # here must not drop the (already created) segment from the lists.
                if not is_compare and candidate_tag:
                    try:
                        await client.tag_segment(seg_id, [candidate_tag])
                        logger.info("  Tagged: %s", candidate_tag)
                    except Exception as exc:
                        msg = f"Row {row.row_num} ({row.segment_name}, {seg_id}): {exc}"
                        logger.warning("  Could not tag %s: %s", candidate_tag, msg)
                        result.tag_failures.append(msg)

                bot_rule_name = bot_rule_name_for(row)
                report_to_ignore = "|".join(dim for dim, _ in row.dimensions())
                all_segments.append({"id": seg_id, "name": row.segment_name})
                result.created_count += 1

            if is_special:
                result.special_count += 1
                if not is_compare:
                    result.special_validate_names.append(row.segment_name)

            if is_compare:
                compare_rows.append(
                    {
                        "DimSegmentId": seg_id,
                        "botRuleName": bot_rule_name,
                        "reportToIgnore": report_to_ignore,
                    }
                )
            else:
                validate_rows.append({"DimSegmentId": seg_id, "botRuleName": bot_rule_name})

            record_file = _write_row_record(
                segment_records_path,
                _build_row_record(
                    row,
                    bot_rule_name=bot_rule_name,
                    segment_id=seg_id,
                    rsid=rsid,
                    resolved=conditions,
                    lookup_base=lookup_base,
                    job_name=list_name,
                ),
            )
            if record_file is not None:
                result.record_files.append(record_file)

        except Exception as exc:
            msg = f"Row {row.row_num} ({row.segment_name}): {exc}"
            logger.error("  FAIL %s", msg)
            result.error_count += 1
            result.errors.append(msg)

    # Write output files
    if compare_rows and compare_list_path is not None:
        out = compare_list_path / f"{list_name}_compare.csv"
        _write_csv(out, compare_rows)
        result.compare_list_file = out
        logger.info("Compare CSV -> %s (%d rows)", out, len(compare_rows))

    if validate_rows and validate_list_path is not None:
        out = validate_list_path / f"{list_name}_validate.csv"
        _write_csv(out, validate_rows)
        result.validate_list_file = out
        logger.info("Validate CSV -> %s (%d rows)", out, len(validate_rows))

    if all_segments and segment_list_path is not None:
        out = segment_list_path / f"{list_name}.json"
        _write_segment_list(out, all_segments)
        result.segment_list_file = out
        logger.info("Segment list JSON -> %s (%d segments)", out, len(all_segments))

    if result.special_validate_names:
        logger.info(
            "Create these Validate - Special segments in Adobe under exactly these names, "
            "tag each %s, then replace %s in the validate CSV:",
            candidate_tag,
            PLACEHOLDER_SEGMENT_ID,
        )
        for name in result.special_validate_names:
            logger.info("  %s", name)

    if result.record_files and segment_records_path is not None:
        logger.info(
            "Segment records -> %s (%d file(s))", segment_records_path, len(result.record_files)
        )

    if template is not None and (result.compare_list_file or result.validate_list_file):
        from adobe_downloader.segments.run_config import (
            DEFAULT_RUN_CONFIG_DIR,
            build_run_config,
            write_run_config,
        )
        from adobe_downloader.segments.segment_records import default_records_path

        try:
            run_config = build_run_config(
                client=client_name,
                round_id=round_id,
                template=template,
                validate_list=result.validate_list_file,
                compare_list=result.compare_list_file,
                records_path=segment_records_path or default_records_path(client_name),
                candidate_tag=candidate_tag,
            )
            result.run_config_file = write_run_config(
                run_config_path or DEFAULT_RUN_CONFIG_DIR, round_id, run_config
            )
            logger.info("Run config -> %s", result.run_config_file)
        except Exception as exc:
            # The segments exist already; a missing run config must not hide that.
            msg = f"Could not write the run config: {exc}"
            logger.error(msg)
            result.error_count += 1
            result.errors.append(msg)

    if result.tag_failures:
        logger.warning(
            "%d created segment(s) could not be tagged %s; tag them in Adobe:",
            len(result.tag_failures),
            candidate_tag,
        )
        for msg in result.tag_failures:
            logger.warning("  %s", msg)

    return result


def _log_row_resolved(row: _CsvRow, lookup_base: Path, rsid_lookup_file: Path) -> str | None:
    """Log the resolved values for a single test-mode row (no API call); returns the RSID."""
    from adobe_downloader.segments.create_segment import resolve_dimension_value
    from adobe_downloader.utils.rsid_lookup import lookup_rsid

    clean_rsid_name = row.rsid_clean_name.replace(".", "")
    rsid = lookup_rsid(clean_rsid_name, rsid_lookup_file)
    logger.info("  RSID: %s", rsid)

    for i, (dim, item) in enumerate(row.dimensions(), start=1):
        val, is_num = resolve_dimension_value(dim, item, lookup_base)
        logger.info("  Dim%d: %s = %r (numeric=%s)", i, dim, val, is_num)
    logger.info("  Segment name: %s", row.segment_name)
    logger.info("  botRuleName : %s", bot_rule_name_for(row))
    return rsid
