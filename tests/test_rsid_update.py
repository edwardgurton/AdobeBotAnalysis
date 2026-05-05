"""Tests for flows/rsid_update.py — Step 18."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adobe_downloader.config.schema import DateRange, RsidUpdateConfig
from adobe_downloader.flows.rsid_update import (
    RsidUpdateResult,
    RsidWithVisits,
    _archive_file,
    _write_clean_name_list,
    _write_suite_pairs_file,
    clean_suite_name,
    load_exclusion_list,
    run_rsid_update,
)


# ---------------------------------------------------------------------------
# clean_suite_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Casino Online", "CasinoOnline"),
        ("Casino.Online", "CasinoOnline"),
        ("Casino Online - Production", "CasinoOnline"),
        ("Casino Online-Production", "CasinoOnline"),
        ("Casino Online - production", "CasinoOnline"),
        ("My Site.com", "MySitecom"),
        ("Plain Name", "PlainName"),
        ("NoChange", "NoChange"),
        ("A B C - Production", "ABC"),
        # dots AND spaces
        ("casino.com UK - Production", "casinocomUK"),
    ],
)
def test_clean_suite_name(name: str, expected: str) -> None:
    assert clean_suite_name(name) == expected


# ---------------------------------------------------------------------------
# load_exclusion_list
# ---------------------------------------------------------------------------


def test_load_exclusion_list_missing_file() -> None:
    assert load_exclusion_list(Path("nonexistent_file.txt")) == set()


def test_load_exclusion_list_none() -> None:
    assert load_exclusion_list(None) == set()


def test_load_exclusion_list_reads_names(tmp_path: Path) -> None:
    f = tmp_path / "excl.txt"
    f.write_text("Alpha\nBeta\n\nGamma\n", encoding="utf-8")
    result = load_exclusion_list(f)
    assert result == {"Alpha", "Beta", "Gamma"}


# ---------------------------------------------------------------------------
# _write_clean_name_list
# ---------------------------------------------------------------------------


def test_write_clean_name_list_content(tmp_path: Path) -> None:
    out = tmp_path / "investigation.txt"
    dr = DateRange(from_date="2025-01-01", to="2025-03-31")
    _write_clean_name_list(out, ["AlphaName", "BetaSite"], 500, dr, "20250401")
    text = out.read_text(encoding="utf-8")
    assert "# Minimum threshold = 500" in text
    assert "# Date range = 2025-01-01 to 2025-03-31" in text
    assert "# File generated on 20250401" in text
    assert "AlphaName" in text
    assert "BetaSite" in text


def test_write_clean_name_list_creates_parent(tmp_path: Path) -> None:
    out = tmp_path / "sub" / "dir" / "list.txt"
    dr = DateRange(from_date="2025-01-01", to="2025-01-31")
    _write_clean_name_list(out, ["X"], 100, dr, "20250131")
    assert out.exists()


# ---------------------------------------------------------------------------
# _write_suite_pairs_file
# ---------------------------------------------------------------------------


def test_write_suite_pairs_file(tmp_path: Path) -> None:
    out = tmp_path / "pairs.txt"
    _write_suite_pairs_file(out, [("rsid1", "CleanOne"), ("rsid2", "CleanTwo")])
    lines = out.read_text(encoding="utf-8").splitlines()
    assert "rsid1:CleanOne" in lines
    assert "rsid2:CleanTwo" in lines


# ---------------------------------------------------------------------------
# _archive_file
# ---------------------------------------------------------------------------


def test_archive_file_creates_copy(tmp_path: Path) -> None:
    src = tmp_path / "botInvestigationMinThresholdVisits.txt"
    src.write_text("existing content", encoding="utf-8")
    _archive_file(src, "20250401")
    archived = tmp_path / "archive" / "botInvestigationMinThresholdVisits_20250401.txt"
    assert archived.exists()
    assert archived.read_text(encoding="utf-8") == "existing content"


def test_archive_file_no_op_when_missing(tmp_path: Path) -> None:
    _archive_file(tmp_path / "nonexistent.txt", "20250401")
    assert not (tmp_path / "archive").exists()


# ---------------------------------------------------------------------------
# run_rsid_update — unit tests with mocked API
# ---------------------------------------------------------------------------

_FAKE_SUITES = {
    "content": [
        {"rsid": "tri123", "name": "Casino Site"},
        {"rsid": "tri456", "name": "Betting.com - Production"},
        {"rsid": "vrs_789", "name": "Virtual Suite"},
        {"rsid": "tri000", "name": "Small Site"},
    ]
}

_DATE_RANGE = DateRange(from_date="2025-01-01", to="2025-03-31")


def _make_totals_response(visits: int) -> dict:
    return {"summaryData": {"totals": [visits // 2, visits]}}


@pytest.mark.asyncio
async def test_run_rsid_update_filters_virtual(tmp_path: Path) -> None:
    """Virtual suites are excluded when include_virtual=False."""
    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100, include_virtual=False)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
        )

    assert result.total_suites == 3  # vrs_ filtered out
    assert result.investigation_count == 3
    assert result.validation_count == 3


@pytest.mark.asyncio
async def test_run_rsid_update_includes_virtual_when_flag_set(tmp_path: Path) -> None:
    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100, include_virtual=True)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
        )

    assert result.total_suites == 4  # all suites including vrs_


@pytest.mark.asyncio
async def test_run_rsid_update_threshold_filtering(tmp_path: Path) -> None:
    """RSIDs below threshold are excluded from lists."""
    cfg = RsidUpdateConfig(investigation_threshold=1000, validation_threshold=2000)
    visit_map = {"tri123": 1500, "tri456": 800, "tri000": 2500}

    async def _mock_visits(client: object, rsid: str, date_range: object) -> int | None:
        return visit_map.get(rsid, 0)

    with patch("adobe_downloader.flows.rsid_update._fetch_visits", side_effect=_mock_visits):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
        )

    assert result.total_suites == 3  # vrs_ excluded
    assert result.investigation_count == 2  # tri123 (1500) and tri000 (2500) >= 1000
    assert result.validation_count == 1  # only tri000 (2500) >= 2000


@pytest.mark.asyncio
async def test_run_rsid_update_exclusion_list(tmp_path: Path) -> None:
    """Clean names in the exclusion list are removed from output."""
    excl = tmp_path / "excl.txt"
    excl.write_text("CasinoSite\n", encoding="utf-8")  # matches clean_suite_name("Casino Site")

    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
            exclusion_file=excl,
        )

    # CasinoSite excluded → 2 remaining (BettingCom + SmallSite)
    assert result.investigation_count == 2


@pytest.mark.asyncio
async def test_run_rsid_update_writes_output_files(tmp_path: Path) -> None:
    """Output files exist and contain clean names."""
    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
        )

    assert result.investigation_list.exists()
    assert result.validation_list.exists()
    text = result.investigation_list.read_text(encoding="utf-8")
    assert "CasinoSite" in text
    assert "Bettingcom" in text


@pytest.mark.asyncio
async def test_run_rsid_update_archives_existing_file(tmp_path: Path) -> None:
    """Existing output file is archived before being overwritten."""
    inv_path = tmp_path / "botInvestigationMinThresholdVisits.txt"
    inv_path.write_text("old content\n", encoding="utf-8")

    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
        )

    # Archive dir should exist with one file
    archive_dir = tmp_path / "archive"
    assert archive_dir.exists()
    archived = list(archive_dir.glob("botInvestigationMinThresholdVisits_*.txt"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == "old content\n"


@pytest.mark.asyncio
async def test_run_rsid_update_writes_suite_pairs_file(tmp_path: Path) -> None:
    """Suite pairs file is written when suite_pairs_dir is given."""
    pairs_dir = tmp_path / "pairs"
    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
            suite_pairs_dir=pairs_dir,
        )

    assert result.suite_pairs_file is not None
    assert result.suite_pairs_file.exists()
    text = result.suite_pairs_file.read_text(encoding="utf-8")
    assert "tri123:CasinoSite" in text


@pytest.mark.asyncio
async def test_run_rsid_update_handles_fetch_failure(tmp_path: Path) -> None:
    """Failed visits fetches are counted, suite not included in output lists."""
    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100)

    async def _flaky_visits(client: object, rsid: str, date_range: object) -> int | None:
        if rsid == "tri123":
            return None  # simulate failure
        return 500

    with patch("adobe_downloader.flows.rsid_update._fetch_visits", side_effect=_flaky_visits):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
        )

    assert result.failed == 1
    assert result.investigation_count == 2  # tri456 + tri000 succeed; tri123 failed


@pytest.mark.asyncio
async def test_run_rsid_update_no_suite_pairs_file_when_dir_none(tmp_path: Path) -> None:
    """No suite pairs file written when suite_pairs_dir is None."""
    cfg = RsidUpdateConfig(investigation_threshold=100, validation_threshold=100)

    with patch(
        "adobe_downloader.flows.rsid_update._fetch_visits",
        new=AsyncMock(return_value=500),
    ):
        mock_client = AsyncMock()
        mock_client.get_report_suites = AsyncMock(return_value=_FAKE_SUITES)

        result = await run_rsid_update(
            client=mock_client,
            rsid_update_cfg=cfg,
            date_range=_DATE_RANGE,
            output_base=tmp_path,
            suite_pairs_dir=None,
        )

    assert result.suite_pairs_file is None


# ---------------------------------------------------------------------------
# Schema — RsidUpdateJobConfig with date_range
# ---------------------------------------------------------------------------


def test_rsid_update_job_config_with_date_range() -> None:
    from adobe_downloader.config.schema import RsidUpdateJobConfig
    import yaml

    raw = yaml.safe_load(
        """
        job_type: rsid_update
        client: Legend
        rsid_update:
          investigation_threshold: 500
          validation_threshold: 1000
          include_virtual: false
        date_range:
          from_date: "2025-01-01"
          to: "2025-03-31"
        output:
          base_folder: data/rsid_lists/
        """
    )
    job = RsidUpdateJobConfig.model_validate(raw)
    assert job.rsid_update.investigation_threshold == 500
    assert job.date_range is not None
    assert job.date_range.from_date == "2025-01-01"


def test_rsid_update_job_config_without_date_range() -> None:
    from adobe_downloader.config.schema import RsidUpdateJobConfig
    import yaml

    raw = yaml.safe_load(
        """
        job_type: rsid_update
        client: Legend
        output:
          base_folder: data/rsid_lists/
        """
    )
    job = RsidUpdateJobConfig.model_validate(raw)
    assert job.date_range is None
    assert job.rsid_update.investigation_threshold == 1000  # default
