"""Base JSON → CSV transform for Adobe Analytics ranked and summary reports."""

import csv
import io
import json
import logging
from pathlib import Path

import yaml

_log = logging.getLogger(__name__)

_DEFAULT_HEADERS_DIR = Path(__file__).parent.parent.parent / "data" / "report_headers"


def load_column_headers(report_name: str, headers_dir: Path = _DEFAULT_HEADERS_DIR) -> list[str]:
    """Return the ordered list of CSV column names for report_name."""
    path = headers_dir / f"{report_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No header definition found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return list(data["columns"])


def _parse_filename_parts(stem: str) -> tuple[str, str, str, str]:
    """Extract (client_name, report_name, from_date, to_date) from a JSON filename stem.

    Expected pattern: {client}_{reportName}{_extra?}_{fromDate}_{toDate}
    The last two parts are always fromDate and toDate.  report_name is the longest
    prefix of the middle parts (starting at index 1) that has a known header YAML.
    Falls back to consuming all middle parts if no YAML is found.
    """
    parts = stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"Cannot parse filename stem: {stem!r} (expected at least 4 parts)")
    client_name = parts[0]
    to_date = parts[-1]
    from_date = parts[-2]
    middle = parts[1:-2]  # everything between client and the two date parts

    # Try longest-first match against known header YAMLs
    for length in range(len(middle), 0, -1):
        candidate = "_".join(middle[:length])
        if (_DEFAULT_HEADERS_DIR / f"{candidate}.yaml").exists():
            return client_name, candidate, from_date, to_date

    # Fallback: use the full middle section
    return client_name, "_".join(middle), from_date, to_date


def transform_report(
    json_path: Path,
    headers_dir: Path = _DEFAULT_HEADERS_DIR,
    *,
    output_path: Path | None = None,
) -> str:
    """Transform one Adobe Analytics JSON file into CSV text.

    The report_name is derived from the filename.  Columns are loaded from
    data/report_headers/{report_name}.yaml (or headers_dir override).

    Two JSON shapes are supported:
    - Dimensional (has ``rows``): itemId, value, data[0..n], fileName, fromDate, toDate
    - Summary/totals (has ``summaryData.totals``): data[0..n], fileName, fromDate, toDate

    If output_path is provided the CSV is written there; the CSV text is always returned.
    """
    from adobe_downloader.utils.winpath import to_long_path

    stem = json_path.stem
    _, report_name, from_date, to_date = _parse_filename_parts(stem)
    file_name_col = stem

    columns = load_column_headers(report_name, headers_dir)

    raw = json.loads(to_long_path(json_path).read_text(encoding="utf-8"))

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(columns)

    rows: list[list[str | int | float]] = []

    if "rows" in raw:
        # Detect unauthorized/errored metric columns and record their positions so
        # we can pad None into the data array at those slots.
        columns_meta = raw.get("columns", {})
        error_col_ids: set[str] = {e["columnId"] for e in columns_meta.get("columnErrors", [])}
        if error_col_ids:
            successful_ids: list[str] = columns_meta.get("columnIds", [])
            all_col_ids = sorted(successful_ids + list(error_col_ids), key=lambda x: int(x))
            _log.warning(
                "Column error(s) in %s — padding with empty values for columns: %s",
                json_path.name,
                sorted(error_col_ids, key=int),
            )
        else:
            all_col_ids = []

        for row in raw["rows"]:
            item_id = row.get("itemId", "")
            value = row.get("value", "")
            data: list[str | int | float | None] = list(row.get("data", []))
            if error_col_ids:
                expanded: list[str | int | float | None] = []
                data_iter = iter(data)
                for col_id in all_col_ids:
                    if col_id in error_col_ids:
                        expanded.append(None)
                    else:
                        expanded.append(next(data_iter, None))
                data = expanded
            rows.append([item_id, value, *data, file_name_col, from_date, to_date])
    elif "summaryData" in raw:
        totals = raw["summaryData"].get("totals", [])
        rows.append([*totals, file_name_col, from_date, to_date])
    else:
        _log.warning("No rows or summaryData found in %s", json_path.name)

    _expected = len(columns)
    for i, row in enumerate(rows):
        if len(row) != _expected:
            raise ValueError(
                f"Row {i} has {len(row)} values but header has {_expected} columns "
                f"(report_name={report_name!r}, file={json_path.name})"
            )
        writer.writerow(row)

    csv_text = buf.getvalue()

    if output_path is not None:
        long_output_path = to_long_path(output_path)
        long_output_path.parent.mkdir(parents=True, exist_ok=True)
        long_output_path.write_text(csv_text, encoding="utf-8")
        _log.info("Saved CSV -> %s", output_path)

    return csv_text


def make_csv_output_path(json_path: Path) -> Path:
    """Derive the canonical CSV output path from a JSON output path.

    Changes: .../JSON/...name.json  →  .../CSV/...name.csv
    """
    parts = json_path.parts
    json_idx = next((i for i, p in enumerate(parts) if p == "JSON"), None)
    if json_idx is None:
        return json_path.with_suffix(".csv")
    new_parts = list(parts)
    new_parts[json_idx] = "CSV"
    return Path(*new_parts).with_suffix(".csv")
