"""Tests for adobe_downloader/transforms/base.py and transforms/concatenate.py."""

import json
from pathlib import Path

import pytest

from adobe_downloader.transforms.base import (
    load_column_headers,
    make_csv_output_path,
    transform_report,
    _parse_filename_parts,
)
from adobe_downloader.transforms.concatenate import concatenate_csvs

_FIXTURES = Path(__file__).parent / "fixtures" / "transforms"
_HEADERS_DIR = Path(__file__).parent.parent / "data" / "report_headers"


# ---------------------------------------------------------------------------
# _parse_filename_parts
# ---------------------------------------------------------------------------


def test_parse_filename_parts_standard() -> None:
    client, report, from_d, to_d = _parse_filename_parts(
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31"
    )
    assert client == "Legend"
    # trillioncoverscom is file_name_extra (RSID); report name is resolved via headers YAML
    assert report == "botInvestigationMetricsByBrowser"
    assert from_d == "2026-01-01"
    assert to_d == "2026-01-31"


def test_parse_filename_parts_topline() -> None:
    client, report, from_d, to_d = _parse_filename_parts(
        "Legend_toplineMetricsForRsidValidation_trillioncoverscom_2026-01-01_2026-01-31"
    )
    assert client == "Legend"
    assert report == "toplineMetricsForRsidValidation"
    assert from_d == "2026-01-01"
    assert to_d == "2026-01-31"


def test_parse_filename_parts_too_short() -> None:
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_filename_parts("a_b_c")


# ---------------------------------------------------------------------------
# load_column_headers
# ---------------------------------------------------------------------------


def test_load_column_headers_browser() -> None:
    cols = load_column_headers("botInvestigationMetricsByBrowser", _HEADERS_DIR)
    assert cols[0] == "id"
    assert cols[1] == "browser"
    assert cols[-1] == "toDate"


def test_load_column_headers_topline() -> None:
    cols = load_column_headers("toplineMetricsForRsidValidation", _HEADERS_DIR)
    assert cols == ["unique_visitors", "visits", "fileName", "fromDate", "toDate"]


def test_load_column_headers_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_column_headers("nonExistentReport", tmp_path)


# ---------------------------------------------------------------------------
# transform_report — dimensional (has rows)
# ---------------------------------------------------------------------------


def test_transform_report_dimensional_matches_fixture() -> None:
    json_path = _FIXTURES / "base" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    expected = (_FIXTURES / "base" / "expected.csv").read_text(encoding="utf-8")

    result = transform_report(json_path, _HEADERS_DIR)
    assert result == expected


def test_transform_report_dimensional_writes_file(tmp_path: Path) -> None:
    json_path = _FIXTURES / "base" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    out = tmp_path / "out.csv"
    transform_report(json_path, _HEADERS_DIR, output_path=out)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("id,browser")
    assert len(lines) == 3  # header + 2 data rows


def test_transform_report_dimensional_row_count() -> None:
    json_path = _FIXTURES / "base" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_report(json_path, _HEADERS_DIR)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert len(lines) == 3  # header + 2 rows


def test_transform_report_dimensional_metadata_columns() -> None:
    json_path = _FIXTURES / "base" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_report(json_path, _HEADERS_DIR)
    rows = csv_text.splitlines()
    data_row = rows[1].split(",")
    # fileName is second-to-last-3rd column, fromDate second to last, toDate last
    assert data_row[-3] == (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31"
    )
    assert data_row[-2] == "2026-01-01"
    assert data_row[-1] == "2026-01-31"


def test_transform_report_no_rows_returns_header_only(tmp_path: Path) -> None:
    json_path = tmp_path / "Legend_botInvestigationMetricsByBrowser_rsid_2026-01-01_2026-01-31.json"
    json_path.write_text(json.dumps({"rows": []}), encoding="utf-8")
    csv_text = transform_report(json_path, _HEADERS_DIR)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert len(lines) == 1  # header only


# ---------------------------------------------------------------------------
# transform_report — summary/totals (summaryData)
# ---------------------------------------------------------------------------


