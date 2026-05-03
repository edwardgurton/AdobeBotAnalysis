"""Create Adobe Analytics segments from a CSV list."""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    row_num: int


@dataclass
class SegmentCreationResult:
    segment_list_file: Path | None
    compare_list_file: Path | None
    validate_list_file: Path | None
    created_count: int = 0
    special_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)


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


def _read_csv(file_path: Path) -> list[_CsvRow]:
    rows: list[_CsvRow] = []
    with file_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader, start=1):
            rows.append(
                _CsvRow(
                    compare_validate=row.get("CompareValidate", "").strip(),
                    segment_name=row.get("SegmentName", "").strip(),
                    rsid_clean_name=row.get("RSIDCleanName", "").strip(),
                    dimension1=row.get("Dimension1", "").strip(),
                    dimension1_item=row.get("Dimension1Item", "").strip(),
                    dimension2=row.get("Dimension2", "").strip(),
                    dimension2_item=row.get("Dimension2Item", "").strip(),
                    row_num=i,
                )
            )
    return rows


def _validate_row(row: _CsvRow) -> list[str]:
    errors: list[str] = []
    if not row.segment_name:
        errors.append(f"Row {row.row_num}: Missing SegmentName")
    if row.compare_validate not in COMPARE_VALIDATE_VALUES:
        errors.append(
            f"Row {row.row_num}: CompareValidate must be one of "
            f"{sorted(COMPARE_VALIDATE_VALUES)!r}, got {row.compare_validate!r}"
        )
    is_special = row.compare_validate in ("Compare - Special", "Validate - Special")
    if not is_special:
        if not row.rsid_clean_name:
            errors.append(f"Row {row.row_num}: Missing RSIDCleanName")
        if not row.dimension1:
            errors.append(f"Row {row.row_num}: Missing Dimension1")
        if not row.dimension1_item:
            errors.append(f"Row {row.row_num}: Missing Dimension1Item")
        if row.dimension2 and not row.dimension2_item:
            errors.append(f"Row {row.row_num}: Dimension2 set but Dimension2Item missing")
    return errors


def _write_csv(file_path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["DimSegmentId", "botRuleName", "reportToIgnore"])
        writer.writeheader()
        writer.writerows(rows)


def _write_segment_list(file_path: Path, segments: list[dict[str, str]]) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")


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

    Returns:
        :class:`SegmentCreationResult` with output paths and counters.
    """
    from adobe_downloader.segments.create_segment import (
        build_dual_condition_segment,
        build_single_condition_segment,
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

    if test_mode_row is not None:
        if test_mode_row < 1 or test_mode_row > len(rows):
            raise ValueError(
                f"test_mode_row {test_mode_row} out of range (1-{len(rows)})"
            )
        row = rows[test_mode_row - 1]
        logger.info("Test mode: row %d — %s", test_mode_row, row.segment_name)
        _log_row_resolved(row, lookup_base, rsid_lookup_file)
        return SegmentCreationResult(
            segment_list_file=None,
            compare_list_file=None,
            validate_list_file=None,
        )

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

        bot_rule_fn = transform_to_bot_rule_name if is_compare else transform_to_validate_bot_rule_name

        try:
            if is_special:
                seg_id = "UPDATE-SEGMENT-ID"
                bot_rule_name = bot_rule_fn(row.segment_name)
                report_to_ignore = row.dimension1
            else:
                # Resolve RSID
                clean_rsid_name = row.rsid_clean_name.replace(".", "")
                rsid = lookup_rsid(clean_rsid_name, rsid_lookup_file)
                if rsid is None:
                    raise ValueError(f"RSID not found for clean name: {row.rsid_clean_name!r}")

                # Resolve dimension values
                val1, is_num1 = resolve_dimension_value(row.dimension1, row.dimension1_item, lookup_base)

                seg_def: dict
                if row.dimension2:
                    val2, is_num2 = resolve_dimension_value(row.dimension2, row.dimension2_item, lookup_base)
                    seg_def = build_dual_condition_segment(
                        row.segment_name, rsid,
                        row.dimension1, val1, is_num1,
                        row.dimension2, val2, is_num2,
                    )
                else:
                    seg_def = build_single_condition_segment(
                        row.segment_name, rsid, row.dimension1, val1, is_num1
                    )

                # Create via API
                api_result = await client.create_segment(seg_def)
                seg_id = api_result["id"]
                logger.info("  Created: %s", seg_id)

                # Share
                if share_with_users:
                    await client.share_segment(seg_id, share_with_users)

                bot_rule_name = bot_rule_fn(row.segment_name)
                report_to_ignore = row.dimension1
                all_segments.append({"id": seg_id, "name": row.segment_name})
                result.created_count += 1

            if is_special:
                result.special_count += 1

            out_row = {
                "DimSegmentId": seg_id,
                "botRuleName": bot_rule_name,
                "reportToIgnore": report_to_ignore,
            }
            if is_compare:
                compare_rows.append(out_row)
            else:
                validate_rows.append(out_row)

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

    return result


def _log_row_resolved(row: _CsvRow, lookup_base: Path, rsid_lookup_file: Path) -> None:
    """Log the resolved values for a single test-mode row (no API call)."""
    from adobe_downloader.segments.create_segment import resolve_dimension_value
    from adobe_downloader.utils.rsid_lookup import lookup_rsid

    clean_rsid_name = row.rsid_clean_name.replace(".", "")
    rsid = lookup_rsid(clean_rsid_name, rsid_lookup_file)
    logger.info("  RSID: %s", rsid)

    val1, is_num1 = resolve_dimension_value(row.dimension1, row.dimension1_item, lookup_base)
    logger.info("  Dim1: %s = %r (numeric=%s)", row.dimension1, val1, is_num1)

    if row.dimension2:
        val2, is_num2 = resolve_dimension_value(row.dimension2, row.dimension2_item, lookup_base)
        logger.info("  Dim2: %s = %r (numeric=%s)", row.dimension2, val2, is_num2)
