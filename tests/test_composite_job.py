"""Tests for composite job runner and step_state StateManager additions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adobe_downloader.config.schema import (
    CompositeJobConfig,
    CompositeStep,
    DateRange,
    OutputConfig,
    RsidSource,
    SegmentSource,
)
from adobe_downloader.flows.composite_job import (
    _coerce_date_range,
    _resolve_output_base,
    _resolve_report_defs,
    _resolve_segments,
    run_composite_job,
)
from adobe_downloader.state_manager import (
    StateManager,
    compute_config_hash,
    compute_job_id,
    state_db_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path, suffix: str = "") -> StateManager:
    config_file = tmp_path / f"job{suffix}.yaml"
    config_file.write_text("job_type: composite\nclient: TestClient\n")
    config_hash = compute_config_hash(config_file)
    job_id = compute_job_id(config_file, config_hash)
    db_path = state_db_path(tmp_path, "TestClient", job_id)
    return StateManager(db_path, job_id, config_file, config_hash)


def _date(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


def _composite_job(**kwargs: Any) -> CompositeJobConfig:
    defaults: dict[str, Any] = {
        "job_type": "composite",
        "client": "Legend",
        "steps": [],
        "output": {"base_folder": "/tmp/out"},
    }
    defaults.update(kwargs)
    return CompositeJobConfig.model_validate(defaults)


# ---------------------------------------------------------------------------
# StateManager: step_state methods
# ---------------------------------------------------------------------------


class TestStepState:
    def test_step_not_complete_initially(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        assert sm.is_step_complete("step_a") is False

    def test_mark_step_started_and_complete(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        sm.mark_step_started("step_a")
        assert sm.is_step_complete("step_a") is False  # in_progress, not complete

        sm.mark_step_complete("step_a", {"some_key": "some_value"})
        assert sm.is_step_complete("step_a") is True

    def test_get_step_outputs_returns_stored_dict(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        sm.mark_step_started("step_a")
        sm.mark_step_complete("step_a", {"json_folder": "/data/JSON", "job_id": "abc123"})

        outputs = sm.get_step_outputs("step_a")
        assert outputs == {"json_folder": "/data/JSON", "job_id": "abc123"}

    def test_get_step_outputs_none_if_not_run(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        assert sm.get_step_outputs("missing_step") is None

    def test_mark_step_failed(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        sm.mark_step_started("step_a")
        sm.mark_step_failed("step_a", "API error")
        assert sm.is_step_complete("step_a") is False

    def test_path_values_serialise_correctly(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        sm.mark_step_started("step_a")
        p = tmp_path / "segs.json"
        sm.mark_step_complete("step_a", {"segment_list_file": p})
        outputs = sm.get_step_outputs("step_a")
        # Path is converted to str via json default=str, forward slashes vary by OS
        assert Path(outputs["segment_list_file"]) == p

    def test_full_reset_clears_step_state(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        sm.mark_step_started("step_a")
        sm.mark_step_complete("step_a", {"x": 1})
        sm.full_reset()
        assert sm.is_step_complete("step_a") is False
        assert sm.get_step_outputs("step_a") is None


# ---------------------------------------------------------------------------
# StateManager: step_id scoping in track_request / is_complete
# ---------------------------------------------------------------------------


class TestStepIdScoping:
    def test_is_complete_with_step_id(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        req_id, _ = sm.track_request(
            "rsid1|rep1|2025-01-01|2025-01-02|",
            {"rsid": "rsid1"},
            Path("/out/file.json"),
            step_id="step_a",
        )
        sm.mark_started(req_id)
        sm.mark_complete(req_id, Path("/out/file.json"))

        assert sm.is_complete("rsid1|rep1|2025-01-01|2025-01-02|", step_id="step_a") is True
        # Without step_id prefix the key doesn't exist
        assert sm.is_complete("rsid1|rep1|2025-01-01|2025-01-02|") is False

    def test_canonical_detection_scoped_to_step(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        body = {"rsid": "rsid1", "report": "rep1"}

        req_id1, c1 = sm.track_request(
            "key1", body, Path("/out/f1.json"), step_id="step_a"
        )
        req_id2, c2 = sm.track_request(
            "key2", body, Path("/out/f2.json"), step_id="step_a"
        )
        # Both same step, same body → second is canonical-linked
        assert c1 is None
        assert c2 == req_id1

    def test_canonical_detection_not_cross_step(self, tmp_path: Path) -> None:
        sm = _make_manager(tmp_path)
        body = {"rsid": "rsid1", "report": "rep1"}

        sm.track_request("key1", body, Path("/out/f1.json"), step_id="step_a")
        _, c2 = sm.track_request("key2", body, Path("/out/f2.json"), step_id="step_b")
        # Different steps → no canonical link across them
        assert c2 is None


# ---------------------------------------------------------------------------
# _resolve_segments helper
# ---------------------------------------------------------------------------


class TestResolveSegments:
    def test_none_returns_none(self) -> None:
        assert _resolve_segments(None, {}) is None

    def test_inline_passthrough(self) -> None:
        result = _resolve_segments({"source": "inline", "ids": ["seg1", "seg2"]}, {})
        assert result is not None
        assert result.source == "inline"
        assert result.ids == ["seg1", "seg2"]

    def test_segment_list_file_passthrough(self) -> None:
        result = _resolve_segments({"source": "segment_list_file", "file": "/data/segs.json"}, {})
        assert result is not None
        assert result.source == "segment_list_file"

    def test_step_output_resolved_to_file(self) -> None:
        step_outputs = {"create_segs": {"segment_list_file": "/data/segs.json"}}
        result = _resolve_segments(
            {"source": "step_output", "step_id": "create_segs", "output_key": "segment_list_file"},
            step_outputs,
        )
        assert result is not None
        assert result.source == "segment_list_file"
        assert result.file == "/data/segs.json"

    def test_step_output_missing_dep_raises(self) -> None:
        with pytest.raises(ValueError, match="not yet produced outputs"):
            _resolve_segments(
                {"source": "step_output", "step_id": "missing_step", "output_key": "x"},
                {},
            )

    def test_step_output_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="key 'bad_key' not found"):
            _resolve_segments(
                {"source": "step_output", "step_id": "step_a", "output_key": "bad_key"},
                {"step_a": {"segment_list_file": "/data/segs.json"}},
            )


# ---------------------------------------------------------------------------
# _coerce_date_range helper
# ---------------------------------------------------------------------------


class TestCoerceDateRange:
    def test_none_returns_none(self) -> None:
        assert _coerce_date_range(None) is None

    def test_date_range_passthrough(self) -> None:
        dr = _date("2025-01-01", "2025-02-01")
        assert _coerce_date_range(dr) is dr

    def test_dict_coerced(self) -> None:
        result = _coerce_date_range({"from": "2025-01-01", "to": "2025-02-01"})
        assert result is not None
        assert result.from_date == "2025-01-01"
        assert result.to == "2025-02-01"


# ---------------------------------------------------------------------------
# _resolve_output_base helper
# ---------------------------------------------------------------------------


class TestResolveOutputBase:
    def test_step_level_override(self) -> None:
        job = _composite_job(output={"base_folder": "/job/out"})
        extra = {"output": {"base_folder": "/step/out"}}
        assert _resolve_output_base(extra, job) == "/step/out"

    def test_falls_back_to_job_output(self) -> None:
        job = _composite_job(output={"base_folder": "/job/out"})
        assert _resolve_output_base({}, job) == "/job/out"

    def test_missing_output_raises(self) -> None:
        job = CompositeJobConfig.model_validate(
            {"job_type": "composite", "client": "X", "steps": []}
        )
        with pytest.raises(ValueError, match="output.base_folder"):
            _resolve_output_base({}, job)


# ---------------------------------------------------------------------------
# run_composite_job: integration with mocked flow functions
# ---------------------------------------------------------------------------


@pytest.fixture()
def _fake_report_defs() -> list[Any]:
    rd = MagicMock()
    rd.name = "botInvestigationMetricsByBrowser"
    return [rd]


async def _make_composite_job_with_download_step(
    tmp_path: Path,
    mock_report_defs: list[Any],
) -> tuple[CompositeJobConfig, Path, StateManager, MagicMock]:
    """Build a minimal composite job with one report_download step."""
    job = CompositeJobConfig.model_validate(
        {
            "job_type": "composite",
            "client": "Legend",
            "output": {"base_folder": str(tmp_path)},
            "date_range": {"from": "2025-01-01", "to": "2025-01-02"},
            "steps": [
                {
                    "step": "report_download",
                    "id": "dl_step",
                    "report_group": "bot_investigation",
                    "rsids": {"source": "single", "single": "rsid1"},
                    "interval": "day",
                }
            ],
        }
    )
    config_path = tmp_path / "job.yaml"
    config_path.write_text("job_type: composite\nclient: Legend\n")
    config_hash = compute_config_hash(config_path)
    job_id = compute_job_id(config_path, config_hash)
    db_path = state_db_path(tmp_path, "Legend", job_id)
    sm = StateManager(db_path, job_id, config_path, config_hash)
    ac = MagicMock()
    return job, config_path, sm, ac


class TestRunCompositeJob:
    async def test_single_report_download_step_completes(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )

        from adobe_downloader.flows.report_download import ReportDownloadResult

        fake_result = ReportDownloadResult(
            job_id=sm.job_id,
            json_folder=tmp_path / "Legend" / "JSON",
            downloaded=2,
        )

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch(
                "adobe_downloader.flows.report_download.run_report_download",
                new_callable=lambda: lambda *a, **kw: _async_return(fake_result),
            ),
        ):
            step_outputs = await run_composite_job(job, config_path, sm, ac)

        assert "dl_step" in step_outputs
        assert step_outputs["dl_step"]["downloaded"] == 2
        assert sm.is_step_complete("dl_step") is True

    async def test_resume_skips_completed_step(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )

        # Pre-mark the step as complete
        sm.mark_step_started("dl_step")
        sm.mark_step_complete("dl_step", {"json_folder": str(tmp_path), "downloaded": 5})

        calls: list[str] = []

        async def _fake_run_rd(*a: Any, **kw: Any) -> Any:
            calls.append("called")
            from adobe_downloader.flows.report_download import ReportDownloadResult
            return ReportDownloadResult(job_id="x", json_folder=tmp_path)

        with patch("adobe_downloader.flows.report_download.run_report_download", _fake_run_rd):
            step_outputs = await run_composite_job(job, config_path, sm, ac, no_resume=False)

        # run_report_download should NOT have been called
        assert calls == []
        assert step_outputs["dl_step"]["downloaded"] == 5

    async def test_no_resume_reruns_completed_step(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )

        sm.mark_step_started("dl_step")
        sm.mark_step_complete("dl_step", {"json_folder": str(tmp_path), "downloaded": 5})

        calls: list[str] = []

        async def _fake_run_rd(*a: Any, **kw: Any) -> Any:
            calls.append("called")
            from adobe_downloader.flows.report_download import ReportDownloadResult
            return ReportDownloadResult(job_id="x", json_folder=tmp_path)

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch("adobe_downloader.flows.report_download.run_report_download", _fake_run_rd),
        ):
            await run_composite_job(job, config_path, sm, ac, no_resume=True)

        assert "called" in calls

    async def test_depends_on_blocks_step_when_dep_not_run(self, tmp_path: Path) -> None:
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path)},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "missing_step",
                        "transform": {"type": "standard"},
                    }
                ],
            }
        )
        config_path = tmp_path / "job.yaml"
        config_path.write_text("job_type: composite\nclient: Legend\n")
        config_hash = compute_config_hash(config_path)
        job_id = compute_job_id(config_path, config_hash)
        db_path = state_db_path(tmp_path, "Legend", job_id)
        sm = StateManager(db_path, job_id, config_path, config_hash)
        ac = MagicMock()

        with pytest.raises(RuntimeError, match="depends_on"):
            await run_composite_job(job, config_path, sm, ac)

    async def test_depends_on_resolved_from_db(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        """depends_on step completed in a prior run — outputs reloaded from DB."""
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path)},
                "date_range": {"from": "2025-01-01", "to": "2025-01-02"},
                "steps": [
                    {
                        "step": "report_download",
                        "id": "dl_step",
                        "report_group": "bot_investigation",
                        "rsids": {"source": "single", "single": "rsid1"},
                        "interval": "day",
                        "depends_on": "prior_step",
                    }
                ],
            }
        )
        config_path = tmp_path / "job.yaml"
        config_path.write_text("job_type: composite\nclient: Legend\n")
        config_hash = compute_config_hash(config_path)
        job_id = compute_job_id(config_path, config_hash)
        db_path = state_db_path(tmp_path, "Legend", job_id)
        sm = StateManager(db_path, job_id, config_path, config_hash)
        ac = MagicMock()

        # Simulate prior_step completed in a previous session
        sm.mark_step_started("prior_step")
        sm.mark_step_complete("prior_step", {"some_output": "value"})

        from adobe_downloader.flows.report_download import ReportDownloadResult

        fake_result = ReportDownloadResult(
            job_id=sm.job_id,
            json_folder=tmp_path / "Legend" / "JSON",
            downloaded=1,
        )

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch(
                "adobe_downloader.flows.report_download.run_report_download",
                new_callable=lambda: lambda *a, **kw: _async_return(fake_result),
            ),
        ):
            step_outputs = await run_composite_job(job, config_path, sm, ac)

        assert "prior_step" in step_outputs
        assert step_outputs["prior_step"]["some_output"] == "value"
        assert sm.is_step_complete("dl_step")

    async def test_failed_step_marks_job_failed(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )

        async def _boom(*a: Any, **kw: Any) -> Any:
            raise RuntimeError("API exploded")

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch("adobe_downloader.flows.report_download.run_report_download", _boom),
            pytest.raises(RuntimeError),
        ):
            await run_composite_job(job, config_path, sm, ac)

        assert sm.is_step_complete("dl_step") is False


# ---------------------------------------------------------------------------
# transform_concat step: source folder auto-detection
# ---------------------------------------------------------------------------


class TestTransformConcatStep:
    async def test_source_folder_auto_detected_from_prior_download(
        self, tmp_path: Path
    ) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        jf = json_folder / "Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-01-02.json"
        jf.write_text("{}")  # content doesn't matter — transform is patched

        step_outputs = {
            "dl_step": {
                "json_folder": str(json_folder),
                "downloaded": 1,
            }
        }

        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path)},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl_step",
                        "transform": {"type": "standard"},
                        "concat": {"enabled": False},
                    }
                ],
            }
        )

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        step_obj = CompositeStep.model_validate(
            {
                "step": "transform_concat",
                "id": "transform",
                "depends_on": "dl_step",
                "transform": {"type": "standard"},
                "concat": {"enabled": False},
            }
        )

        csv_folder = json_folder.parent / "CSV"
        csv_folder.mkdir(parents=True, exist_ok=True)

        def _fake_dispatch(src: Path, output_path: Path | None = None) -> None:
            # Write a dummy CSV so the step sees a successful transform
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("col1,col2\n1,2\n")

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert result["ok"] >= 1
        assert "csv_folder" in result


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _async_return(value: Any) -> Any:
    return value
