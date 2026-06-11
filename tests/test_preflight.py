"""Tests for flows/preflight.py — pre-flight metric validation via probe report."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adobe_downloader.flows.preflight import validate_report_metrics, _build_probe_request
from adobe_downloader.config.schema import DateRange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_RANGE = DateRange(**{"from": "2026-01-01", "to": "2026-01-31"})


def _client(column_errors_by_rsid: dict[str, list[str]]) -> MagicMock:
    """Return a mock AdobeClient whose get_report returns columnErrors for the given RSIDs.

    column_errors_by_rsid maps rsid -> list of columnIds that should have errors.
    """
    client = MagicMock()

    async def _get_report(body: dict[str, Any]) -> dict[str, Any]:
        rsid = body["rsid"]
        error_col_ids = column_errors_by_rsid.get(rsid, [])
        column_errors = [{"columnId": cid, "errorCode": "invalid_metric"} for cid in error_col_ids]
        return {"columns": {"columnErrors": column_errors}, "rows": []}

    client.get_report = _get_report
    return client


def _report_def(*metric_ids: str) -> MagicMock:
    rd = MagicMock()
    rd.metrics = list(metric_ids)
    return rd


# ---------------------------------------------------------------------------
# Probe request shape
# ---------------------------------------------------------------------------


def test_probe_request_uses_single_day_from_date_range():
    body = _build_probe_request("rsid1", ["metrics/visits"], _DATE_RANGE)
    date_filter = next(f for f in body["globalFilters"] if f["type"] == "dateRange")
    assert date_filter["dateRange"].startswith("2026-01-01T")
    assert "2026-01-01T" in date_filter["dateRange"]


def test_probe_request_assigns_sequential_column_ids():
    metrics = ["metrics/visits", "metrics/pageviews", "cm_fake"]
    body = _build_probe_request("rsid1", metrics, _DATE_RANGE)
    cols = body["metricContainer"]["metrics"]
    assert [(c["columnId"], c["id"]) for c in cols] == [
        ("0", "metrics/visits"),
        ("1", "metrics/pageviews"),
        ("2", "cm_fake"),
    ]


def test_probe_request_limit_is_one():
    body = _build_probe_request("rsid1", ["metrics/visits"], _DATE_RANGE)
    assert body["settings"]["limit"] == 1


# ---------------------------------------------------------------------------
# Validation logic — three scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_valid_metrics_no_error():
    """Only valid metric IDs — get_report returns no columnErrors."""
    client = _client({"rsid1": []})
    rd = _report_def("metrics/visits", "metrics/pageviews")
    await validate_report_metrics(client, ["rsid1"], [rd], _DATE_RANGE)  # must not raise


@pytest.mark.asyncio
async def test_only_invalid_metrics_raises():
    """Only nonsense metric IDs — all columns have errors."""
    client = _client({"rsid1": ["0", "1"]})
    rd = _report_def("cm_fake_a", "cm_fake_b")
    with pytest.raises(ValueError, match="Pre-flight metric validation failed"):
        await validate_report_metrics(client, ["rsid1"], [rd], _DATE_RANGE)


@pytest.mark.asyncio
async def test_mix_of_valid_and_invalid_raises():
    """One valid metric, one invalid — the invalid one causes a failure."""
    # columnId "1" (cm_fake) errors; columnId "0" (metrics/visits) is fine
    client = _client({"rsid1": ["1"]})
    rd = _report_def("metrics/visits", "cm_fake")
    with pytest.raises(ValueError) as exc_info:
        await validate_report_metrics(client, ["rsid1"], [rd], _DATE_RANGE)
    msg = str(exc_info.value)
    assert "cm_fake" in msg
    assert "metrics/visits" not in msg


# ---------------------------------------------------------------------------
# Error message content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_names_rsid_and_bad_metric():
    client = _client({"rsid1": ["0"]})
    rd = _report_def("cm_fake")
    with pytest.raises(ValueError) as exc_info:
        await validate_report_metrics(client, ["rsid1"], [rd], _DATE_RANGE)
    msg = str(exc_info.value)
    assert "rsid1" in msg
    assert "cm_fake" in msg


@pytest.mark.asyncio
async def test_multiple_rsids_only_failing_rsid_named():
    client = _client({"rsid_ok": [], "rsid_bad": ["0"]})
    rd = _report_def("cm_fake")
    with pytest.raises(ValueError) as exc_info:
        await validate_report_metrics(client, ["rsid_ok", "rsid_bad"], [rd], _DATE_RANGE)
    msg = str(exc_info.value)
    assert "rsid_bad" in msg
    assert "rsid_ok" not in msg


@pytest.mark.asyncio
async def test_multiple_rsids_all_failing_both_named():
    client = _client({"rsid_a": ["0"], "rsid_b": ["0"]})
    rd = _report_def("cm_fake")
    with pytest.raises(ValueError) as exc_info:
        await validate_report_metrics(client, ["rsid_a", "rsid_b"], [rd], _DATE_RANGE)
    msg = str(exc_info.value)
    assert "rsid_a" in msg
    assert "rsid_b" in msg


@pytest.mark.asyncio
async def test_multiple_bad_metrics_all_listed():
    client = _client({"rsid1": ["0", "1"]})
    rd = _report_def("cm_fake_a", "cm_fake_b")
    with pytest.raises(ValueError) as exc_info:
        await validate_report_metrics(client, ["rsid1"], [rd], _DATE_RANGE)
    msg = str(exc_info.value)
    assert "cm_fake_a" in msg
    assert "cm_fake_b" in msg


@pytest.mark.asyncio
async def test_metrics_union_across_report_defs():
    """Bad metric from a second report_def is still caught."""
    client = _client({"rsid1": ["1"]})  # columnId "1" = second unique metric
    rd1 = _report_def("metrics/visits")
    rd2 = _report_def("cm_fake")
    with pytest.raises(ValueError) as exc_info:
        await validate_report_metrics(client, ["rsid1"], [rd1, rd2], _DATE_RANGE)
    assert "cm_fake" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Short-circuit when nothing to validate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_metrics_makes_no_api_call():
    client = MagicMock()
    client.get_report = AsyncMock()
    rd = _report_def()
    await validate_report_metrics(client, ["rsid1"], [rd], _DATE_RANGE)
    client.get_report.assert_not_called()


@pytest.mark.asyncio
async def test_empty_report_defs_makes_no_api_call():
    client = MagicMock()
    client.get_report = AsyncMock()
    await validate_report_metrics(client, ["rsid1"], [], _DATE_RANGE)
    client.get_report.assert_not_called()
