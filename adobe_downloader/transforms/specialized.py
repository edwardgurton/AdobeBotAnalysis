"""Specialised JSON → CSV transforms for Adobe Analytics report variants."""

import csv
import io
import json
import logging
from pathlib import Path

from adobe_downloader.transforms.base import (
    _DEFAULT_HEADERS_DIR,
    _parse_filename_parts,
    load_column_headers,
    transform_report,
)

_log = logging.getLogger(__name__)

_BOT_RULE_COMPARE_HEADERS = (
    "id,Feature,unique_visitors,visits,Raw_Clickouts,Engaged_Visits,"
    "First_Time_Visits,Total_Seconds_Spent,Page_Views,fileName,clientName,"
    "reportType,dimension,rsidName,botRuleName,compareVersion,trafficType,"
    "isCompare,isSegment,segmentId,segmentHash,startDate,endDate"
)


def _write_rows(columns: list[str], rows: list[list], output_path: Path | None) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    text = buf.getvalue()
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        _log.info("Saved CSV -> %s", output_path)
    return text


def _validate_rows(rows: list[list], n_cols: int, label: str, filename: str) -> None:
    for i, row in enumerate(rows):
        if len(row) != n_cols:
            raise ValueError(
                f"Row {i} has {len(row)} values but header has {n_cols} columns "
                f"({label}, file={filename})"
            )


