"""Tests for flows/country_matrix.py and the generate_country_matrix composite step."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from adobe_downloader.config.schema import (
    CompositeJobConfig,
    CompositeStep,
    DateRange,
    RsidSource,
)
from adobe_downloader.flows.country_matrix import (
    load_country_lookup,
    load_matrix_file,
    run_generate_country_matrix,
    save_country_lookup,
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


_FAKE_REQUEST_BODY = {"rsid": "test", "globalFilters": []}


def _patch_build_request():
    return patch(
        "adobe_downloader.core.request_builder.build_request",
        return_value=_FAKE_REQUEST_BODY,
    )


# ---------------------------------------------------------------------------
# load_matrix_file: legacy key support
# ---------------------------------------------------------------------------


class TestLoadMatrixFileLegacyFormat:
    def test_reads_legacy_js_key_names(self, tmp_path: Path) -> None:
        """The legacy JS tool wrote rsidCleanName/geocountry/segmentId — real migrated
        data (data/rsid_country_thresholds/botInvestigationRsidCountriesMinThreshold.json)
        uses this format and should load without a conversion step."""
        import json

        legacy_file = tmp_path / "legacy_matrix.json"
        legacy_file.write_text(
            json.dumps(
                [
                    {
                        "rsidCleanName": "Apuestasdeportivascom",
                        "geocountry": "Spain",
                        "segmentId": "s3938_6852864ce90051508f05779b",
                        "visits": 181074,
                    }
                ]
            )
        )

        pairs = load_matrix_file(legacy_file)
        assert len(pairs) == 1
        assert pairs[0].rsid_clean_name == "Apuestasdeportivascom"
        assert pairs[0].country == "Spain"
        assert pairs[0].segment_id == "s3938_6852864ce90051508f05779b"
        assert pairs[0].visits == 181074

    def test_reads_current_key_names(self, tmp_path: Path) -> None:
        matrix_file = tmp_path / "matrix.json"
        matrix_file.write_text(
            '[{"rsid_clean_name": "CasinoOrg", "country": "France", '
            '"segment_id": "seg1", "visits": 5000}]'
        )

        pairs = load_matrix_file(matrix_file)
        assert pairs[0].rsid_clean_name == "CasinoOrg"
        assert pairs[0].country == "France"


# ---------------------------------------------------------------------------
# run_generate_country_matrix
# ---------------------------------------------------------------------------


class TestRunGenerateCountryMatrix:
    async def test_creates_new_segment_for_qualifying_country(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(
            return_value={
                "rows": [
                    {"itemId": "111", "value": "United Kingdom", "data": [400, 500]},
                    {"itemId": "222", "value": "France", "data": [10, 20]},
                ]
            }
        )
        client.create_segment = AsyncMock(return_value={"id": "seg_new_uk"})
        client.share_segment = AsyncMock()

        country_lookup_file = tmp_path / "country_lookup.json"
        matrix_file = tmp_path / "matrix.json"

        with _patch_build_request():
            result = await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["CasinoOrg"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,
                country_lookup_file=country_lookup_file,
                matrix_file=matrix_file,
                sm=sm,
                share_with_users=["200419062"],
                no_resume=True,
                output_base=str(tmp_path / "output"),
            )

        # France (20 visits) is below threshold; only United Kingdom qualifies
        assert result.segments_created == 1
        assert len(result.pairs) == 1
        pair = result.pairs[0]
        assert pair.rsid_clean_name == "CasinoOrg"
        assert pair.country == "United Kingdom"
        assert pair.segment_id == "seg_new_uk"
        assert pair.visits == 500

        client.create_segment.assert_called_once()
        client.share_segment.assert_called_once_with("seg_new_uk", ["200419062"])

        pairs_on_disk = load_matrix_file(matrix_file)
        assert len(pairs_on_disk) == 1
        assert pairs_on_disk[0].country == "United Kingdom"

        lookup = load_country_lookup(country_lookup_file)
        assert any(e["DimValueId"] == "111" and e["SegmentId"] == "seg_new_uk" for e in lookup)

    async def test_reuses_existing_segment_by_dim_value_id(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(
            return_value={
                "rows": [{"itemId": "111", "value": "United Kingdom", "data": [400, 500]}]
            }
        )
        client.create_segment = AsyncMock()

        country_lookup_file = tmp_path / "country_lookup.json"
        save_country_lookup(
            country_lookup_file,
            [
                {
                    "SegmentId": "seg_existing",
                    "SegmentName": "variables/geocountry = United Kingdom",
                    "DimValueId": "111",
                    "DimValueName": "United Kingdom",
                }
            ],
        )
        matrix_file = tmp_path / "matrix.json"

        with _patch_build_request():
            result = await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["CasinoOrg"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,
                country_lookup_file=country_lookup_file,
                matrix_file=matrix_file,
                sm=sm,
                no_resume=True,
                output_base=str(tmp_path / "output"),
            )

        assert result.segments_created == 0
        assert result.pairs[0].segment_id == "seg_existing"
        client.create_segment.assert_not_called()

    async def test_below_threshold_country_excluded(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(
            return_value={
                "rows": [{"itemId": "111", "value": "United Kingdom", "data": [400, 100]}]
            }
        )

        with _patch_build_request():
            result = await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["CasinoOrg"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,  # exactly at threshold — strictly-greater-than excludes it
                country_lookup_file=tmp_path / "country_lookup.json",
                matrix_file=tmp_path / "matrix.json",
                sm=sm,
                no_resume=True,
                output_base=str(tmp_path / "output"),
            )

        assert len(result.pairs) == 0

    async def test_unknown_rsid_skipped(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "KnownSite")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock()

        with _patch_build_request():
            result = await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["UnknownSite"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,
                country_lookup_file=tmp_path / "country_lookup.json",
                matrix_file=tmp_path / "matrix.json",
                sm=sm,
                no_resume=True,
                output_base=str(tmp_path / "output"),
            )

        assert client.get_report.call_count == 0
        assert result.failed == 1
        assert "UnknownSite" in result.errors[0]

    async def test_two_rsids_share_one_country_segment(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "SiteA"), ("rsid2", "SiteB")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(
            return_value={
                "rows": [{"itemId": "111", "value": "United Kingdom", "data": [400, 500]}]
            }
        )
        client.create_segment = AsyncMock(return_value={"id": "seg_uk"})
        client.share_segment = AsyncMock()

        with _patch_build_request():
            result = await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["SiteA", "SiteB"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,
                country_lookup_file=tmp_path / "country_lookup.json",
                matrix_file=tmp_path / "matrix.json",
                sm=sm,
                no_resume=True,
                output_base=str(tmp_path / "output"),
            )

        # Segment created once, reused for the second RSID's identical country
        assert result.segments_created == 1
        assert len(result.pairs) == 2
        assert {p.segment_id for p in result.pairs} == {"seg_uk"}

    async def test_resume_skips_completed_download(self, tmp_path: Path) -> None:
        rsid_file = _make_rsid_file(tmp_path, [("rsid1", "CasinoOrg")])
        sm = _make_manager(tmp_path)
        client = AsyncMock()
        client.get_report = AsyncMock(
            return_value={
                "rows": [{"itemId": "111", "value": "United Kingdom", "data": [400, 500]}]
            }
        )
        client.create_segment = AsyncMock(return_value={"id": "seg_uk"})
        client.share_segment = AsyncMock()

        with _patch_build_request():
            await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["CasinoOrg"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,
                country_lookup_file=tmp_path / "country_lookup.json",
                matrix_file=tmp_path / "matrix.json",
                sm=sm,
                no_resume=True,
                output_base=str(tmp_path / "output"),
            )
            first_call_count = client.get_report.call_count

            result2 = await run_generate_country_matrix(
                client=client,
                client_name="Legend",
                rsids=RsidSource.model_validate({"source": "list", "list": ["CasinoOrg"]}),
                rsid_lookup_file=rsid_file,
                date_range=_date("2026-01-01", "2026-03-31"),
                visit_threshold=100,
                country_lookup_file=tmp_path / "country_lookup.json",
                matrix_file=tmp_path / "matrix.json",
                sm=sm,
                no_resume=False,
                output_base=str(tmp_path / "output"),
            )

        assert client.get_report.call_count == first_call_count  # no re-download
        assert len(result2.pairs) == 1  # still recomputed from the on-disk JSON


# ---------------------------------------------------------------------------
# Schema: generate_country_matrix step type
# ---------------------------------------------------------------------------


class TestGenerateCountryMatrixSchema:
    def test_step_type_accepted(self) -> None:
        step = CompositeStep.model_validate({"step": "generate_country_matrix", "id": "matrix"})
        assert step.step == "generate_country_matrix"

    def test_composite_job_with_generate_country_matrix_step(self) -> None:
        job = CompositeJobConfig.model_validate(
            {
                "job_type": "composite",
                "client": "Legend",
                "output": {"base_folder": "/tmp/out"},
                "steps": [
                    {
                        "step": "generate_country_matrix",
                        "id": "matrix",
                        "rsids": {"source": "list", "list": ["CleanName1"]},
                        "visit_threshold": 100000,
                    }
                ],
            }
        )
        assert job.steps[0].step == "generate_country_matrix"
