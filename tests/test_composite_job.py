"""Tests for composite job runner and step_state StateManager additions."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from adobe_downloader.config.schema import (
    CompositeJobConfig,
    CompositeStep,
    DateRange,
)
from adobe_downloader.flows.composite_job import (
    _coerce_date_range,
    _parse_bot_rules_from_config,
    _resolve_output_base,
    _resolve_rsids,
    _resolve_segments,
    _segment_iterations_from_bot_rules,
    _state_key,
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

        req_id1, c1 = sm.track_request("key1", body, Path("/out/f1.json"), step_id="step_a")
        req_id2, c2 = sm.track_request("key2", body, Path("/out/f2.json"), step_id="step_a")
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
# CompositeJobConfig: duplicate step id validation
# ---------------------------------------------------------------------------


class TestUniqueStepIds:
    def test_duplicate_step_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="Duplicate step id 'transform'"):
            _composite_job(
                steps=[
                    {"step": "transform_concat", "id": "transform", "transform": {}},
                    {"step": "transform_concat", "id": "transform", "transform": {}},
                ]
            )

    def test_distinct_step_ids_accepted(self) -> None:
        job = _composite_job(
            steps=[
                {"step": "transform_concat", "id": "transform_validation", "transform": {}},
                {"step": "transform_concat", "id": "transform_compare", "transform": {}},
            ]
        )
        assert [s.id for s in job.steps] == ["transform_validation", "transform_compare"]


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


class TestResolveRsids:
    def test_file_passthrough(self) -> None:
        result = _resolve_rsids({"source": "file", "file": "/data/rsids.txt"}, {})
        assert result.source == "file"
        assert result.file == "/data/rsids.txt"

    def test_list_passthrough(self) -> None:
        result = _resolve_rsids({"source": "list", "list": ["rsid1", "rsid2"]}, {})
        assert result.source == "list"
        assert result.rsid_list == ["rsid1", "rsid2"]

    def test_step_output_resolved_to_file(self) -> None:
        step_outputs = {
            "update_rsids": {"investigation_list": "/data/rsid_lists/investigation.txt"}
        }
        result = _resolve_rsids(
            {
                "source": "step_output",
                "step_id": "update_rsids",
                "output_key": "investigation_list",
                "batch_size": 20,
            },
            step_outputs,
        )
        assert result.source == "file"
        assert result.file == "/data/rsid_lists/investigation.txt"
        assert result.batch_size == 20

    def test_step_output_defaults_batch_size(self) -> None:
        step_outputs = {
            "update_rsids": {"investigation_list": "/data/rsid_lists/investigation.txt"}
        }
        result = _resolve_rsids(
            {
                "source": "step_output",
                "step_id": "update_rsids",
                "output_key": "investigation_list",
            },
            step_outputs,
        )
        assert result.batch_size == 12

    def test_step_output_missing_dep_raises(self) -> None:
        with pytest.raises(ValueError, match="not yet produced outputs"):
            _resolve_rsids(
                {"source": "step_output", "step_id": "missing_step", "output_key": "x"},
                {},
            )

    def test_step_output_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="key 'bad_key' not found"):
            _resolve_rsids(
                {"source": "step_output", "step_id": "update_rsids", "output_key": "bad_key"},
                {"update_rsids": {"investigation_list": "/data/rsid_lists/investigation.txt"}},
            )


# ---------------------------------------------------------------------------
# _segment_iterations_from_bot_rules helper
# ---------------------------------------------------------------------------


class TestSegmentIterationsFromBotRules:
    def test_one_iteration_per_rule(self) -> None:
        from adobe_downloader.flows.bot_rule_compare import BotRule

        bot_rules = [
            BotRule(segment_id="seg1", segment_name="Rule One", reports_to_skip=[]),
            BotRule(
                segment_id="seg2",
                segment_name="Rule Two",
                reports_to_skip=["botInvestigationMetricsByDomain"],
            ),
        ]
        iterations = _segment_iterations_from_bot_rules(bot_rules)

        assert len(iterations) == 2
        assert iterations[0].ids == ["seg1"]
        assert iterations[0].id == "seg1"
        assert iterations[0].name == "Rule One"
        assert iterations[1].ids == ["seg2"]
        assert iterations[1].name == "Rule Two"

    def test_blank_name_raises(self) -> None:
        from adobe_downloader.flows.bot_rule_compare import BotRule

        bot_rules = [BotRule(segment_id="seg1", segment_name="   ", reports_to_skip=[])]
        with pytest.raises(ValueError, match="blank/missing name"):
            _segment_iterations_from_bot_rules(bot_rules)

    def test_colliding_sanitized_names_raise(self) -> None:
        from adobe_downloader.flows.bot_rule_compare import BotRule

        bot_rules = [
            BotRule(segment_id="seg1", segment_name="Rule/One", reports_to_skip=[]),
            BotRule(segment_id="seg2", segment_name="Rule-One", reports_to_skip=[]),
        ]
        with pytest.raises(ValueError, match="both sanitize to filename component"):
            _segment_iterations_from_bot_rules(bot_rules)


# ---------------------------------------------------------------------------
# _parse_bot_rules_from_config — inline source
# ---------------------------------------------------------------------------


class TestParseBotRulesFromConfigInline:
    def test_scalar_report_to_skip(self) -> None:
        bot_rules = _parse_bot_rules_from_config(
            {
                "source": "inline",
                "rules": [
                    {"segment_id": "s1", "segment_name": "RuleA", "report_to_skip": "Domain"}
                ],
            },
            step_outputs={},
            step_id="step1",
        )
        assert bot_rules[0].reports_to_skip == ["botInvestigationMetricsByDomain"]

    def test_pipe_delimited_report_to_skip(self) -> None:
        bot_rules = _parse_bot_rules_from_config(
            {
                "source": "inline",
                "rules": [
                    {
                        "segment_id": "s1",
                        "segment_name": "RuleA",
                        "report_to_skip": "Domain|OperatingSystem",
                    }
                ],
            },
            step_outputs={},
            step_id="step1",
        )
        assert bot_rules[0].reports_to_skip == [
            "botInvestigationMetricsByDomain",
            "botInvestigationMetricsByOperatingSystem",
        ]

    def test_list_report_to_skip(self) -> None:
        bot_rules = _parse_bot_rules_from_config(
            {
                "source": "inline",
                "rules": [
                    {
                        "segment_id": "s1",
                        "segment_name": "RuleA",
                        "report_to_skip": ["Domain", "OperatingSystem"],
                    }
                ],
            },
            step_outputs={},
            step_id="step1",
        )
        assert bot_rules[0].reports_to_skip == [
            "botInvestigationMetricsByDomain",
            "botInvestigationMetricsByOperatingSystem",
        ]

    def test_missing_report_to_skip_is_empty(self) -> None:
        bot_rules = _parse_bot_rules_from_config(
            {
                "source": "inline",
                "rules": [{"segment_id": "s1", "segment_name": "RuleA"}],
            },
            step_outputs={},
            step_id="step1",
        )
        assert bot_rules[0].reports_to_skip == []


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

    async def test_bot_rules_without_segments_drives_segment_filter(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        """A report_download step with bot_rules but no segments: block should
        still filter/anchor its downloads per rule — bot_validation's whole point
        in dropping the separate segments: field."""
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
                        "report_group": "bot_validation",
                        "rsids": {"source": "single", "single": "rsid1"},
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {"segment_id": "seg1", "segment_name": "Rule One"},
                            ],
                        },
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

        from adobe_downloader.flows.report_download import ReportDownloadResult

        fake_result = ReportDownloadResult(
            job_id=sm.job_id, json_folder=tmp_path / "Legend" / "JSON"
        )
        captured_kwargs: dict[str, Any] = {}

        async def _fake_run_rd(*a: Any, **kw: Any) -> Any:
            captured_kwargs.update(kw)
            return fake_result

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch("adobe_downloader.flows.report_download.run_report_download", _fake_run_rd),
        ):
            await run_composite_job(job, config_path, sm, ac)

        assert captured_kwargs["segments"] is None
        iterations = captured_kwargs["segment_iterations"]
        assert iterations is not None
        assert len(iterations) == 1
        assert iterations[0].ids == ["seg1"]
        assert iterations[0].name == "Rule One"

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
# Partial download failures: a download-bearing step should only hard-fail
# the composite job when no validate_output step is wired (via config_ref) to
# reconcile its output. This mirrors the legacy JS workflow, where a flaky
# download never stopped a separate validate script from mopping up stragglers.
# ---------------------------------------------------------------------------


class TestPartialFailureTolerance:
    async def test_report_download_failure_without_validate_step_raises(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )

        from adobe_downloader.flows.report_download import ReportDownloadResult

        fake_result = ReportDownloadResult(
            job_id=sm.job_id,
            json_folder=tmp_path / "Legend" / "JSON",
            downloaded=1,
            failed=1,
            errors=["rsid1/report: timeout"],
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
            pytest.raises(RuntimeError, match=r"1 download\(s\) failed"),
        ):
            await run_composite_job(job, config_path, sm, ac)

        assert sm.is_step_complete("dl_step") is False

    async def test_report_download_failure_tolerated_when_validate_step_follows(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
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
                    },
                    {
                        "step": "validate_output",
                        "id": "validate",
                        "depends_on": "dl_step",
                        "config_ref": "dl_step",
                    },
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

        from adobe_downloader.flows.report_download import ReportDownloadResult

        fake_result = ReportDownloadResult(
            job_id=sm.job_id,
            json_folder=tmp_path / "Legend" / "JSON",
            downloaded=1,
            failed=1,
            errors=["rsid1/report: timeout"],
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

        # The download step completes despite the failure — it's on record, not fatal.
        assert sm.is_step_complete("dl_step") is True
        assert step_outputs["dl_step"]["failed"] == 1
        # The job proceeds all the way to (and past) the validate step.
        assert "validate" in step_outputs
        assert sm.is_step_complete("validate") is True

    async def test_bot_rule_compare_failure_tolerated_when_validate_step_follows(
        self, tmp_path: Path
    ) -> None:
        rsid_lookup_file = tmp_path / "rsids.txt"
        rsid_lookup_file.write_text("rsid1:Legend")

        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "date_range": {"from": "2025-01-01", "to": "2025-01-02"},
                "steps": [
                    {
                        "step": "bot_rule_compare",
                        "id": "download_compare",
                        "rsids": {"source": "single", "single": "rsid1"},
                        "rsid_lookup_file": str(rsid_lookup_file),
                        "bot_rules": {
                            "source": "inline",
                            "rules": [{"segment_id": "s1", "segment_name": "RuleA"}],
                        },
                    },
                    {
                        "step": "validate_output",
                        "id": "validate",
                        "depends_on": "download_compare",
                        "config_ref": "download_compare",
                    },
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

        from adobe_downloader.flows.bot_rule_compare import BotRuleCompareResult

        fake_result = BotRuleCompareResult(
            job_id=sm.job_id,
            json_folder=tmp_path / "Legend" / "TestJob" / "JSON",
            downloaded=1,
            failed=1,
            errors=["rsid1/RuleA: timeout"],
        )

        with patch(
            "adobe_downloader.flows.bot_rule_compare.run_bot_rule_compare",
            new_callable=lambda: lambda *a, **kw: _async_return(fake_result),
        ):
            step_outputs = await run_composite_job(job, config_path, sm, ac)

        assert sm.is_step_complete("download_compare") is True
        assert step_outputs["download_compare"]["failed"] == 1
        assert "validate" in step_outputs
        assert sm.is_step_complete("validate") is True


# ---------------------------------------------------------------------------
# test_mode / full-run state isolation (regression: a --test run must never
# satisfy a later full run's resume check, or vice versa)
# ---------------------------------------------------------------------------


class TestTestModeStateIsolation:
    async def test_test_mode_run_does_not_block_full_run(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )
        test_job = job.model_copy(update={"test_mode": True})

        from adobe_downloader.flows.report_download import ReportDownloadResult

        calls: list[str] = []

        async def _fake_run_rd(*a: Any, **kw: Any) -> Any:
            calls.append("called")
            return ReportDownloadResult(job_id="x", json_folder=tmp_path, downloaded=1)

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch("adobe_downloader.flows.report_download.run_report_download", _fake_run_rd),
        ):
            # First run: --test mode. The capped download "completes" the step,
            # but only under the test-mode-namespaced key.
            await run_composite_job(test_job, config_path, sm, ac)
            assert calls == ["called"]
            assert sm.is_step_complete("dl_step") is False
            assert sm.is_step_complete(_state_key("dl_step", test_job)) is True

            # Second run: full mode, same sm/config — must NOT be skipped.
            step_outputs = await run_composite_job(job, config_path, sm, ac)

        assert calls == ["called", "called"]
        assert step_outputs["dl_step"]["downloaded"] == 1
        assert sm.is_step_complete("dl_step") is True

    async def test_full_run_completion_unaffected_by_later_test_run(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        job, config_path, sm, ac = await _make_composite_job_with_download_step(
            tmp_path, _fake_report_defs
        )
        test_job = job.model_copy(update={"test_mode": True})

        from adobe_downloader.flows.report_download import ReportDownloadResult

        calls: list[str] = []

        async def _fake_run_rd(*a: Any, **kw: Any) -> Any:
            calls.append("called")
            return ReportDownloadResult(job_id="x", json_folder=tmp_path, downloaded=1)

        with (
            patch(
                "adobe_downloader.flows.composite_job._resolve_report_defs",
                return_value=_fake_report_defs,
            ),
            patch("adobe_downloader.flows.report_download.run_report_download", _fake_run_rd),
        ):
            # Full run completes for real first.
            await run_composite_job(job, config_path, sm, ac)
            assert calls == ["called"]

            # A later --test run must not crash, and must not be silently
            # skipped as if it were the (differently-scoped) full run.
            await run_composite_job(test_job, config_path, sm, ac)

        assert calls == ["called", "called"]
        assert sm.is_step_complete("dl_step") is True

    async def test_depends_on_resolved_from_db_same_mode(
        self, tmp_path: Path, _fake_report_defs: list[Any]
    ) -> None:
        """A test-mode step's depends_on lookup must find a same-mode
        dependency completed in a prior run, via the same namespaced key."""
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path)},
                "date_range": {"from": "2025-01-01", "to": "2025-01-02"},
                "test_mode": True,
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

        # Simulate prior_step completed in a previous *test-mode* run.
        sm.mark_step_started(_state_key("prior_step", job))
        sm.mark_step_complete(_state_key("prior_step", job), {"some_output": "value"})

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
        assert sm.is_step_complete(_state_key("dl_step", job))


# ---------------------------------------------------------------------------
# transform_concat step: source folder auto-detection
# ---------------------------------------------------------------------------


class TestTransformConcatStep:
    async def test_source_folder_auto_detected_from_prior_download(self, tmp_path: Path) -> None:
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
                "transform": {},
                "concat": {"enabled": False},
            }
        )

        csv_folder = json_folder.parent / "CSV"
        csv_folder.mkdir(parents=True, exist_ok=True)

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
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


class TestTransformConcatSplitByBotRule:
    async def test_split_produces_one_file_per_bot_rule(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)

        files = [
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleA-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleA-Compare-V1"
            "-AllTraffic_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleB-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleB-Compare-V1"
            "-AllTraffic_2025-01-01_2025-01-02.json",
        ]
        for name in files:
            (json_folder / name).write_text("{}")

        step_outputs = {"download_compare": {"json_folder": str(json_folder)}}

        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "bot_rule_compare",
                        "id": "download_compare",
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {
                                    "segment_id": "s1",
                                    "segment_name": "RuleA",
                                    "report_to_skip": "Domain",
                                },
                                {
                                    "segment_id": "s2",
                                    "segment_name": "RuleB",
                                    "report_to_skip": "Domain",
                                },
                            ],
                        },
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "download_compare",
                        "transform": {
                            "type": "bot_rule_compare",
                            "source_pattern": ".*Compare-V1.*\\.json$",
                            "split_by_bot_rule": True,
                        },
                        "concat": {"enabled": True},
                    },
                ],
            }
        )
        step_obj = job.steps[1]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"col1\n{src.stem}\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert set(result["concatenated_files"].keys()) == {"RuleA", "RuleB"}
        assert result["concatenated_file"] is None

        rule_a_content = Path(result["concatenated_files"]["RuleA"]).read_text()
        assert "RuleA" in rule_a_content
        assert "RuleB" not in rule_a_content

        rule_b_content = Path(result["concatenated_files"]["RuleB"]).read_text()
        assert "RuleB" in rule_b_content
        assert "RuleA" not in rule_b_content

    async def test_split_resolves_own_download_step_when_job_has_two(self, tmp_path: Path) -> None:
        """A job with both a bot_validation-style download and a bot_rule_compare
        download (e.g. a combined validate+compare job) must resolve each
        transform_concat step's bot rules from *its own* dependency chain, not
        whichever bot_rules-bearing download step happens to be declared first.
        """
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)
        compare_file = (
            json_folder / "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleCompare-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json"
        )
        compare_file.write_text("{}")

        step_outputs = {
            "download_validation": {"json_folder": str(json_folder)},
            "download_compare": {"json_folder": str(json_folder)},
        }
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "report_download",
                        "id": "download_validation",
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {"segment_id": "s1", "segment_name": "RuleValidation"},
                            ],
                        },
                    },
                    {
                        "step": "bot_rule_compare",
                        "id": "download_compare",
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {"segment_id": "s2", "segment_name": "RuleCompare"},
                            ],
                        },
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform_compare",
                        "depends_on": "download_compare",
                        "transform": {
                            "type": "bot_rule_compare",
                            "source_pattern": ".*Compare-V1.*\\.json$",
                            "split_by_bot_rule": True,
                        },
                    },
                ],
            }
        )
        step_obj = job.steps[2]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"col1\n{src.stem}\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        # Must resolve RuleCompare (its own download step), not RuleValidation
        # (the first bot_rules-bearing download step declared in the job).
        assert set(result["concatenated_files"].keys()) == {"RuleCompare"}

    async def test_split_requires_bot_rules_source_in_job(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder
            / "Legend_report_Coverscom-RuleA-Compare-V1-Segment_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        step_outputs = {"dl": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl",
                        "transform": {
                            "type": "bot_rule_compare",
                            "source_pattern": ".*Compare-V1.*\\.json$",
                            "split_by_bot_rule": True,
                        },
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("col1\nrow\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with (
            patch(
                "adobe_downloader.transforms.specialized.transform_report_dispatch",
                side_effect=_fake_dispatch,
            ),
            pytest.raises(ValueError, match="split_by_bot_rule requires"),
        ):
            await _run_transform_concat_step(step_obj, job, step_outputs)

    async def test_split_anchors_match_to_avoid_prefix_collision(self, tmp_path: Path) -> None:
        """ "RuleA" must not match inside "RuleA2"'s filename (substring-match regression)."""
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)

        files = [
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleA-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleA2-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json",
        ]
        for name in files:
            (json_folder / name).write_text("{}")

        step_outputs = {"download_compare": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "bot_rule_compare",
                        "id": "download_compare",
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {
                                    "segment_id": "s1",
                                    "segment_name": "RuleA",
                                    "report_to_skip": "Domain",
                                },
                                {
                                    "segment_id": "s2",
                                    "segment_name": "RuleA2",
                                    "report_to_skip": "Domain",
                                },
                            ],
                        },
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "download_compare",
                        "transform": {
                            "type": "bot_rule_compare",
                            "source_pattern": ".*Compare-V1.*\\.json$",
                            "split_by_bot_rule": True,
                        },
                        "concat": {"enabled": True},
                    },
                ],
            }
        )
        step_obj = job.steps[1]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"col1\n{src.stem}\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        rule_a_content = Path(result["concatenated_files"]["RuleA"]).read_text()
        assert "RuleA2" not in rule_a_content

        rule_a2_content = Path(result["concatenated_files"]["RuleA2"]).read_text()
        assert "RuleA2" in rule_a2_content

    async def test_split_matches_report_download_rule_anchor_scheme(self, tmp_path: Path) -> None:
        """split_by_bot_rule also matches bot_validation-style RULE{name}-anchored files."""
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)

        files = [
            "Legend_botFilterExcludeMetricsByMonth_trillioncoverscom_RULEUS-Mobile-Bots"
            "_2025-01-01_2025-01-02.json",
            "Legend_botFilterExcludeMetricsByMonth_trillioncoverscom_RULECA-Desktop-Bots"
            "_2025-01-01_2025-01-02.json",
        ]
        for name in files:
            (json_folder / name).write_text("{}")

        step_outputs = {"download_validation": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "report_download",
                        "id": "download_validation",
                        "report_group": "bot_validation",
                        "rsids": {"source": "single", "single": "rsid1"},
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {
                                    "segment_id": "s1",
                                    "segment_name": "US_Mobile_Bots",
                                    "report_to_skip": "Domain",
                                },
                                {
                                    "segment_id": "s2",
                                    "segment_name": "CA_Desktop_Bots",
                                    "report_to_skip": "Domain",
                                },
                            ],
                        },
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "download_validation",
                        "transform": {"type": "bot_validation", "split_by_bot_rule": True},
                        "concat": {"enabled": True},
                    },
                ],
            }
        )
        step_obj = job.steps[1]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"col1\n{src.stem}\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert set(result["concatenated_files"].keys()) == {"US_Mobile_Bots", "CA_Desktop_Bots"}

        us_content = Path(result["concatenated_files"]["US_Mobile_Bots"]).read_text()
        assert "RULEUS-Mobile-Bots" in us_content
        assert "CA-Desktop-Bots" not in us_content