def transform_bot_investigation(
    json_path: Path,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Bot investigation transform — identical logic to base transform."""
    return transform_report(json_path, headers_dir, output_path=output_path)


def transform_bot_validation(
    json_path: Path,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Bot validation transform.

    Appends requestName (parts[1]), botRuleName (parts[2]), rsidName (parts[3]).
    Filename pattern: {client}_{requestName}_{botRuleName}_{rsidName}_{from}_{to}
    """
    stem = json_path.stem
    parts = stem.split("_")
    request_name = parts[1]
    bot_rule_name = parts[2]
    rsid_name = parts[3]
    file_name_col = stem

    columns = load_column_headers(request_name, headers_dir)
    raw = json.loads(json_path.read_text(encoding="utf-8"))

    rows: list[list] = []
    for row in raw.get("rows", []):
        item_id = row.get("itemId", "")
        value = row.get("value", "")
        data = row.get("data", [])
        rows.append([item_id, value, *data, file_name_col, request_name, bot_rule_name, rsid_name])

    _validate_rows(rows, len(columns), f"request_name={request_name!r}", json_path.name)
    return _write_rows(columns, rows, output_path)


def transform_final_bot_rule_metrics(
    json_path: Path,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Final bot rule metrics transform.

    Appends fileName, botRuleName (parts[4]), rsidName (parts[3]), fromDate, toDate.
    Filename pattern:
      {client}_{reportName}_{fileExtra}_{rsidName}_{botRuleName}_{from}_{to}
    """
    stem = json_path.stem
    parts = stem.split("_")
    _, report_name, from_date, to_date = _parse_filename_parts(stem)
    rsid_name = parts[3]
    bot_rule_name = parts[4]
    file_name_col = stem

    columns = load_column_headers(report_name, headers_dir)
    raw = json.loads(json_path.read_text(encoding="utf-8"))

    rows: list[list] = []
    for row in raw.get("rows", []):
        item_id = row.get("itemId", "")
        value = row.get("value", "")
        data = row.get("data", [])
        rows.append([item_id, value, *data, file_name_col, bot_rule_name, rsid_name, from_date, to_date])

    _validate_rows(rows, len(columns), f"report_name={report_name!r}", json_path.name)
    return _write_rows(columns, rows, output_path)


def transform_bot_rule_compare(
    json_path: Path,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Bot rule compare transform — hardcoded headers + complex filename parsing.

    Filename patterns:
      AllTraffic: {client}_{reportType}_{rsid}_{round}_{ruleName}-Compare-{ver}-AllTraffic_{from}_{to}
      Segment: same but TrafficType=Segment, then DIMSEG{n}_{hash}_{from}_{to}
    """
    stem = json_path.stem
    parts = stem.split("_")

    client_name = parts[0]
    report_type = parts[1]
    dimension = report_type.replace("botInvestigationMetricsBy", "")
    rsid_bot_compare = parts[2]
    # parts[3] = roundString, parts[4] = {ruleName}-Compare-{version}-{trafficType}
    complex_part = parts[4]

    rsid_name = rsid_bot_compare.split("-")[0]
    complex_parts = complex_part.split("-")
    bot_rule_name = complex_parts[0]
    compare_version = complex_parts[2] if len(complex_parts) > 2 else ""
    traffic_type = complex_parts[3] if len(complex_parts) > 3 else ""

    is_segment = traffic_type == "Segment"
    is_compare = traffic_type in ("AllTraffic", "Compare")

    segment_id = ""
    segment_hash = ""
    start_date = ""
    end_date = ""

    if is_segment and len(parts) > 5 and parts[5].startswith("DIMSEG"):
        segment_id = parts[5]
        if len(parts) > 6 and len(parts[6]) == 24:
            segment_hash = parts[6]
            start_date = parts[7] if len(parts) > 7 else ""
            end_date = parts[8] if len(parts) > 8 else ""
        else:
            start_date = parts[6] if len(parts) > 6 else ""
            end_date = parts[7] if len(parts) > 7 else ""
    else:
        start_date = parts[5] if len(parts) > 5 else ""
        end_date = parts[6] if len(parts) > 6 else ""

    headers = _BOT_RULE_COMPARE_HEADERS.split(",")
    file_name_col = stem

    raw = json.loads(json_path.read_text(encoding="utf-8"))

    rows: list[list] = []
    for row in raw.get("rows", []):
        item_id = row.get("itemId", "")
        value = row.get("value", "")
        data = row.get("data", [])
        rows.append([
            item_id, value, *data,
            file_name_col, client_name, report_type, dimension,
            rsid_name, bot_rule_name, compare_version, traffic_type,
            str(is_compare).lower(), str(is_segment).lower(),
            segment_id, segment_hash, start_date, end_date,
        ])

    _validate_rows(rows, len(headers), f"report_type={report_type!r}", json_path.name)
    return _write_rows(headers, rows, output_path)


def transform_summary_total_only(
    json_path: Path,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Summary/totals-only transform — delegates to base transform_report."""
    return transform_report(json_path, headers_dir, output_path=output_path)


_TRANSFORM_REGISTRY: dict[str, object] = {
    "bot_investigation": transform_bot_investigation,
    "bot_validation": transform_bot_validation,
    "bot_rule_compare": transform_bot_rule_compare,
    "final_bot_rule_metrics": transform_final_bot_rule_metrics,
    "summary_total_only": transform_summary_total_only,
}


def _detect_transform_type(json_path: Path) -> str:
    """Infer transform type from JSON filename stem."""
    stem = json_path.stem
    parts = stem.split("_")
    report_part = parts[1] if len(parts) > 1 else ""

    if len(parts) > 4 and "-Compare-" in parts[4]:
        return "bot_rule_compare"
    if report_part.startswith("LegendFinalBotMetrics"):
        return "final_bot_rule_metrics"
    if report_part.startswith("botFilter"):
        return "bot_validation"
    if report_part.startswith("botInvestigation"):
        return "bot_investigation"
    return "summary_total_only"


def transform_report_dispatch(
    json_path: Path,
    transform_type: str | None = None,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Dispatch to the appropriate transform function.

    If transform_type is None, infer from the filename.
    """
    if transform_type is None:
        transform_type = _detect_transform_type(json_path)
    fn = _TRANSFORM_REGISTRY.get(transform_type)
    if fn is None:
        raise ValueError(f"Unknown transform_type: {transform_type!r}")
    return fn(json_path, headers_dir, output_path=output_path)  # type: ignore[operator]
