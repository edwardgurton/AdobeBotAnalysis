"""Tests for Step 16: test mode — utils/test_mode.py and --test flag wiring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adobe_downloader.config.schema import (
    DateRange,
    ReportDownloadConfig,
    RsidSource,
    TestLimits,
)
from adobe_downloader.utils.test_mode import (
    apply_all_limits,
    apply_date_limit,
    apply_rsid_limit,
    apply_segment_limit,
)


# ---------------------------------------------------------------------------
# TestLimits schema defaults
# ---------------------------------------------------------------------------


def test_test_limits_defaults() -> None:
    lim = TestLimits()
    assert lim.max_rsids == 3
    assert lim.max_date_intervals == 2
    assert lim.max_segments == 5


def test_test_limits_custom() -> None:
    lim = TestLimits(max_rsids=1, max_date_intervals=1, max_segments=2)
    assert lim.max_rsids == 1
    assert lim.max_date_intervals == 1
    assert lim.max_segments == 2


# ---------------------------------------------------------------------------
# apply_rsid_limit
# ---------------------------------------------------------------------------


def test_apply_rsid_limit_truncates() -> None:
    rsids = ["a", "b", "c", "d", "e"]
    lim = TestLimits(max_rsids=2, max_date_intervals=99, max_segments=99)
    assert apply_rsid_limit(rsids, lim) == ["a", "b"]


def test_apply_rsid_limit_does_not_pad() -> None:
    rsids = ["a"]
    lim = TestLimits(max_rsids=10, max_date_intervals=99, max_segments=99)
    assert apply_rsid_limit(rsids, lim) == ["a"]


def test_apply_rsid_limit_empty() -> None:
    assert apply_rsid_limit([], TestLimits()) == []


# ---------------------------------------------------------------------------
# apply_date_limit
# ---------------------------------------------------------------------------


def _dr(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


def test_apply_date_limit_truncates() -> None:
    intervals = [_dr("2025-01-01", "2025-02-01"), _dr("2025-02-01", "2025-03-01"),
                 _dr("2025-03-01", "2025-04-01")]
    lim = TestLimits(max_rsids=99, max_date_intervals=2, max_segments=99)
    result = apply_date_limit(intervals, lim)
    assert len(result) == 2
    assert result[0].from_date == "2025-01-01"
    assert result[1].from_date == "2025-02-01"


def test_apply_date_limit_no_truncation_needed() -> None:
    intervals = [_dr("2025-01-01", "2025-02-01")]
    lim = TestLimits(max_rsids=99, max_date_intervals=5, max_segments=99)
    assert apply_date_limit(intervals, lim) == intervals


# ---------------------------------------------------------------------------
# apply_segment_limit
# ---------------------------------------------------------------------------


def test_apply_segment_limit_truncates() -> None:
    segs = [("seg1", ["seg1"]), ("seg2", ["seg2"]), ("seg3", ["seg3"]), ("seg4", ["seg4"])]
    lim = TestLimits(max_rsids=99, max_date_intervals=99, max_segments=2)
    result = apply_segment_limit(segs, lim)
    assert len(result) == 2
    assert result[0][0] == "seg1"


def test_apply_segment_limit_single_item() -> None:
    segs = [(None, [])]
    lim = TestLimits(max_rsids=99, max_date_intervals=99, max_segments=1)
    assert apply_segment_limit(segs, lim) == segs


# ---------------------------------------------------------------------------
# apply_all_limits
# ---------------------------------------------------------------------------


def test_apply_all_limits_caps_all() -> None:
    rsids = ["r1", "r2", "r3", "r4"]
    dates = [_dr(f"2025-0{i}-01", f"2025-0{i+1}-01") for i in range(1, 5)]
    segs = [("s" + str(i), []) for i in range(6)]
    lim = TestLimits(max_rsids=2, max_date_intervals=3, max_segments=4)

    out_rsids, out_dates, out_segs = apply_all_limits(rsids, dates, segs, lim)

    assert len(out_rsids) == 2
    assert len(out_dates) == 3
    assert len(out_segs) == 4


def test_apply_all_limits_does_not_exceed_input() -> None:
    rsids = ["r1"]
    dates = [_dr("2025-01-01", "2025-02-01")]
    segs = [(None, [])]
    lim = TestLimits(max_rsids=10, max_date_intervals=10, max_segments=10)

    out_rsids, out_dates, out_segs = apply_all_limits(rsids, dates, segs, lim)

    assert out_rsids == rsids
    assert out_dates == dates
    assert out_segs == segs


# ---------------------------------------------------------------------------
# Schema: test_mode / test_limits on ReportDownloadConfig
# ---------------------------------------------------------------------------


def _base_report_config() -> dict:
    return {
        "job_type": "report_download",
        "client": "TestClient",
        "report_ref": "botInvestigationMetricsByBrowser",
        "rsids": {"source": "single", "single": "myrsid"},
        "date_range": {"from": "2025-01-01", "to": "2025-02-01"},
        "output": {"base_folder": "/tmp/out"},
    }


def test_report_download_test_mode_defaults_false() -> None:
    cfg = ReportDownloadConfig.model_validate(_base_report_config())
    assert cfg.test_mode is False
    assert isinstance(cfg.test_limits, TestLimits)


def test_report_download_test_mode_enabled_in_config() -> None:
    raw = {**_base_report_config(), "test_mode": True,
           "test_limits": {"max_rsids": 1, "max_date_intervals": 1, "max_segments": 1}}
    cfg = ReportDownloadConfig.model_validate(raw)
    assert cfg.test_mode is True
    assert cfg.test_limits.max_rsids == 1


# ---------------------------------------------------------------------------
# run_report_download applies limits when test_limits provided
# ---------------------------------------------------------------------------


def _make_sm(tmp_path: Path) -> MagicMock:
    sm = MagicMock()
    sm.job_id = "test-job"
    sm.is_complete.return_value = False
    sm.track_request.return_value = ("req-id", None)
    return sm


def _make_ac() -> AsyncMock:
    ac = AsyncMock()
    ac.get_report = AsyncMock(return_value={"rows": [], "summaryData": {"totals": [0, 0]}})
    return ac


@pytest.mark.asyncio
async def test_run_report_download_test_limits_caps_rsids(tmp_path: Path) -> None:
    """With max_rsids=1, only one RSID is downloaded even if five are provided."""
    from adobe_downloader.config.report_definitions import load_report_registry
    from adobe_downloader.flows.report_download import run_report_download

    registry = load_report_registry()
    report_def = registry["botInvestigationMetricsByBrowser"]

    rsids = RsidSource.model_validate({"source": "list", "list": ["r1", "r2", "r3", "r4", "r5"]})
    date_range = _dr("2025-01-01", "2025-02-01")
    sm = _make_sm(tmp_path)
    ac = _make_ac()
    limits = TestLimits(max_rsids=1, max_date_intervals=99, max_segments=99)

    result = await run_report_download(
        client=ac,
        client_name="TestClient",
        report_defs=[report_def],
        rsids=rsids,
        date_range=date_range,
        interval="full",
        output_base=str(tmp_path),
        sm=sm,
        test_limits=limits,
    )

    # Only 1 RSID processed → 1 download attempt
    assert ac.get_report.call_count == 1


@pytest.mark.asyncio
async def test_run_report_download_test_limits_caps_dates(tmp_path: Path) -> None:
    """With max_date_intervals=1 and interval=month across 3 months, only 1 interval runs."""
    from adobe_downloader.config.report_definitions import load_report_registry
    from adobe_downloader.flows.report_download import run_report_download

    registry = load_report_registry()
    report_def = registry["botInvestigationMetricsByBrowser"]

    rsids = RsidSource.model_validate({"source": "single", "single": "rsid1"})
    date_range = _dr("2025-01-01", "2025-04-01")  # 3 month intervals
    sm = _make_sm(tmp_path)
    ac = _make_ac()
    limits = TestLimits(max_rsids=99, max_date_intervals=1, max_segments=99)

    result = await run_report_download(
        client=ac,
        client_name="TestClient",
        report_defs=[report_def],
        rsids=rsids,
        date_range=date_range,
        interval="month",
        output_base=str(tmp_path),
        sm=sm,
        test_limits=limits,
    )

    assert ac.get_report.call_count == 1


@pytest.mark.asyncio
async def test_run_report_download_no_test_limits_runs_all(tmp_path: Path) -> None:
    """Without test_limits, all 2 RSIDs × 2 months = 4 downloads run."""
    from adobe_downloader.config.report_definitions import load_report_registry
    from adobe_downloader.flows.report_download import run_report_download

    registry = load_report_registry()
    report_def = registry["botInvestigationMetricsByBrowser"]

    rsids = RsidSource.model_validate({"source": "list", "list": ["r1", "r2"]})
    date_range = _dr("2025-01-01", "2025-03-01")  # 2 months
    sm = _make_sm(tmp_path)
    ac = _make_ac()

    result = await run_report_download(
        client=ac,
        client_name="TestClient",
        report_defs=[report_def],
        rsids=rsids,
        date_range=date_range,
        interval="month",
        output_base=str(tmp_path),
        sm=sm,
        test_limits=None,
    )

    assert ac.get_report.call_count == 4  # 2 RSIDs × 2 months


@pytest.mark.asyncio
async def test_run_report_download_test_limits_zero_rsids(tmp_path: Path) -> None:
    """max_rsids=0 → no downloads at all."""
    from adobe_downloader.config.report_definitions import load_report_registry
    from adobe_downloader.flows.report_download import run_report_download

    registry = load_report_registry()
    report_def = registry["botInvestigationMetricsByBrowser"]

    rsids = RsidSource.model_validate({"source": "list", "list": ["r1", "r2"]})
    date_range = _dr("2025-01-01", "2025-02-01")
    sm = _make_sm(tmp_path)
    ac = _make_ac()
    limits = TestLimits(max_rsids=0, max_date_intervals=99, max_segments=99)

    result = await run_report_download(
        client=ac,
        client_name="TestClient",
        report_defs=[report_def],
        rsids=rsids,
        date_range=date_range,
        interval="full",
        output_base=str(tmp_path),
        sm=sm,
        test_limits=limits,
    )

    assert ac.get_report.call_count == 0
    assert result.downloaded == 0