def test_transform_report_summary_matches_fixture() -> None:
    json_path = _FIXTURES / "summary_total_only" / (
        "Legend_toplineMetricsForRsidValidation_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    expected = (_FIXTURES / "summary_total_only" / "expected.csv").read_text(encoding="utf-8")
    result = transform_report(json_path, _HEADERS_DIR)
    assert result == expected


def test_transform_report_summary_single_row() -> None:
    json_path = _FIXTURES / "summary_total_only" / (
        "Legend_toplineMetricsForRsidValidation_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_report(json_path, _HEADERS_DIR)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert len(lines) == 2  # header + 1 row


def test_transform_report_summary_values() -> None:
    json_path = _FIXTURES / "summary_total_only" / (
        "Legend_toplineMetricsForRsidValidation_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_report(json_path, _HEADERS_DIR)
    data_row = csv_text.splitlines()[1].split(",")
    assert data_row[0] == "45000"
    assert data_row[1] == "80000"


# ---------------------------------------------------------------------------
# transform_report — column count mismatch raises
# ---------------------------------------------------------------------------


def test_transform_report_column_mismatch_raises(tmp_path: Path) -> None:
    json_path = tmp_path / "Legend_botInvestigationMetricsByBrowser_rsid_2026-01-01_2026-01-31.json"
    json_path.write_text(
        json.dumps({"rows": [{"itemId": "1", "value": "Chrome", "data": [1]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="column"):
        transform_report(json_path, _HEADERS_DIR)


# ---------------------------------------------------------------------------
# make_csv_output_path
# ---------------------------------------------------------------------------


def test_make_csv_output_path_replaces_json_dir() -> None:
    p = Path("/base/client/JSON/Legend_report_2026-01-01_2026-01-31.json")
    result = make_csv_output_path(p)
    assert result == Path("/base/client/CSV/Legend_report_2026-01-01_2026-01-31.csv")


def test_make_csv_output_path_no_json_dir() -> None:
    p = Path("/some/other/dir/report.json")
    result = make_csv_output_path(p)
    assert result.suffix == ".csv"
    assert result.stem == "report"


# ---------------------------------------------------------------------------
# concatenate_csvs
# ---------------------------------------------------------------------------


def _write_csv(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_concatenate_csvs_basic(tmp_path: Path) -> None:
    folder = tmp_path / "csv"
    _write_csv(folder / "a.csv", "col1,col2\n1,2\n3,4\n")
    _write_csv(folder / "b.csv", "col1,col2\n5,6\n")
    out = tmp_path / "out.csv"
    count = concatenate_csvs(folder, "*.csv", out)
    assert count == 2
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "col1,col2"
    assert len(lines) == 4  # header + 3 data rows


def test_concatenate_csvs_pattern_filter(tmp_path: Path) -> None:
    folder = tmp_path / "csv"
    _write_csv(folder / "bot_a.csv", "h1\nrow1\n")
    _write_csv(folder / "other_b.csv", "h1\nrow2\n")
    out = tmp_path / "out.csv"
    count = concatenate_csvs(folder, "bot_*.csv", out)
    assert count == 1
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "row1" in lines
    assert "row2" not in lines


def test_concatenate_csvs_no_match_returns_zero(tmp_path: Path) -> None:
    folder = tmp_path / "csv"
    folder.mkdir()
    out = tmp_path / "out.csv"
    count = concatenate_csvs(folder, "*.csv", out)
    assert count == 0
    assert not out.exists()


def test_concatenate_csvs_custom_headers(tmp_path: Path) -> None:
    folder = tmp_path / "csv"
    _write_csv(folder / "a.csv", "old_name,col2\n1,2\n")
    out = tmp_path / "out.csv"
    concatenate_csvs(folder, "*.csv", out, custom_headers={0: "new_name"})
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "new_name,col2"


def test_concatenate_csvs_creates_output_dir(tmp_path: Path) -> None:
    folder = tmp_path / "csv"
    _write_csv(folder / "a.csv", "h\n1\n")
    out = tmp_path / "nested" / "deep" / "out.csv"
    concatenate_csvs(folder, "*.csv", out)
    assert out.exists()


def test_concatenate_csvs_deduplicates_header(tmp_path: Path) -> None:
    folder = tmp_path / "csv"
    _write_csv(folder / "a.csv", "col1,col2\n1,2\n")
    _write_csv(folder / "b.csv", "col1,col2\n3,4\n")
    out = tmp_path / "out.csv"
    concatenate_csvs(folder, "*.csv", out)
    content = out.read_text(encoding="utf-8")
    assert content.count("col1,col2") == 1
