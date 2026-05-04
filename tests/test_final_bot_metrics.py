"""Tests for flows/final_bot_metrics.py and composite final_bot_metrics step."""

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
)
from adobe_downloader.flows.final_bot_metrics import (
    FinalBotMetricsResult,
    SegmentEntry,
    _PER_SEGMENT_REPORTS,
    load_segment_list_with_names,
    run_final_bot_metrics,
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
    sm = StateManager(db_path, job_id, config_file, config_hash)
    sm.mark_job_started()
    return sm


def _date(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


def _make_rsid_file(tmp_path: Path, entries: list[tuple[str, str]]) -> Path:
    p = tmp_path / "rsids.txt"
    p.write_text("\n".join(f"{rsid}:{name}" for rsid, name in entries))
    return p


def _make_segment_list(tmp_path: Path, segments: list[dict]) -> Path:
    p = tmp_path / "segments.json"
    p.write_text(json.dumps(segments))
    return p


_FAKE_REPORT_RESPONSE = {"rows": [], "summaryData": {"totals": []}}


def _patch_build_request():
    return patch(
        "adobe_downloader.core.request_builder.build_request",
        return_value={"rsuite": "test", "globalFilters": []},
    )


# ---------------------------------------------------------------------------
# load_segment_list_with_names
# ---------------------------------------------------------------------------


class TestLoadSegmentListWithNames:
    def test_parses_compatability_prefix_format(self, tmp_path: Path) -> None:
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg001", "name": "CompatabilityPrefix=0073-Bot-Rule-Google"},
            {"id": "seg002", "name": "CompatabilityPrefix=0074-Bot-Rule-Bing"},
        ])
        entries = load_segment_list_with_names(seg_file)
        assert len(entries) == 2
        assert entries[0].id == "seg001"
        assert entries[0].suffix == "0073-Bot-Rule-Google"
        assert entries[1].suffix == "0074-Bot-Rule-Bing"

    def test_suffix_spaces_replaced_with_hyphens(self, tmp_path: Path) -> None:
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg001", "name": "Prefix=Bot Rule With Spaces"},
        ])
        entries = load_segment_list_with_names(seg_file)
        assert entries[0].suffix == "Bot-Rule-With-Spaces"

    def test_no_equals_uses_full_name(self, tmp_path: Path) -> None:
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg001", "name": "PlainSegmentName"},
        ])
        entries = load_segment_list_with_names(seg_file)
        assert entries[0].suffix == "PlainSegmentName"

    def test_leading_whitespace_stripped_from_suffix(self, tmp_path: Path) -> None:
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg001", "name": "Prefix= SuffixWithLeadingSpace"},
        ])
        entries = load_segment_list_with_names(seg_file)
        assert entries[0].suffix == "SuffixWithLeadingSpace"

    def test_empty_list(self, tmp_path: Path) -> None:
        seg_file = _make_segment_list(tmp_path, [])
        entries = load_segment_list_with_names(seg_file)
        assert entries == []


# ---------------------------------------------------------------------------
# Per-segment vs aggregate report classification
# ---------------------------------------------------------------------------


class TestPerSegmentReports:
    def test_unfiltered_is_per_segment(self) -> None:
        assert "LegendFinalBotMetricsUnfilteredVisitsByYear" in _PER_SEGMENT_REPORTS

    def test_current_include_is_not_per_segment(self) -> None:
        assert "LegendFinalBotMetricsCurrentIncludeByYear" not in _PER_SEGMENT_REPORTS

    def test_development_include_is_not_per_segment(self) -> None:
        assert "LegendFinalBotMetricsDevelopmentIncludeByYear" not in _PER_SEGMENT_REPORTS


# ---------------------------------------------------------------------------
# run_final_bot_metrics — unit tests with mocked client and StateManager
# ---------------------------------------------------------------------------