class TestTransformConcatCustomHeaders:
    async def test_custom_headers_applied_on_composite_path(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder / "Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl_step",
                        "transform": {"type": "bot_investigation"},
                        "concat": {"enabled": True, "custom_headers": {1: "feature"}},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("id,browser\n1,Chrome\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        content = Path(result["concatenated_file"]).read_text()
        assert content.splitlines()[0] == "id,feature"


class TestTransformConcatSharedFolder:
    async def test_concat_ignores_other_steps_files_in_shared_folder(self, tmp_path: Path) -> None:
        # Simulates two report_download steps sharing one output.job_name and
        # therefore the same JSON/CSV folders (e.g. a Daily + a Totals download).
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder / "Legend_botInvestigationMetricsByBrowser_Daily_2025-01-01_2025-01-02.json"
        ).write_text("{}")
        (
            json_folder
            / "Legend_botInvestigationMetricsByBrowser_Totals_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        # A CSV already sitting in the shared CSV folder from the sibling Totals step.
        csv_folder = json_folder.parent / "CSV"
        csv_folder.mkdir(parents=True)
        (
            csv_folder / "Legend_botInvestigationMetricsByBrowser_Totals_2025-01-01_2025-01-02.csv"
        ).write_text("id,browser\nTOTALS_ROW,x\n")

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform_daily",
                        "depends_on": "dl_step",
                        "transform": {
                            "type": "bot_investigation",
                            "source_pattern": "*Daily*.json",
                        },
                        "concat": {"enabled": True, "file_name_extra": "Daily"},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        def _fake_dispatch(
            src: Path,
            transform_type: str | None = None,
            headers_dir: object = None,
            *,
            output_path: Path | None = None,
        ) -> None:
            p = output_path or src.with_suffix(".csv")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"id,browser\n{src.stem}\n")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=_fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        content = Path(result["concatenated_file"]).read_text()
        assert "TOTALS_ROW" not in content
        assert "Daily" in content


class TestTransformConcatSplitByRsid:
    @staticmethod
    def _fake_dispatch(
        src: Path,
        transform_type: str | None = None,
        headers_dir: object = None,
        *,
        output_path: Path | None = None,
    ) -> None:
        p = output_path or src.with_suffix(".csv")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"id,browser\n{src.stem}\n")

    async def test_split_produces_one_file_per_rsid_from_correct_download_step(
        self, tmp_path: Path
    ) -> None:
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)

        files = [
            "Legend_botInvestigationMetricsByBrowser_SiteA_Daily_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_SiteB_Daily_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_SiteC_Totals_2025-01-01_2025-01-02.json",
        ]
        for name in files:
            (json_folder / name).write_text("{}")

        step_outputs = {
            "download_daily": {"json_folder": str(json_folder)},
            "download_totals": {"json_folder": str(json_folder)},
        }

        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "report_download",
                        "id": "download_daily",
                        "report_group": "bot_investigation",
                        "rsids": {"source": "list", "list": ["SiteA", "SiteB"]},
                        "interval": "day",
                        "file_name_extra": "Daily",
                    },
                    {
                        "step": "report_download",
                        "id": "download_totals",
                        "report_group": "bot_investigation",
                        "rsids": {"source": "list", "list": ["SiteC"]},
                        "interval": "full",
                        "file_name_extra": "Totals",
                    },
                    {
                        "step": "validate_output",
                        "id": "validate_daily",
                        "depends_on": "download_daily",
                        "config_ref": "download_daily",
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform_daily",
                        "depends_on": "validate_daily",
                        "transform": {
                            "type": "bot_investigation",
                            "source_pattern": "*Daily*.json",
                            "split_by_rsid": True,
                        },
                        "concat": {"enabled": True, "file_name_extra": "Daily"},
                    },
                ],
            }
        )
        step_obj = next(s for s in job.steps if s.id == "transform_daily")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert set(result["concatenated_files"].keys()) == {"SiteA", "SiteB"}
        assert result["concatenated_file"] is None

        site_a_content = Path(result["concatenated_files"]["SiteA"]).read_text()
        assert "SiteA" in site_a_content
        assert "SiteB" not in site_a_content
        assert "SiteC" not in site_a_content

    async def test_split_by_rsid_requires_report_download_step(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)
        (json_folder / "Legend_report_2025-01-01_2025-01-02.json").write_text("{}")

        step_outputs = {"dl": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl",
                        "transform": {"type": "bot_investigation", "split_by_rsid": True},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with (
            patch(
                "adobe_downloader.transforms.specialized.transform_report_dispatch",
                side_effect=self._fake_dispatch,
            ),
            pytest.raises(ValueError, match="split_by_rsid requires"),
        ):
            await _run_transform_concat_step(step_obj, job, step_outputs)


class TestTransformConcatSplitByRsidCountry:
    @staticmethod
    def _fake_dispatch(
        src: Path,
        transform_type: str | None = None,
        headers_dir: object = None,
        *,
        output_path: Path | None = None,
    ) -> None:
        p = output_path or src.with_suffix(".csv")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"id,browser\n{src.stem}\n")

    async def test_split_produces_one_file_per_rsid_country_pair(self, tmp_path: Path) -> None:
        from adobe_downloader.flows.country_matrix import RsidCountryPair, write_matrix_file

        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)

        files = [
            "Legend_botInvestigationMetricsByBrowser_SiteA-United-Kingdom-FullRun-V1-Daily_"
            "DIMSEGseg-uk_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_SiteB-France-FullRun-V1-Daily_"
            "DIMSEGseg-fr_2025-01-01_2025-01-02.json",
        ]
        for name in files:
            (json_folder / name).write_text("{}")

        matrix_file = tmp_path / "matrix.json"
        write_matrix_file(
            matrix_file,
            [
                RsidCountryPair("SiteA", "United Kingdom", "seg-uk", 500),
                RsidCountryPair("SiteB", "France", "seg-fr", 300),
            ],
        )

        step_outputs = {"download_daily": {"json_folder": str(json_folder)}}

        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "country_investigation",
                        "id": "download_daily",
                        "matrix": {"source": "file", "file": str(matrix_file)},
                        "interval": "day",
                        "file_name_extra": "Daily",
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform_daily",
                        "depends_on": "download_daily",
                        "transform": {
                            "type": "bot_investigation",
                            "source_pattern": "*Daily*.json",
                            "split_by_rsid_country": True,
                        },
                        "concat": {"enabled": True, "file_name_extra": "Daily"},
                    },
                ],
            }
        )
        step_obj = next(s for s in job.steps if s.id == "transform_daily")

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert set(result["concatenated_files"].keys()) == {
            "SiteA-United Kingdom",
            "SiteB-France",
        }

        site_a_content = Path(result["concatenated_files"]["SiteA-United Kingdom"]).read_text()
        assert "SiteA-United-Kingdom" in site_a_content
        assert "SiteB-France" not in site_a_content

    async def test_split_by_rsid_country_requires_country_investigation_step(
        self, tmp_path: Path
    ) -> None:
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)
        (json_folder / "Legend_report_2025-01-01_2025-01-02.json").write_text("{}")

        step_outputs = {"dl": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl",
                        "transform": {"type": "bot_investigation", "split_by_rsid_country": True},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with (
            patch(
                "adobe_downloader.transforms.specialized.transform_report_dispatch",
                side_effect=self._fake_dispatch,
            ),
            pytest.raises(ValueError, match="split_by_rsid_country requires"),
        ):
            await _run_transform_concat_step(step_obj, job, step_outputs)


class TestGenerateCountryMatrixAndCountryInvestigationSteps:
    async def test_matrix_step_output_flows_into_country_investigation_step(
        self, tmp_path: Path
    ) -> None:
        from adobe_downloader.flows.country_investigation import CountryInvestigationResult
        from adobe_downloader.flows.country_matrix import CountryMatrixResult, RsidCountryPair

        rsid_file = tmp_path / "rsids.txt"
        rsid_file.write_text("rsid1:CasinoOrg")

        job = _composite_job(
            client="Legend",
            output={"base_folder": str(tmp_path), "job_name": "TestJob"},
            date_range={"from": "2026-01-01", "to": "2026-03-31"},
            steps=[
                {
                    "step": "generate_country_matrix",
                    "id": "matrix",
                    "rsids": {"source": "list", "list": ["CasinoOrg"]},
                    "visit_threshold": 100000,
                    "rsid_lookup_file": str(rsid_file),
                },
                {
                    "step": "country_investigation",
                    "id": "download",
                    "depends_on": "matrix",
                    "matrix": {
                        "source": "step_output",
                        "step_id": "matrix",
                        "output_key": "matrix_file",
                    },
                    "interval": "full",
                    "investigation_label": "FullRun-V1",
                    "rsid_lookup_file": str(rsid_file),
                },
            ],
        )
        config_path = tmp_path / "job.yaml"
        config_path.write_text("job_type: composite\nclient: Legend\n")
        config_hash = compute_config_hash(config_path)
        job_id = compute_job_id(config_path, config_hash)
        db_path = state_db_path(tmp_path, "Legend", job_id)
        sm = StateManager(db_path, job_id, config_path, config_hash)
        ac = MagicMock()

        matrix_path = tmp_path / "matrix.json"
        matrix_result = CountryMatrixResult(
            job_id=sm.job_id,
            matrix_file=matrix_path,
            pairs=[RsidCountryPair("CasinoOrg", "United Kingdom", "seg_uk", 500000)],
            segments_created=1,
        )
        investigation_result = CountryInvestigationResult(
            job_id=sm.job_id,
            json_folder=tmp_path / "Legend" / "TestJob" / "JSON",
            downloaded=1,
        )

        captured_kwargs: dict[str, Any] = {}

        async def _fake_matrix(*a: Any, **kw: Any) -> Any:
            return matrix_result

        async def _fake_investigation(*a: Any, **kw: Any) -> Any:
            captured_kwargs.update(kw)
            return investigation_result

        with (
            patch(
                "adobe_downloader.flows.country_matrix.run_generate_country_matrix",
                _fake_matrix,
            ),
            patch(
                "adobe_downloader.flows.country_investigation.run_country_investigation",
                _fake_investigation,
            ),
        ):
            step_outputs = await run_composite_job(job, config_path, sm, ac)

        assert step_outputs["matrix"]["matrix_file"] == str(matrix_path)
        assert step_outputs["matrix"]["pair_count"] == 1
        assert step_outputs["matrix"]["segments_created"] == 1

        # The country_investigation step must resolve matrix.step_output to the
        # exact path generate_country_matrix produced.
        assert captured_kwargs["matrix_file"] == matrix_path
        assert step_outputs["download"]["downloaded"] == 1


class TestTransformConcatFileNameExtra:
    @staticmethod
    def _fake_dispatch(
        src: Path,
        transform_type: str | None = None,
        headers_dir: object = None,
        *,
        output_path: Path | None = None,
    ) -> None:
        p = output_path or src.with_suffix(".csv")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("col1,col2\n1,2\n")

    async def test_non_split_baseline_filename_unchanged_when_unset(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder / "Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl_step",
                        "transform": {"type": "bot_investigation"},
                        "concat": {"enabled": True},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert Path(result["concatenated_file"]).name == "INVESTIGATION_TestJob.csv"

    async def test_non_split_appends_file_name_extra_after_job_name(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder / "Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl_step",
                        "transform": {"type": "bot_investigation"},
                        "concat": {"enabled": True, "file_name_extra": "MyLabel"},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert Path(result["concatenated_file"]).name == "INVESTIGATION_TestJob_MyLabel.csv"

    async def test_split_appends_file_name_extra_before_rule_name(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "TestJob" / "JSON"
        json_folder.mkdir(parents=True)

        files = [
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleA-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json",
            "Legend_botInvestigationMetricsByBrowser_Coverscom-RuleB-Compare-V1"
            "-Segment_2025-01-01_2025-01-02.json",
        ]
        for name in files:
            (json_folder / name).write_text("{}")

        step_outputs = {"download_compare": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "bot_rule_compare",
                        "id": "download_compare",
                        "bot_rules": {
                            "source": "inline",
                            "rules": [
                                {
                                    "segment_id": "s1",
                                    "segment_name": "RuleA",
                                    "report_to_skip": "Domain",
                                },
                                {
                                    "segment_id": "s2",
                                    "segment_name": "RuleB",
                                    "report_to_skip": "Domain",
                                },
                            ],
                        },
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "download_compare",
                        "transform": {
                            "type": "bot_rule_compare",
                            "source_pattern": ".*Compare-V1.*\\.json$",
                            "split_by_bot_rule": True,
                        },
                        "concat": {"enabled": True, "file_name_extra": "V4"},
                    },
                ],
            }
        )
        step_obj = job.steps[1]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert Path(result["concatenated_files"]["RuleA"]).name == "COMPARE_TestJob_V4_RuleA.csv"
        assert Path(result["concatenated_files"]["RuleB"]).name == "COMPARE_TestJob_V4_RuleB.csv"

    async def test_fallback_no_job_name_appends_file_name_extra(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        (json_folder / "Legend_report_2025-01-01_2025-01-02.json").write_text("{}")

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
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
                        "concat": {"enabled": True, "file_name_extra": "MyLabel"},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert Path(result["concatenated_file"]).name == "transform_MyLabel_concat.csv"

    async def test_file_name_extra_sanitizes_illegal_windows_chars(self, tmp_path: Path) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder / "Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl_step",
                        "transform": {"type": "bot_investigation"},
                        "concat": {"enabled": True, "file_name_extra": "A/B:C*D"},
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert Path(result["concatenated_file"]).name == "INVESTIGATION_TestJob_A-B-C-D.csv"

    @pytest.mark.parametrize("file_name_extra_value", ["", "   ", None])
    async def test_file_name_extra_blank_and_whitespace_treated_as_unset(
        self, tmp_path: Path, file_name_extra_value: str | None
    ) -> None:
        json_folder = tmp_path / "Legend" / "JSON"
        json_folder.mkdir(parents=True)
        (
            json_folder / "Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-01-02.json"
        ).write_text("{}")

        concat_block: dict[str, Any] = {"enabled": True}
        if file_name_extra_value is not None:
            concat_block["file_name_extra"] = file_name_extra_value

        step_outputs = {"dl_step": {"json_folder": str(json_folder)}}
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": str(tmp_path), "job_name": "TestJob"},
                "steps": [
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "dl_step",
                        "transform": {"type": "bot_investigation"},
                        "concat": concat_block,
                    }
                ],
            }
        )
        step_obj = job.steps[0]

        from adobe_downloader.flows.composite_job import _run_transform_concat_step

        with patch(
            "adobe_downloader.transforms.specialized.transform_report_dispatch",
            side_effect=self._fake_dispatch,
        ):
            result = await _run_transform_concat_step(step_obj, job, step_outputs)

        assert Path(result["concatenated_file"]).name == "INVESTIGATION_TestJob.csv"


# ---------------------------------------------------------------------------
# Async helper
# ---------------------------------------------------------------------------


async def _async_return(value: Any) -> Any:
    return value
