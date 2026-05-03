"""Tests for adobe_downloader/transforms/specialized.py."""

from pathlib import Path

import pytest

from adobe_downloader.transforms.specialized import (
    _detect_transform_type,
    transform_bot_investigation,
    transform_bot_rule_compare,
    transform_bot_validation,
    transform_final_bot_rule_metrics,
    transform_report_dispatch,
    transform_summary_total_only,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "transforms"
_HEADERS_DIR = Path(__file__).parent.parent / "data" / "report_headers"


# ---------------------------------------------------------------------------
# _detect_transform_type
# ---------------------------------------------------------------------------


def test_detect_bot_investigation(tmp_path: Path) -> None:
    p = tmp_path / "Legend_botInvestigationMetricsByBrowser_rsid_2026-01-01_2026-01-31.json"
    assert _detect_transform_type(p) == "bot_investigation"


def test_detect_bot_validation(tmp_path: Path) -> None:
    p = tmp_path / "Legend_botFilterExcludeMetricsByMonth_Rule_rsid_2026-01-01_2026-01-31.json"
    assert _detect_transform_type(p) == "bot_validation"


def test_detect_bot_rule_compare(tmp_path: Path) -> None:
    p = tmp_path / (
        "Legend_botInvestigationMetricsByBrowserType_Casinoorg_FebMay25"
        "_UserAgent-Compare-V1-AllTraffic_2026-01-01_2026-01-31.json"
    )
    assert _detect_transform_type(p) == "bot_rule_compare"


def test_detect_final_bot_rule_metrics(tmp_path: Path) -> None:
    p = tmp_path / (
        "Legend_LegendFinalBotMetricsCurrentIncludeByYear_Extra_rsid_rule_2026-01-01_2026-01-31.json"
    )
    assert _detect_transform_type(p) == "final_bot_rule_metrics"


def test_detect_summary_total_only(tmp_path: Path) -> None:
    p = tmp_path / "Legend_toplineMetricsForRsidValidation_rsid_2026-01-01_2026-01-31.json"
    assert _detect_transform_type(p) == "summary_total_only"


# ---------------------------------------------------------------------------
# transform_bot_investigation — matches fixture (same as base)
# ---------------------------------------------------------------------------


def test_bot_investigation_matches_fixture() -> None:
    fixture_dir = _FIXTURES / "bot_investigation"
    json_path = fixture_dir / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    expected = (fixture_dir / "expected.csv").read_text(encoding="utf-8")
    result = transform_bot_investigation(json_path, _HEADERS_DIR)
    assert result == expected


def test_bot_investigation_row_count() -> None:
    json_path = _FIXTURES / "bot_investigation" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_bot_investigation(json_path, _HEADERS_DIR)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert len(lines) == 3  # header + 2 rows


# ---------------------------------------------------------------------------
# transform_bot_validation — matches fixture
# ---------------------------------------------------------------------------


def test_bot_validation_matches_fixture() -> None:
    fixture_dir = _FIXTURES / "bot_validation"
    json_path = fixture_dir / (
        "Legend_botFilterExcludeMetricsByMonth_Apr25ValidatedList_trillioncoverscom"
        "_2026-01-01_2026-01-31.json"
    )
    expected = (fixture_dir / "expected.csv").read_text(encoding="utf-8")
    result = transform_bot_validation(json_path, _HEADERS_DIR)
    assert result == expected


def test_bot_validation_metadata_columns() -> None:
    json_path = _FIXTURES / "bot_validation" / (
        "Legend_botFilterExcludeMetricsByMonth_Apr25ValidatedList_trillioncoverscom"
        "_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_bot_validation(json_path, _HEADERS_DIR)
    row = csv_text.splitlines()[1].split(",")
    assert row[-1] == "trillioncoverscom"   # rsidName
    assert row[-2] == "Apr25ValidatedList"  # botRuleName
    assert row[-3] == "botFilterExcludeMetricsByMonth"  # requestName


def test_bot_validation_no_rows_header_only(tmp_path: Path) -> None:
    import json as _json
    p = tmp_path / "Legend_botFilterExcludeMetricsByMonth_Rule_rsid_2026-01-01_2026-01-31.json"
    p.write_text(_json.dumps({"rows": []}), encoding="utf-8")
    csv_text = transform_bot_validation(p, _HEADERS_DIR)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert len(lines) == 1  # header only


# ---------------------------------------------------------------------------
# transform_final_bot_rule_metrics — matches fixture
# ---------------------------------------------------------------------------


def test_final_bot_rule_metrics_matches_fixture() -> None:
    fixture_dir = _FIXTURES / "final_bot_rule_metrics"
    json_path = fixture_dir / (
        "Legend_LegendFinalBotMetricsCurrentIncludeByYear_FinalBotMetrics"
        "_trillioncoverscom_Apr25ValidatedList_2025-12-01_2026-01-01.json"
    )
    expected = (fixture_dir / "expected.csv").read_text(encoding="utf-8")
    result = transform_final_bot_rule_metrics(json_path, _HEADERS_DIR)
    assert result == expected


def test_final_bot_rule_metrics_metadata_columns() -> None:
    json_path = _FIXTURES / "final_bot_rule_metrics" / (
        "Legend_LegendFinalBotMetricsCurrentIncludeByYear_FinalBotMetrics"
        "_trillioncoverscom_Apr25ValidatedList_2025-12-01_2026-01-01.json"
    )
    csv_text = transform_final_bot_rule_metrics(json_path, _HEADERS_DIR)
    row = csv_text.splitlines()[1].split(",")
    assert row[-1] == "2026-01-01"          # toDate
    assert row[-2] == "2025-12-01"          # fromDate
    assert row[-3] == "trillioncoverscom"   # rsidName
    assert row[-4] == "Apr25ValidatedList"  # botRuleName


# ---------------------------------------------------------------------------
# transform_bot_rule_compare — matches fixture
# ---------------------------------------------------------------------------


def test_bot_rule_compare_matches_fixture() -> None:
    fixture_dir = _FIXTURES / "bot_rule_compare"
    json_path = fixture_dir / (
        "Legend_botInvestigationMetricsByBrowserType_Casinoorg_FebMay25"
        "_UserAgent-Compare-V1-AllTraffic_2026-01-01_2026-01-31.json"
    )
    expected = (fixture_dir / "expected.csv").read_text(encoding="utf-8")
    result = transform_bot_rule_compare(json_path, _HEADERS_DIR)
    assert result == expected


def test_bot_rule_compare_metadata_columns() -> None:
    json_path = _FIXTURES / "bot_rule_compare" / (
        "Legend_botInvestigationMetricsByBrowserType_Casinoorg_FebMay25"
        "_UserAgent-Compare-V1-AllTraffic_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_bot_rule_compare(json_path, _HEADERS_DIR)
    header = csv_text.splitlines()[0].split(",")
    row = csv_text.splitlines()[1].split(",")
    assert header[9] == "fileName"
    assert header[13] == "rsidName"
    assert row[13] == "Casinoorg"    # rsidName
    assert row[14] == "UserAgent"    # botRuleName
    assert row[15] == "V1"           # compareVersion
    assert row[16] == "AllTraffic"   # trafficType
    assert row[17] == "true"         # isCompare
    assert row[18] == "false"        # isSegment
    assert row[19] == ""             # segmentId (empty for AllTraffic)
    assert row[20] == ""             # segmentHash (empty for AllTraffic)


def test_bot_rule_compare_row_count() -> None:
    json_path = _FIXTURES / "bot_rule_compare" / (
        "Legend_botInvestigationMetricsByBrowserType_Casinoorg_FebMay25"
        "_UserAgent-Compare-V1-AllTraffic_2026-01-01_2026-01-31.json"
    )
    csv_text = transform_bot_rule_compare(json_path, _HEADERS_DIR)
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    assert len(lines) == 3  # header + 2 rows


# ---------------------------------------------------------------------------
# transform_summary_total_only — matches fixture
# ---------------------------------------------------------------------------


def test_summary_total_only_matches_fixture() -> None:
    fixture_dir = _FIXTURES / "summary_total_only"
    json_path = fixture_dir / (
        "Legend_toplineMetricsForRsidValidation_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    expected = (fixture_dir / "expected.csv").read_text(encoding="utf-8")
    result = transform_summary_total_only(json_path, _HEADERS_DIR)
    assert result == expected


# ---------------------------------------------------------------------------
# transform_report_dispatch
# ---------------------------------------------------------------------------


def test_dispatch_auto_detect_bot_investigation() -> None:
    json_path = _FIXTURES / "bot_investigation" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    expected = (_FIXTURES / "bot_investigation" / "expected.csv").read_text(encoding="utf-8")
    assert transform_report_dispatch(json_path, headers_dir=_HEADERS_DIR) == expected


def test_dispatch_explicit_type_bot_validation() -> None:
    json_path = _FIXTURES / "bot_validation" / (
        "Legend_botFilterExcludeMetricsByMonth_Apr25ValidatedList_trillioncoverscom"
        "_2026-01-01_2026-01-31.json"
    )
    expected = (_FIXTURES / "bot_validation" / "expected.csv").read_text(encoding="utf-8")
    result = transform_report_dispatch(json_path, "bot_validation", _HEADERS_DIR)
    assert result == expected


def test_dispatch_unknown_type_raises() -> None:
    p = Path("dummy.json")
    with pytest.raises(ValueError, match="Unknown transform_type"):
        transform_report_dispatch(p, "no_such_type")


def test_dispatch_writes_file(tmp_path: Path) -> None:
    json_path = _FIXTURES / "bot_investigation" / (
        "Legend_botInvestigationMetricsByBrowser_trillioncoverscom_2026-01-01_2026-01-31.json"
    )
    out = tmp_path / "out.csv"
    transform_report_dispatch(json_path, "bot_investigation", _HEADERS_DIR, output_path=out)
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("id,browser")
