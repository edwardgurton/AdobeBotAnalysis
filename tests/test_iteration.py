"""Tests for flows/report_download iteration helpers (Step 6)."""

import json
from pathlib import Path

import pytest

from adobe_downloader.config.schema import DateRange, RsidSource, SegmentSource
from adobe_downloader.flows.report_download import (
    iterate_dates,
    iterate_rsids,
    iterate_segments,
    load_segment_list,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _date(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


def _rsid_source(source: str, **kwargs: object) -> RsidSource:
    return RsidSource.model_validate({"source": source, **kwargs})


def _seg_source(source: str, **kwargs: object) -> SegmentSource:
    return SegmentSource.model_validate({"source": source, **kwargs})


def _dates(it: object) -> list[tuple[str, str]]:
    return [(dr.from_date, dr.to) for dr in it]  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# iterate_dates — full
# ---------------------------------------------------------------------------


def test_iterate_dates_full_yields_one_item():
    result = _dates(iterate_dates(_date("2025-01-01", "2025-04-01"), "full"))
    assert result == [("2025-01-01", "2025-04-01")]


def test_iterate_dates_full_narrow_range():
    result = _dates(iterate_dates(_date("2025-01-15", "2025-01-20"), "full"))
    assert result == [("2025-01-15", "2025-01-20")]


# ---------------------------------------------------------------------------
# iterate_dates — month
# ---------------------------------------------------------------------------


def test_iterate_dates_month_three_complete_months():
    result = _dates(iterate_dates(_date("2025-01-01", "2025-04-01"), "month"))
    assert result == [
        ("2025-01-01", "2025-02-01"),
        ("2025-02-01", "2025-03-01"),
        ("2025-03-01", "2025-04-01"),
    ]


def test_iterate_dates_month_single_month():
    result = _dates(iterate_dates(_date("2025-06-01", "2025-07-01"), "month"))
    assert result == [("2025-06-01", "2025-07-01")]


def test_iterate_dates_month_partial_last_month():
    result = _dates(iterate_dates(_date("2025-01-01", "2025-02-15"), "month"))
    assert result == [
        ("2025-01-01", "2025-02-01"),
        ("2025-02-01", "2025-02-15"),
    ]


def test_iterate_dates_month_partial_first_month():
    result = _dates(iterate_dates(_date("2025-01-15", "2025-03-01"), "month"))
    assert result == [
        ("2025-01-15", "2025-02-01"),
        ("2025-02-01", "2025-03-01"),
    ]


def test_iterate_dates_month_year_boundary():
    result = _dates(iterate_dates(_date("2024-12-01", "2025-02-01"), "month"))
    assert result == [
        ("2024-12-01", "2025-01-01"),
        ("2025-01-01", "2025-02-01"),
    ]


# ---------------------------------------------------------------------------
# iterate_dates — day
# ---------------------------------------------------------------------------


def test_iterate_dates_day_three_days():
    result = _dates(iterate_dates(_date("2025-01-01", "2025-01-04"), "day"))
    assert result == [
        ("2025-01-01", "2025-01-02"),
        ("2025-01-02", "2025-01-03"),
        ("2025-01-03", "2025-01-04"),
    ]


def test_iterate_dates_day_single_day():
    result = _dates(iterate_dates(_date("2025-06-15", "2025-06-16"), "day"))
    assert result == [("2025-06-15", "2025-06-16")]


def test_iterate_dates_day_month_boundary():
    result = _dates(iterate_dates(_date("2025-01-30", "2025-02-02"), "day"))
    assert result == [
        ("2025-01-30", "2025-01-31"),
        ("2025-01-31", "2025-02-01"),
        ("2025-02-01", "2025-02-02"),
    ]


# ---------------------------------------------------------------------------
# iterate_rsids
# ---------------------------------------------------------------------------


def test_iterate_rsids_single():
    result = list(iterate_rsids(_rsid_source("single", single="myrsid")))
    assert result == ["myrsid"]


def test_iterate_rsids_list():
    result = list(iterate_rsids(_rsid_source("list", list=["rsid1", "rsid2", "rsid3"])))
    assert result == ["rsid1", "rsid2", "rsid3"]


def test_iterate_rsids_file(tmp_path: Path):
    rsid_file = tmp_path / "rsids.txt"
    rsid_file.write_text("rsidA\nrsidB\n\nrsidC\n", encoding="utf-8")
    result = list(iterate_rsids(_rsid_source("file", file=str(rsid_file))))
    assert result == ["rsidA", "rsidB", "rsidC"]


def test_iterate_rsids_file_strips_blank_lines(tmp_path: Path):
    rsid_file = tmp_path / "rsids.txt"
    rsid_file.write_text("\n  \nrsidX\n  rsidY  \n\n", encoding="utf-8")
    result = list(iterate_rsids(_rsid_source("file", file=str(rsid_file))))
    assert result == ["rsidX", "rsidY"]


# ---------------------------------------------------------------------------
# load_segment_list
# ---------------------------------------------------------------------------


def test_load_segment_list_returns_ids(tmp_path: Path):
    seg_file = tmp_path / "segments.json"
    seg_file.write_text(
        json.dumps([
            {"id": "seg_001", "name": "United States"},
            {"id": "seg_002", "name": "Canada"},
        ]),
        encoding="utf-8",
    )
    result = load_segment_list(seg_file)
    assert result == ["seg_001", "seg_002"]


def test_load_segment_list_empty_file(tmp_path: Path):
    seg_file = tmp_path / "empty.json"
    seg_file.write_text("[]", encoding="utf-8")
    assert load_segment_list(seg_file) == []


# ---------------------------------------------------------------------------
# iterate_segments
# ---------------------------------------------------------------------------


def test_iterate_segments_none_yields_one_empty():
    result = list(iterate_segments(None))
    assert result == [(None, [])]


def test_iterate_segments_inline_all_ids_together():
    cfg = _seg_source("inline", ids=["s1", "s2"])
    result = list(iterate_segments(cfg))
    assert result == [(None, ["s1", "s2"])]


def test_iterate_segments_segment_list_file(tmp_path: Path):
    seg_file = tmp_path / "segs.json"
    seg_file.write_text(
        json.dumps([
            {"id": "seg_001", "name": "US"},
            {"id": "seg_002", "name": "CA"},
            {"id": "seg_003", "name": "MX"},
        ]),
        encoding="utf-8",
    )
    cfg = _seg_source("segment_list_file", file=str(seg_file))
    result = list(iterate_segments(cfg))
    assert result == [
        ("seg_001", ["seg_001"]),
        ("seg_002", ["seg_002"]),
        ("seg_003", ["seg_003"]),
    ]


def test_iterate_segments_step_output_raises():
    cfg = _seg_source("step_output", step_id="some_step", output_key="segment_list_file")
    with pytest.raises(NotImplementedError):
        list(iterate_segments(cfg))