class TestRunFinalBotMetrics:
    async def test_per_segment_report_downloads_per_segment(self, tmp_path: Path) -> None:
        """Unfiltered report must be downloaded once per segment."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "SiteA")])
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg1", "name": "P=Rule1"},
            {"id": "seg2", "name": "P=Rule2"},
        ])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd_unfiltered = MagicMock()
        rd_unfiltered.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd_unfiltered.segments = []

        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "segments": segments}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd_unfiltered]

            result = await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="SiteA"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # 1 RSID × 2 segments = 2 downloads (each segment produces a distinct request body)
        assert client.get_report.call_count == 2
        assert result.downloaded == 2
        assert result.failed == 0

    async def test_aggregate_report_downloads_once_per_rsid(self, tmp_path: Path) -> None:
        """Current/Development Include reports must NOT iterate per segment."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "SiteA")])
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg1", "name": "P=Rule1"},
            {"id": "seg2", "name": "P=Rule2"},
            {"id": "seg3", "name": "P=Rule3"},
        ])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd_current = MagicMock()
        rd_current.name = "LegendFinalBotMetricsCurrentIncludeByYear"
        rd_current.segments = ["s3938_fixed"]

        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "segments": segments}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd_current]

            result = await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="SiteA"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # 1 RSID × 1 report (not per segment) = 1 download despite 3 segments
        assert client.get_report.call_count == 1
        assert result.downloaded == 1

    async def test_mixed_reports_correct_download_counts(self, tmp_path: Path) -> None:
        """1 Unfiltered (per segment) + 2 aggregate = N_segs + 2 downloads per RSID."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "SiteA")])
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg1", "name": "P=Rule1"},
            {"id": "seg2", "name": "P=Rule2"},
        ])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd_unfiltered = MagicMock()
        rd_unfiltered.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd_unfiltered.segments = []
        rd_current = MagicMock()
        rd_current.name = "LegendFinalBotMetricsCurrentIncludeByYear"
        rd_current.segments = ["s3938_current"]
        rd_dev = MagicMock()
        rd_dev.name = "LegendFinalBotMetricsDevelopmentIncludeByYear"
        rd_dev.segments = ["s3938_dev"]

        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "report": report_def.name, "segments": segments}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd_unfiltered, rd_current, rd_dev]

            result = await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="SiteA"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # Unfiltered: 2 segments = 2 downloads
        # Current: 1 download
        # Development: 1 download
        assert client.get_report.call_count == 4
        assert result.downloaded == 4
        assert result.failed == 0

    async def test_multiple_rsids(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [
            ("triarsid1", "SiteA"),
            ("triarsid2", "SiteB"),
            ("triarsid3", "SiteC"),
        ])
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg1", "name": "P=Rule1"},
        ])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd_unfiltered = MagicMock()
        rd_unfiltered.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd_unfiltered.segments = []

        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "segments": segments}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd_unfiltered]

            result = await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="list", rsid_list=["SiteA", "SiteB", "SiteC"]),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # 3 RSIDs × 1 segment = 3 downloads
        assert client.get_report.call_count == 3
        assert result.downloaded == 3

    async def test_unknown_rsid_skipped(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "KnownSite")])
        seg_file = _make_segment_list(tmp_path, [{"id": "seg1", "name": "P=Rule1"}])
        sm = _make_manager(tmp_path)
        client = AsyncMock()

        rd = MagicMock()
        rd.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd.segments = []

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             _patch_build_request():
            mock_load.return_value = [rd]

            result = await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="list", rsid_list=["UnknownSite"]),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        assert client.get_report.call_count == 0
        assert result.failed == 1
        assert "UnknownSite" in result.errors[0]

    async def test_resume_skips_completed(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "SiteA")])
        seg_file = _make_segment_list(tmp_path, [{"id": "seg1", "name": "P=Rule1"}])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd = MagicMock()
        rd.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd.segments = []

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             _patch_build_request():
            mock_load.return_value = [rd]

            kwargs = dict(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="SiteA"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
            )

            await run_final_bot_metrics(**kwargs, no_resume=True)
            first_count = client.get_report.call_count

            result2 = await run_final_bot_metrics(**kwargs, no_resume=False)

        assert client.get_report.call_count == first_count
        assert result2.skipped == 1
        assert result2.downloaded == 0

    async def test_download_failure_recorded(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "SiteA")])
        seg_file = _make_segment_list(tmp_path, [{"id": "seg1", "name": "P=Rule1"}])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(side_effect=RuntimeError("API error"))

        rd = MagicMock()
        rd.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd.segments = []

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             _patch_build_request():
            mock_load.return_value = [rd]

            result = await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="SiteA"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="TestJob",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        assert result.failed == 1
        assert "API error" in result.errors[0]

    async def test_unfiltered_filename_contains_job_clean_name_suffix(self, tmp_path: Path) -> None:
        """Unfiltered filename must encode jobName_cleanName_segSuffix for transform."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "Coverscom")])
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg1", "name": "CompatabilityPrefix=0073-Bot-Rule-Google"},
        ])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd = MagicMock()
        rd.name = "LegendFinalBotMetricsUnfilteredVisitsByYear"
        rd.segments = []

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             _patch_build_request():
            mock_load.return_value = [rd]

            await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="Coverscom"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="FinalBotRuleMetrics-Apr25",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        json_dir = tmp_path / "output" / "Legend" / "JSON"
        names = [f.name for f in json_dir.glob("*.json")]
        assert len(names) == 1
        # Filename must contain job_name, clean_name, and seg_suffix
        assert "FinalBotRuleMetrics-Apr25" in names[0]
        assert "Coverscom" in names[0]
        assert "0073-Bot-Rule-Google" in names[0]
        # Must NOT contain DIMSEG
        assert "DIMSEG" not in names[0]

    async def test_aggregate_filename_contains_only_job_name(self, tmp_path: Path) -> None:
        """Aggregate (Current/Development) filenames contain only job_name as extra."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "Coverscom")])
        seg_file = _make_segment_list(tmp_path, [
            {"id": "seg1", "name": "P=Rule1"},
            {"id": "seg2", "name": "P=Rule2"},
        ])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd_current = MagicMock()
        rd_current.name = "LegendFinalBotMetricsCurrentIncludeByYear"
        rd_current.segments = ["s3938_fixed"]

        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "segments": segments}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd_current]

            await run_final_bot_metrics(
                client=client,
                client_name="Legend",
                rsids=MagicMock(source="single", single="Coverscom"),
                rsid_lookup_file=rsid_file,
                segment_list_file=seg_file,
                job_name="Apr25Totals",
                date_range=_date("2025-01-01", "2025-12-31"),
                interval="full",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        json_dir = tmp_path / "output" / "Legend" / "JSON"
        names = [f.name for f in json_dir.glob("*.json")]
        # Only 1 file despite 2 segments (aggregate report is not per-segment)
        assert len(names) == 1
        assert "Apr25Totals" in names[0]
        assert "Rule1" not in names[0]
        assert "Rule2" not in names[0]


# ---------------------------------------------------------------------------
# Schema: final_bot_metrics step type
# ---------------------------------------------------------------------------


class TestFinalBotMetricsSchema:
    def test_step_type_accepted(self) -> None:
        step = CompositeStep.model_validate({
            "step": "final_bot_metrics",
            "id": "download_final",
        })
        assert step.step == "final_bot_metrics"

    def test_composite_job_with_final_bot_metrics_step(self) -> None:
        job = CompositeJobConfig.model_validate({
            "job_type": "composite",
            "client": "Legend",
            "output": {"base_folder": "/tmp/out"},
            "steps": [
                {
                    "step": "final_bot_metrics",
                    "id": "download_final",
                    "job_name": "FinalBotRuleMetrics-Apr25",
                    "rsids": {"source": "list", "list": ["SiteA", "SiteB", "SiteC"]},
                    "segment_list_file": "data/segment_lists/Legend/Apr25ValidatedList.json",
                    "interval": "full",
                }
            ],
        })
        assert job.steps[0].step == "final_bot_metrics"


# ---------------------------------------------------------------------------
# Report definitions: final_bot_metrics group
# ---------------------------------------------------------------------------


class TestFinalBotMetricsReportDefs:
    def test_group_loads_three_reports(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("final_bot_metrics")
        assert len(reports) == 3

    def test_unfiltered_has_no_fixed_segments(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("final_bot_metrics")
        unfiltered = next(r for r in reports if "Unfiltered" in r.name)
        assert unfiltered.segments == []

    def test_current_and_development_have_fixed_segments(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("final_bot_metrics")
        current = next(r for r in reports if "Current" in r.name)
        dev = next(r for r in reports if "Development" in r.name)
        assert len(current.segments) > 0
        assert len(dev.segments) > 0

    def test_all_expected_report_names_present(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("final_bot_metrics")
        names = {r.name for r in reports}
        expected = {
            "LegendFinalBotMetricsUnfilteredVisitsByYear",
            "LegendFinalBotMetricsCurrentIncludeByYear",
            "LegendFinalBotMetricsDevelopmentIncludeByYear",
        }
        assert names == expected
