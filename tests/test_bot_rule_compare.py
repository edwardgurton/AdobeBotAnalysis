"""Tests for flows/bot_rule_compare.py and composite bot_rule_compare step."""

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
from adobe_downloader.flows.bot_rule_compare import (
    DIMENSION_MAPPING,
    BotRule,
    BotRuleCompareResult,
    parse_bot_rule_csv,
    run_bot_rule_compare,
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
    """Write rsid:CleanName lookup file and return its path."""
    p = tmp_path / "rsids.txt"
    p.write_text("\n".join(f"{rsid}:{name}" for rsid, name in entries))
    return p


def _csv_content(rows: list[dict[str, str]]) -> str:
    headers = "DimSegmentId,botRuleName,reportToIgnore"
    lines = [headers] + [
        f"{r['DimSegmentId']},{r['botRuleName']},{r['reportToIgnore']}" for r in rows
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# parse_bot_rule_csv
# ---------------------------------------------------------------------------


class TestParseBotRuleCsv:
    def test_basic_parse(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_text(
            "DimSegmentId,botRuleName,reportToIgnore\n"
            "seg123,Philippines-Rule,Domain\n"
        )
        rules = parse_bot_rule_csv(csv)
        assert len(rules) == 1
        assert rules[0].segment_id == "seg123"
        assert rules[0].segment_name == "Philippines-Rule"
        assert rules[0].report_to_skip == "botInvestigationMetricsByDomain"

    def test_short_name_mapping(self, tmp_path: Path) -> None:
        short_names = [
            ("UserAgent", "botInvestigationMetricsByUserAgent"),
            ("Region", "botInvestigationMetricsByRegion"),
            ("BrowserType", "botInvestigationMetricsByBrowserType"),
            ("OperatingSystem", "botInvestigationMetricsByOperatingSystem"),
            ("Operating System", "botInvestigationMetricsByOperatingSystem"),
            ("MarketingChannel", "botInvestigationMetricsByMarketingChannel"),
            ("ReferringDomain", "botInvestigationMetricsByMarketingChannel"),
        ]
        for short, expected_full in short_names:
            csv = tmp_path / f"rules_{short.replace(' ', '_')}.csv"
            csv.write_text(
                f"DimSegmentId,botRuleName,reportToIgnore\nseg1,Rule1,{short}\n"
            )
            rules = parse_bot_rule_csv(csv)
            assert rules[0].report_to_skip == expected_full, f"failed for {short}"

    def test_full_report_name_passthrough(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_text(
            "DimSegmentId,botRuleName,reportToIgnore\n"
            "seg1,Rule1,botInvestigationMetricsByHourOfDay\n"
        )
        rules = parse_bot_rule_csv(csv)
        assert rules[0].report_to_skip == "botInvestigationMetricsByHourOfDay"

    def test_multiple_rows(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_text(
            "DimSegmentId,botRuleName,reportToIgnore\n"
            "seg1,Rule1,Domain\n"
            "seg2,Rule2,UserAgent\n"
            "seg3,Rule3,Region\n"
        )
        rules = parse_bot_rule_csv(csv)
        assert len(rules) == 3
        assert rules[1].segment_id == "seg2"

    def test_bom_handled(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_bytes(
            b"\xef\xbb\xbfDimSegmentId,botRuleName,reportToIgnore\nseg1,Rule1,Domain\n"
        )
        rules = parse_bot_rule_csv(csv)
        assert rules[0].segment_id == "seg1"

    def test_missing_column_raises(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_text("SegId,Name\nseg1,Rule1\n")
        with pytest.raises(ValueError, match="DimSegmentId"):
            parse_bot_rule_csv(csv)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_text("DimSegmentId,botRuleName,reportToIgnore\n")
        with pytest.raises(ValueError, match="header row"):
            parse_bot_rule_csv(csv)

    def test_unknown_short_name_fallback(self, tmp_path: Path) -> None:
        csv = tmp_path / "rules.csv"
        csv.write_text(
            "DimSegmentId,botRuleName,reportToIgnore\nseg1,Rule1,SomeDimension\n"
        )
        rules = parse_bot_rule_csv(csv)
        assert rules[0].report_to_skip == "botInvestigationMetricsBySomeDimension"


# ---------------------------------------------------------------------------
# DIMENSION_MAPPING completeness
# ---------------------------------------------------------------------------


class TestDimensionMapping:
    def test_all_mapped_values_start_with_prefix(self) -> None:
        for v in DIMENSION_MAPPING.values():
            assert v.startswith("botInvestigationMetricsBy"), v

    def test_key_count(self) -> None:
        assert len(DIMENSION_MAPPING) >= 10


# ---------------------------------------------------------------------------
# run_bot_rule_compare — unit tests with mocked client and StateManager
# ---------------------------------------------------------------------------


def _make_mock_sm(tmp_path: Path) -> StateManager:
    return _make_manager(tmp_path)


_FAKE_REQUEST_BODY = {"rsuite": "test", "dimension": "variables/georegion", "globalFilters": []}
_FAKE_REPORT_RESPONSE = {"rows": [], "summaryData": {"totals": []}}


def _patch_build_request():
    return patch(
        "adobe_downloader.core.request_builder.build_request",
        return_value=_FAKE_REQUEST_BODY,
    )


class TestRunBotRuleCompare:
    async def test_skips_report_to_skip(self, tmp_path: Path) -> None:
        """The report matching report_to_skip must not be downloaded."""
        rsid_file = _make_rsid_file(tmp_path, [("triacoverscombr", "Coverscom")])
        sm = _make_mock_sm(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        bot_rules = [
            BotRule(
                segment_id="seg123",
                segment_name="Philippines-Rule",
                report_to_skip="botInvestigationMetricsByDomain",
            )
        ]

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByDomain"
        rd1.segments = []
        rd2 = MagicMock()
        rd2.name = "botInvestigationMetricsByRegion"
        rd2.segments = []

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, _patch_build_request():
            mock_load.return_value = [rd1, rd2]

            result = await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["Coverscom"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # Domain was skipped; Region: Segment (download) + AllTraffic (copied from Segment
        # since same body hash) = 1 API call, 1 copy
        assert client.get_report.call_count == 1
        assert result.downloaded == 1
        assert result.copied == 1
        assert result.failed == 0

    async def test_all_traffic_canonical_dedup(self, tmp_path: Path) -> None:
        """AllTraffic files for the same RSID+report should be copied, not re-downloaded."""
        rsid_file = _make_rsid_file(tmp_path, [("triacoverscombr", "Coverscom")])
        sm = _make_mock_sm(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        bot_rules = [
            BotRule("seg1", "Rule1", "botInvestigationMetricsByDomain"),
            BotRule("seg2", "Rule2", "botInvestigationMetricsByDomain"),
        ]

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByRegion"
        rd1.segments = []

        # Use different bodies for Segment vs AllTraffic so only AllTraffic deduplicates
        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "globalFilters": [{"id": s} for s in segments]}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd1]

            result = await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["Coverscom"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # Rule1: Segment (download) + AllTraffic (download) = 2
        # Rule2: Segment (download, different seg) + AllTraffic (copy, same body) = 1
        assert client.get_report.call_count == 3
        assert result.downloaded == 3
        assert result.copied == 1

    async def test_unknown_rsid_skipped(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "KnownSite")])
        sm = _make_mock_sm(tmp_path)
        client = AsyncMock()

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByRegion"
        rd1.segments = []

        bot_rules = [BotRule("seg1", "Rule1", "botInvestigationMetricsByDomain")]

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, _patch_build_request():
            mock_load.return_value = [rd1]

            result = await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["UnknownSite"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        assert client.get_report.call_count == 0
        assert result.failed == 1
        assert "UnknownSite" in result.errors[0]

    async def test_resume_skips_completed(self, tmp_path: Path) -> None:
        """Requests already in DB as completed must be skipped on resume."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "Site1")])
        sm = _make_mock_sm(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByRegion"
        rd1.segments = []

        bot_rules = [BotRule("seg1", "Rule1", "botInvestigationMetricsByDomain")]

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, _patch_build_request():
            mock_load.return_value = [rd1]

            # First run — downloads both
            await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["Site1"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )
            first_call_count = client.get_report.call_count

            # Second run with resume=True — should skip all
            result2 = await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["Site1"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=False,
            )

        assert client.get_report.call_count == first_call_count  # no extra API calls
        # Both Segment and AllTraffic entries are in DB as complete; both skipped
        assert result2.downloaded == 0
        assert result2.copied == 0
        assert result2.failed == 0

    async def test_download_failure_recorded(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "Site1")])
        sm = _make_mock_sm(tmp_path)

        client = AsyncMock()
        client.get_report = AsyncMock(side_effect=RuntimeError("API error"))

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByRegion"
        rd1.segments = []

        bot_rules = [BotRule("seg1", "Rule1", "botInvestigationMetricsByDomain")]

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, _patch_build_request():
            mock_load.return_value = [rd1]

            result = await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["Site1"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        assert result.failed == 2  # Segment + AllTraffic both failed
        assert "API error" in result.errors[0]

    async def test_investigation_name_format(self, tmp_path: Path) -> None:
        """Output file names must embed the investigation name pattern."""
        rsid_file = _make_rsid_file(tmp_path, [("triarsid1", "Coverscom")])
        sm = _make_mock_sm(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByRegion"
        rd1.segments = []

        bot_rules = [BotRule("seg1", "MyRule", "botInvestigationMetricsByDomain")]

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, _patch_build_request():
            mock_load.return_value = [rd1]

            await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["Coverscom"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=2.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        json_dir = tmp_path / "output" / "Legend" / "JSON"
        names = [f.name for f in json_dir.glob("*.json")]

        segment_files = [n for n in names if "Segment" in n]
        all_traffic_files = [n for n in names if "AllTraffic" in n]
        assert len(segment_files) == 1
        assert len(all_traffic_files) == 1
        assert "Coverscom-MyRule-Compare-V2.0-Segment" in segment_files[0]
        assert "Coverscom-MyRule-Compare-V2.0-AllTraffic" in all_traffic_files[0]
        assert "DIMSEG" in segment_files[0]
        assert "DIMSEG" not in all_traffic_files[0]

    async def test_multiple_rsids(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [
            ("triarsid1", "SiteA"),
            ("triarsid2", "SiteB"),
        ])
        sm = _make_mock_sm(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        rd1 = MagicMock()
        rd1.name = "botInvestigationMetricsByRegion"
        rd1.segments = []

        bot_rules = [BotRule("seg1", "Rule1", "botInvestigationMetricsByDomain")]

        def _build_req(report_def: Any, date_range: Any, rsid: str, segments: list[str]) -> dict[str, Any]:
            return {"rsuite": rsid, "globalFilters": [{"id": s} for s in segments]}

        with patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load, \
             patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req):
            mock_load.return_value = [rd1]

            result = await run_bot_rule_compare(
                client=client,
                client_name="Legend",
                rsid_clean_names=["SiteA", "SiteB"],
                rsid_lookup_file=rsid_file,
                bot_rules=bot_rules,
                date_range=_date("2025-01-01", "2025-03-31"),
                comparison_round=1.0,
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # SiteA: Segment + AllTraffic = 2 (different RSIDs, no canonical dedup across them)
        # SiteB: Segment + AllTraffic = 2
        assert result.downloaded == 4
        assert result.failed == 0


# ---------------------------------------------------------------------------
# Schema: bot_rule_compare step type
# ---------------------------------------------------------------------------


class TestBotRuleCompareSchema:
    def test_step_type_accepted(self) -> None:
        step = CompositeStep.model_validate({
            "step": "bot_rule_compare",
            "id": "compare",
        })
        assert step.step == "bot_rule_compare"

    def test_composite_job_with_bot_rule_compare_step(self) -> None:
        job = CompositeJobConfig.model_validate({
            "job_type": "composite",
            "client": "Legend",
            "output": {"base_folder": "/tmp/out"},
            "steps": [
                {
                    "step": "bot_rule_compare",
                    "id": "compare",
                    "rsids": {"source": "list", "list": ["CleanName1"]},
                    "bot_rules": {"source": "file", "file": "data/rules.csv"},
                    "comparison_round": 1.0,
                }
            ],
        })
        assert job.steps[0].step == "bot_rule_compare"


# ---------------------------------------------------------------------------
# Report definitions: bot_rule_compare group loads correctly
# ---------------------------------------------------------------------------


class TestBotRuleCompareReportDefs:
    def test_group_loads_ten_reports(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("bot_rule_compare")
        assert len(reports) == 10

    def test_no_default_segments(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("bot_rule_compare")
        for rd in reports:
            assert rd.segments == [], f"{rd.name} should have no default segments"

    def test_all_expected_report_names_present(self) -> None:
        from adobe_downloader.config.report_definitions import load_report_group
        reports = load_report_group("bot_rule_compare")
        names = {rd.name for rd in reports}
        expected = {
            "botInvestigationMetricsByMarketingChannel",
            "botInvestigationMetricsByMobileManufacturer",
            "botInvestigationMetricsByDomain",
            "botInvestigationMetricsByMonitorResolution",
            "botInvestigationMetricsByHourOfDay",
            "botInvestigationMetricsByOperatingSystem",
            "botInvestigationMetricsByPageURL",
            "botInvestigationMetricsByRegion",
            "botInvestigationMetricsByUserAgent",
            "botInvestigationMetricsByBrowserType",
        }
        assert names == expected
