"""Tests for flows/country_investigation.py and the country_investigation composite step."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from adobe_downloader.config.schema import (
    CompositeJobConfig,
    CompositeStep,
    DateRange,
)
from adobe_downloader.flows.country_investigation import (
    combo_label,
    run_country_investigation,
)
from adobe_downloader.flows.country_matrix import RsidCountryPair, write_matrix_file
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


_FAKE_REQUEST_BODY = {"rsid": "test", "globalFilters": []}
_FAKE_REPORT_RESPONSE = {"rows": [], "summaryData": {"totals": []}}


def _patch_build_request():
    return patch(
        "adobe_downloader.core.request_builder.build_request",
        return_value=_FAKE_REQUEST_BODY,
    )


def _report_def(name: str) -> Any:
    rd = MagicMock()
    rd.name = name
    rd.segments = []
    return rd


# ---------------------------------------------------------------------------
# combo_label
# ---------------------------------------------------------------------------


class TestComboLabel:
    def test_basic(self) -> None:
        assert combo_label("CasinoOrg", "United Kingdom", "FullRun-V1") == (
            "CasinoOrg-United-Kingdom-FullRun-V1"
        )

    def test_sanitizes_underscores_in_country(self) -> None:
        # Underscores would shift transform_report's positional filename parsing.
        assert "_" not in combo_label("CasinoOrg", "Some_Country", "FullRun-V1")


# ---------------------------------------------------------------------------
# run_country_investigation
# ---------------------------------------------------------------------------


class TestRunCountryInvestigation:
    async def test_downloads_one_report_per_pair(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg"), ("rsid2", "Legend2")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        matrix_file = tmp_path / "matrix.json"
        write_matrix_file(
            matrix_file,
            [
                RsidCountryPair("CasinoOrg", "United Kingdom", "seg_uk", 500),
                RsidCountryPair("Legend2", "France", "seg_fr", 300),
            ],
        )

        def _build_req(
            report_def: Any, date_range: Any, rsid: str, segments: list[str]
        ) -> dict[str, Any]:
            return {"rsid": rsid, "globalFilters": [{"id": s} for s in segments]}

        with (
            patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load,
            patch("adobe_downloader.core.request_builder.build_request", side_effect=_build_req),
        ):
            mock_load.return_value = [_report_def("botInvestigationMetricsByBrowser")]

            result = await run_country_investigation(
                client=client,
                client_name="Legend",
                matrix_file=matrix_file,
                rsid_lookup_file=rsid_file,
                report_group="bot_investigation",
                date_range=_date("2026-01-01", "2026-03-31"),
                interval="full",
                investigation_label="FullRun-V1",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        # Different RSIDs/segments → distinct request bodies, no canonical dedup
        assert result.downloaded == 2
        assert result.failed == 0

        json_dir = tmp_path / "output" / "Legend" / "JSON"
        names = [f.name for f in json_dir.glob("*.json")]
        assert any("CasinoOrg-United-Kingdom-FullRun-V1" in n for n in names)
        assert any("Legend2-France-FullRun-V1" in n for n in names)

    async def test_file_name_extra_suffix_appended(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        matrix_file = tmp_path / "matrix.json"
        write_matrix_file(
            matrix_file, [RsidCountryPair("CasinoOrg", "United Kingdom", "seg_uk", 500)]
        )

        with (
            patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load,
            _patch_build_request(),
        ):
            mock_load.return_value = [_report_def("botInvestigationMetricsByBrowser")]

            await run_country_investigation(
                client=client,
                client_name="Legend",
                matrix_file=matrix_file,
                rsid_lookup_file=rsid_file,
                report_group="bot_investigation",
                date_range=_date("2026-01-01", "2026-03-31"),
                interval="full",
                investigation_label="FullRun-V1",
                file_name_extra="Daily",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        json_dir = tmp_path / "output" / "Legend" / "JSON"
        names = [f.name for f in json_dir.glob("*.json")]
        assert any("CasinoOrg-United-Kingdom-FullRun-V1-Daily" in n for n in names)

    async def test_unknown_rsid_in_matrix_skipped(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "KnownSite")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        matrix_file = tmp_path / "matrix.json"
        write_matrix_file(matrix_file, [RsidCountryPair("UnknownSite", "France", "seg_fr", 300)])

        with (
            patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load,
            _patch_build_request(),
        ):
            mock_load.return_value = [_report_def("botInvestigationMetricsByBrowser")]

            result = await run_country_investigation(
                client=client,
                client_name="Legend",
                matrix_file=matrix_file,
                rsid_lookup_file=rsid_file,
                report_group="bot_investigation",
                date_range=_date("2026-01-01", "2026-03-31"),
                interval="full",
                investigation_label="FullRun-V1",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        assert client.get_report.call_count == 0
        assert result.failed == 1
        assert "UnknownSite" in result.errors[0]

    async def test_resume_skips_completed(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(return_value=_FAKE_REPORT_RESPONSE)

        matrix_file = tmp_path / "matrix.json"
        write_matrix_file(
            matrix_file, [RsidCountryPair("CasinoOrg", "United Kingdom", "seg_uk", 500)]
        )

        with (
            patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load,
            _patch_build_request(),
        ):
            mock_load.return_value = [_report_def("botInvestigationMetricsByBrowser")]

            await run_country_investigation(
                client=client,
                client_name="Legend",
                matrix_file=matrix_file,
                rsid_lookup_file=rsid_file,
                report_group="bot_investigation",
                date_range=_date("2026-01-01", "2026-03-31"),
                interval="full",
                investigation_label="FullRun-V1",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )
            first_call_count = client.get_report.call_count

            result2 = await run_country_investigation(
                client=client,
                client_name="Legend",
                matrix_file=matrix_file,
                rsid_lookup_file=rsid_file,
                report_group="bot_investigation",
                date_range=_date("2026-01-01", "2026-03-31"),
                interval="full",
                investigation_label="FullRun-V1",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=False,
            )

        assert client.get_report.call_count == first_call_count
        assert result2.downloaded == 0
        assert result2.skipped == 1

    async def test_download_failure_recorded(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(side_effect=RuntimeError("API error"))

        matrix_file = tmp_path / "matrix.json"
        write_matrix_file(
            matrix_file, [RsidCountryPair("CasinoOrg", "United Kingdom", "seg_uk", 500)]
        )

        with (
            patch("adobe_downloader.config.report_definitions.load_report_group") as mock_load,
            _patch_build_request(),
        ):
            mock_load.return_value = [_report_def("botInvestigationMetricsByBrowser")]

            result = await run_country_investigation(
                client=client,
                client_name="Legend",
                matrix_file=matrix_file,
                rsid_lookup_file=rsid_file,
                report_group="bot_investigation",
                date_range=_date("2026-01-01", "2026-03-31"),
                interval="full",
                investigation_label="FullRun-V1",
                output_base=str(tmp_path / "output"),
                sm=sm,
                no_resume=True,
            )

        assert result.failed == 1
        assert "API error" in result.errors[0]


# ---------------------------------------------------------------------------
# Schema: country_investigation step type
# ---------------------------------------------------------------------------


class TestCountryInvestigationSchema:
    def test_step_type_accepted(self) -> None:
        step = CompositeStep.model_validate({"step": "country_investigation", "id": "download"})
        assert step.step == "country_investigation"

    def test_composite_job_with_country_investigation_step(self) -> None:
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": "/tmp/out", "job_name": "job1"},
                "steps": [
                    {
                        "step": "country_investigation",
                        "id": "download",
                        "matrix": {"source": "file", "file": "data/matrix.json"},
                        "interval": "full",
                    },
                    {
                        "step": "transform_concat",
                        "id": "transform",
                        "depends_on": "download",
                        "transform": {"type": "bot_investigation"},
                    },
                ],
            }
        )
        assert job.steps[0].step == "country_investigation"

    def test_matrix_source_step_output_requires_step_id_and_key(self) -> None:
        import pytest

        from adobe_downloader.config.schema import MatrixSource

        with pytest.raises(ValueError, match="step_id"):
            MatrixSource.model_validate({"source": "step_output"})

    def test_matrix_source_file_requires_file(self) -> None:
        import pytest

        from adobe_downloader.config.schema import MatrixSource

        with pytest.raises(ValueError, match="file"):
            MatrixSource.model_validate({"source": "file"})
