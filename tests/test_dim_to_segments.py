"""Tests for segments/dim_to_segments.py and composite dim_to_segments step."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adobe_downloader.config.schema import DateRange
from adobe_downloader.segments.dim_to_segments import (
    DimSegmentsResult,
    _build_dim_segment_def,
    dim_to_segments,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _date(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


def _make_client(rows: list[dict], created_ids: list[str]) -> Any:
    """Return a mock AdobeClient that returns *rows* from get_report and creates segments."""
    id_iter = iter(created_ids)
    client = MagicMock()
    client.get_report = AsyncMock(
        return_value={"rows": rows, "summaryData": {"totals": []}}
    )

    async def _create_segment(seg_def: dict) -> dict:
        return {"id": next(id_iter), "name": seg_def["name"]}

    client.create_segment = AsyncMock(side_effect=_create_segment)
    return client


_ROWS = [
    {"itemId": "10001", "value": "Direct", "data": [100, 50]},
    {"itemId": "10002", "value": "Natural Search", "data": [80, 40]},
    {"itemId": "10003", "value": "Paid Search", "data": [60, 30]},
]

_DIM = "variables/marketingchannel.marketing-channel-attribution"
_RSID = "trillioncoverscom"
_DATE = _date("2025-01-01", "2025-01-31")


# ---------------------------------------------------------------------------
# _build_dim_segment_def
# ---------------------------------------------------------------------------


class TestBuildDimSegmentDef:
    def test_basic_shape(self) -> None:
        seg = _build_dim_segment_def(_DIM, "10001", "Direct", _RSID)
        assert seg["name"] == f"{_DIM} = Direct"
        assert seg["rsid"] == _RSID
        assert seg["isPostShardId"] is True
        assert seg["definition"]["func"] == "segment"
        assert seg["definition"]["version"] == [1, 0, 0]

    def test_predicate_uses_numeric_itemid(self) -> None:
        seg = _build_dim_segment_def(_DIM, "99999", "Foo", _RSID)
        pred = seg["definition"]["container"]["pred"]
        assert pred["func"] == "eq"
        assert pred["num"] == 99999
        assert pred["val"]["name"] == _DIM

    def test_container_context_is_hits(self) -> None:
        seg = _build_dim_segment_def(_DIM, "1", "x", _RSID)
        assert seg["definition"]["container"]["context"] == "hits"


# ---------------------------------------------------------------------------
# dim_to_segments — core behaviour
# ---------------------------------------------------------------------------


class TestDimToSegments:
    async def test_creates_segments_for_each_row(self, tmp_path: Path) -> None:
        client = _make_client(_ROWS[:2], ["seg_aaa", "seg_bbb"])
        out = tmp_path / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out, num_pairs=2)

        assert len(result.segments) == 2
        assert result.segments[0]["id"] == "seg_aaa"
        assert result.segments[1]["id"] == "seg_bbb"

    async def test_formatted_name_removes_spaces_and_replaces_colons(self, tmp_path: Path) -> None:
        rows = [{"itemId": "1", "value": "A: B C", "data": []}]
        client = _make_client(rows, ["s1"])
        # API echoes the name we sent; name = "{dim} = A: B C"
        raw_name = f"{_DIM} = A: B C"
        client.create_segment = AsyncMock(return_value={"id": "s1", "name": raw_name})
        out = tmp_path / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out, num_pairs=1)
        assert " " not in result.segments[0]["name"]
        assert result.segments[0]["name"] == raw_name.replace(":", "-").replace(" ", "")

    async def test_writes_json_to_output_path(self, tmp_path: Path) -> None:
        client = _make_client(_ROWS[:1], ["s1"])
        out = tmp_path / "sub" / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out)
        assert out.exists()
        saved = json.loads(out.read_text())
        assert isinstance(saved, list)
        assert saved[0]["id"] == "s1"

    async def test_result_segment_list_file_matches_output_path(self, tmp_path: Path) -> None:
        client = _make_client(_ROWS[:1], ["s1"])
        out = tmp_path / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out)
        assert result.segment_list_file == out

    async def test_num_pairs_respected_in_request_settings(self, tmp_path: Path) -> None:
        client = _make_client([], [])
        out = tmp_path / "segs.json"
        await dim_to_segments(client, _DIM, _RSID, _DATE, out, num_pairs=5)
        called_body = client.get_report.call_args[0][0]
        assert called_body["settings"]["limit"] == 5

    async def test_additional_segments_added_to_request(self, tmp_path: Path) -> None:
        client = _make_client([], [])
        out = tmp_path / "segs.json"
        await dim_to_segments(
            client, _DIM, _RSID, _DATE, out, additional_segments=["seg_abc"]
        )
        called_body = client.get_report.call_args[0][0]
        seg_filters = [f for f in called_body["globalFilters"] if f.get("type") == "segment"]
        assert any(f["segmentId"] == "seg_abc" for f in seg_filters)

    async def test_rows_without_value_or_itemid_skipped(self, tmp_path: Path) -> None:
        rows = [
            {"itemId": "", "value": "Good", "data": []},  # empty itemId
            {"itemId": "10001", "value": "", "data": []},  # empty value
            {"itemId": "10002", "value": "Valid", "data": []},
        ]
        client = _make_client(rows, ["s_good"])
        # Only one valid row
        client.create_segment = AsyncMock(return_value={"id": "s_good", "name": "name"})
        out = tmp_path / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out, num_pairs=10)
        assert len(result.segments) == 1

    async def test_failed_segment_creation_logged_not_raised(self, tmp_path: Path) -> None:
        client = _make_client(_ROWS[:2], [])
        client.create_segment = AsyncMock(side_effect=Exception("API error"))
        out = tmp_path / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out, num_pairs=2)
        # Failures are swallowed; result has empty segments list
        assert result.segments == []
        assert out.exists()

    async def test_empty_rows_returns_empty_segments(self, tmp_path: Path) -> None:
        client = _make_client([], [])
        out = tmp_path / "segs.json"
        result = await dim_to_segments(client, _DIM, _RSID, _DATE, out)
        assert result.segments == []
        saved = json.loads(out.read_text())
        assert saved == []

    async def test_dimension_set_in_request_body(self, tmp_path: Path) -> None:
        client = _make_client([], [])
        out = tmp_path / "segs.json"
        await dim_to_segments(client, _DIM, _RSID, _DATE, out)
        called_body = client.get_report.call_args[0][0]
        assert called_body["dimension"] == _DIM


# ---------------------------------------------------------------------------
# composite _run_dim_to_segments_step
# ---------------------------------------------------------------------------


class TestCompositeDimToSegmentsStep:
    def _make_job(self, tmp_path: Path, *, with_date_range: bool = True) -> Any:
        from adobe_downloader.config.schema import CompositeJobConfig, CompositeStep, DateRange, OutputConfig

        extra: dict[str, Any] = {
            "dim_to_segments": {
                "dimension": _DIM,
                "rsid": _RSID,
                "num_pairs": 2,
            }
        }
        step = CompositeStep(step="dim_to_segments", id="create_segs", **extra)
        dr = DateRange.model_validate({"from": "2025-01-01", "to": "2025-01-31"}) if with_date_range else None
        job = CompositeJobConfig(
            job_type="composite",
            client="TestClient",
            steps=[step],
            date_range=dr,
            output=OutputConfig(base_folder=str(tmp_path)),
        )
        return job

    async def test_step_returns_segment_list_file_key(self, tmp_path: Path) -> None:
        from adobe_downloader.flows.composite_job import _run_dim_to_segments_step

        job = self._make_job(tmp_path)
        client = _make_client(_ROWS[:1], ["s1"])

        outputs = await _run_dim_to_segments_step(
            job.steps[0], job, {}, client
        )
        assert "segment_list_file" in outputs
        assert Path(outputs["segment_list_file"]).exists()

    async def test_step_raises_if_no_date_range(self, tmp_path: Path) -> None:
        from adobe_downloader.flows.composite_job import _run_dim_to_segments_step

        job = self._make_job(tmp_path, with_date_range=False)
        client = _make_client([], [])

        with pytest.raises(ValueError, match="date_range"):
            await _run_dim_to_segments_step(job.steps[0], job, {}, client)

    async def test_step_segment_list_path_under_client_dir(self, tmp_path: Path) -> None:
        from adobe_downloader.flows.composite_job import _run_dim_to_segments_step

        job = self._make_job(tmp_path)
        client = _make_client([], [])

        outputs = await _run_dim_to_segments_step(job.steps[0], job, {}, client)
        seg_path = Path(outputs["segment_list_file"])
        # Path should be <output_base>/TestClient/segments/create_segs_segments.json
        assert "TestClient" in str(seg_path)
        assert seg_path.name == "create_segs_segments.json"
