"""Tests for core/request_builder.py — validate against request body fixtures."""

import json
from pathlib import Path

import pytest

from adobe_downloader.config.schema import DateRange, ReportDefinitionInline
from adobe_downloader.core.request_builder import build_request

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "request_bodies"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _date_range(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


# ---------------------------------------------------------------------------
# botInvestigationMetricsByBrowser
# ---------------------------------------------------------------------------

def test_bot_investigation_by_browser_matches_fixture():
    report_def = ReportDefinitionInline(
        name="botInvestigationMetricsByBrowser",
        dimension="variables/browser",
        row_limit=500,
        segments=["s3938_66fe79408ff02713f66ed76b"],
        metrics=[
            "metrics/event3",
            "cm3938_602b915cb99757640284234e",
            "cm3938_66d0bfba05c95b4eca739eb4",
            "metrics/itemtimespent",
            "metrics/pageviews",
        ],
        csv_headers=[
            "id", "browser", "unique_visitors", "visits",
            "Raw_Clickouts", "Engaged_Visits", "First_Time_Visits",
            "Total_Seconds_Spent", "Page_Views", "fileName", "fromDate", "toDate",
        ],
    )
    body = build_request(
        report_def,
        _date_range("2026-01-01", "2026-01-31"),
        "trillioncoverscom",
    )
    assert body == _load_fixture("botInvestigationMetricsByBrowser")


# ---------------------------------------------------------------------------
# botFilterExcludeMetricsByMonth (with runtime extra segment)
# ---------------------------------------------------------------------------

def test_bot_filter_exclude_by_month_matches_fixture():
    report_def = ReportDefinitionInline(
        name="botFilterExcludeMetricsByMonth",
        dimension="variables/daterangemonth",
        row_limit=5000,
        segments=["s3938_66fe79408ff02713f66ed76b"],
        metrics=[
            "metrics/event3",
            "cm3938_602b915cb99757640284234e",
            "cm3938_5fcf3ee998b6d77a9d7167ad",
            "cm3938_66d0bfba05c95b4eca739eb4",
            "metrics/itemtimespent",
            "metrics/pageviews",
        ],
        csv_headers=[
            "id", "month", "unique_visitors", "visits",
            "raw_clickouts", "engaged_visits", "engagement_rate",
            "First_Time_Visits", "Total_Seconds_Spent", "Page_Views",
            "fileName", "requestName", "botRuleName", "rsidName",
        ],
    )
    body = build_request(
        report_def,
        _date_range("2026-01-01", "2026-01-31"),
        "trillioncoverscom",
        segments=["s3938_66843aaa4e73b6231c8a7556"],
    )
    assert body == _load_fixture("botFilterExcludeMetricsByMonth")


# ---------------------------------------------------------------------------
# toplineMetricsForRsidValidation (no dimension, no extra metrics)
# ---------------------------------------------------------------------------

def test_topline_metrics_for_rsid_validation_matches_fixture():
    report_def = ReportDefinitionInline(
        name="toplineMetricsForRsidValidation",
        dimension=None,
        row_limit=10,
        segments=["s3938_61bb0165a88ab931afa78e4c"],
        metrics=[],
        csv_headers=["unique_visitors", "visits", "fileName", "fromDate", "toDate"],
    )
    body = build_request(
        report_def,
        _date_range("2026-01-01", "2026-01-31"),
        "trillioncoverscom",
    )
    assert body == _load_fixture("toplineMetricsForRsidValidation")


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def _minimal_def(**kwargs) -> ReportDefinitionInline:
    defaults = dict(
        name="test",
        dimension=None,
        row_limit=500,
        segments=[],
        metrics=[],
        csv_headers=[],
    )
    defaults.update(kwargs)
    return ReportDefinitionInline(**defaults)


def _dr() -> DateRange:
    return _date_range("2026-01-01", "2026-01-31")


def test_date_range_format():
    body = build_request(_minimal_def(), _dr(), "myrsid")
    assert body["globalFilters"][0]["dateRange"] == (
        "2026-01-01T00:00:00.000/2026-01-31T00:00:00.000"
    )


def test_visitors_and_visits_always_first():
    body = build_request(_minimal_def(), _dr(), "myrsid")
    metrics = body["metricContainer"]["metrics"]
    assert metrics[0] == {"columnId": "0", "id": "metrics/visitors", "sort": "desc"}
    assert metrics[1] == {"columnId": "1", "id": "metrics/visits", "sort": "desc"}


def test_extra_metrics_start_at_column_2():
    body = build_request(
        _minimal_def(metrics=["metrics/event3", "metrics/pageviews"]),
        _dr(),
        "myrsid",
    )
    metrics = body["metricContainer"]["metrics"]
    assert len(metrics) == 4
    assert metrics[2] == {"columnId": "2", "id": "metrics/event3"}
    assert metrics[3] == {"columnId": "3", "id": "metrics/pageviews"}


def test_dimension_omitted_when_none():
    body = build_request(_minimal_def(dimension=None), _dr(), "myrsid")
    assert "dimension" not in body


def test_dimension_included_when_set():
    body = build_request(_minimal_def(dimension="variables/browser"), _dr(), "myrsid")
    assert body["dimension"] == "variables/browser"


def test_report_segments_before_extra_segments():
    body = build_request(
        _minimal_def(segments=["seg_report"]),
        _dr(),
        "myrsid",
        segments=["seg_extra"],
    )
    filters = body["globalFilters"]
    seg_ids = [f["segmentId"] for f in filters if f["type"] == "segment"]
    assert seg_ids == ["seg_report", "seg_extra"]


def test_settings_block_complete():
    body = build_request(_minimal_def(row_limit=250), _dr(), "myrsid")
    assert body["settings"] == {
        "countRepeatInstances": True,
        "includeAnnotations": True,
        "page": 0,
        "nonesBehavior": "return-nones",
        "limit": 250,
    }


def test_rsid_set_correctly():
    body = build_request(_minimal_def(), _dr(), "my_report_suite")
    assert body["rsid"] == "my_report_suite"
