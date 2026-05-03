"""Tests for lookup generation and search utilities."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adobe_downloader.config.schema import DateRange, LookupGenerationConfig
from adobe_downloader.segments.lookup_generator import (
    clean_dim_name,
    generate_lookup_file,
    merge_into_lookup_file,
    write_lookup_file,
)
from adobe_downloader.segments.lookup_searcher import search_lookup_value
from adobe_downloader.flows.lookup_generation import run_lookup_generation


# ---------------------------------------------------------------------------
# clean_dim_name
# ---------------------------------------------------------------------------


def test_clean_dim_name_removes_slashes() -> None:
    assert clean_dim_name("variables/browsertype") == "variablesbrowsertype"


def test_clean_dim_name_removes_mixed_specials() -> None:
    assert clean_dim_name("variables/geo-region_2") == "variablesgeoregion2"


def test_clean_dim_name_already_clean() -> None:
    assert clean_dim_name("variablesbrowsertype") == "variablesbrowsertype"


# ---------------------------------------------------------------------------
# write_lookup_file
# ---------------------------------------------------------------------------


def test_write_lookup_file_creates_file(tmp_path: Path) -> None:
    dest = tmp_path / "variablesbrowsertype" / "lookup.txt"
    pairs = {"Apple": "6", "Google": "8", "Microsoft": "2"}
    write_lookup_file(dest, pairs, "variables/browsertype", "Legend", "trillioncoverscom", "2025-01-01", "2025-12-31")

    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "Apple|6" in content
    assert "Google|8" in content
    assert "Microsoft|2" in content


def test_write_lookup_file_sorted(tmp_path: Path) -> None:
    dest = tmp_path / "lookup.txt"
    pairs = {"Zynga": "99", "Apple": "6", "Mozilla": "7"}
    write_lookup_file(dest, pairs, "variables/browsertype", "Legend", "rsid", "2025-01-01", "2025-12-31")

    lines = [l for l in dest.read_text(encoding="utf-8").splitlines() if "|" in l and not l.strip().startswith("*") and not l.strip().startswith("/")]
    assert lines == ["Apple|6", "Mozilla|7", "Zynga|99"]


def test_write_lookup_file_includes_header(tmp_path: Path) -> None:
    dest = tmp_path / "lookup.txt"
    write_lookup_file(dest, {"A": "1"}, "variables/browsertype", "Legend", "myrsid", "2025-01-01", "2025-03-31")

    content = dest.read_text(encoding="utf-8")
    assert "variables/browsertype" in content
    assert "Legend" in content
    assert "myrsid" in content
    assert "2025-01-01" in content
    assert "2025-03-31" in content


def test_write_lookup_file_creates_parent_dirs(tmp_path: Path) -> None:
    dest = tmp_path / "deep" / "nested" / "lookup.txt"
    write_lookup_file(dest, {"A": "1"}, "variables/x", "C", "r", "2025-01-01", "2025-12-31")
    assert dest.exists()


# ---------------------------------------------------------------------------
# merge_into_lookup_file
# ---------------------------------------------------------------------------


def test_merge_into_lookup_file_creates_when_missing(tmp_path: Path) -> None:
    lookup_path = tmp_path / "variablesbrowsertype" / "lookup.txt"
    result = merge_into_lookup_file(lookup_path, {"Apple": "6"}, "variables/browsertype", "Legend")
    assert result == {"Apple": "6"}
    assert lookup_path.exists()
    assert "Apple|6" in lookup_path.read_text(encoding="utf-8")


def test_merge_into_lookup_file_merges_with_existing(tmp_path: Path) -> None:
    lookup_path = tmp_path / "lookup.txt"
    write_lookup_file(lookup_path, {"Apple": "6"}, "variables/browsertype", "Legend", "rsid", "2025-01-01", "2025-12-31")
    result = merge_into_lookup_file(lookup_path, {"Google": "8"}, "variables/browsertype", "Legend")
    assert result == {"Apple": "6", "Google": "8"}
    content = lookup_path.read_text(encoding="utf-8")
    assert "Apple|6" in content
    assert "Google|8" in content


def test_merge_into_lookup_file_no_duplicates(tmp_path: Path) -> None:
    lookup_path = tmp_path / "lookup.txt"
    write_lookup_file(lookup_path, {"Apple": "6"}, "variables/browsertype", "Legend", "rsid", "2025-01-01", "2025-12-31")
    result = merge_into_lookup_file(lookup_path, {"Apple": "6"}, "variables/browsertype", "Legend")
    # Apple appears only once in the file
    lines_with_apple = [l for l in lookup_path.read_text(encoding="utf-8").splitlines() if l.startswith("Apple")]
    assert len(lines_with_apple) == 1
    assert result["Apple"] == "6"


# ---------------------------------------------------------------------------
# generate_lookup_file
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def date_range_fixture() -> DateRange:
    return DateRange.model_validate({"from": "2025-01-01", "to": "2025-12-31"})


async def test_generate_lookup_file_writes_pairs(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={
        "rows": [
            {"value": "Apple", "itemId": 6},
            {"value": "Google", "itemId": 8},
        ]
    })
    dest = await generate_lookup_file(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        rsid="trillioncoverscom",
        date_range=date_range_fixture,
        segments=[],
        lookup_base=tmp_path,
    )
    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    assert "Apple|6" in content
    assert "Google|8" in content


async def test_generate_lookup_file_default_path(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={"rows": [{"value": "Apple", "itemId": 6}]})
    dest = await generate_lookup_file(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        rsid="rsid",
        date_range=date_range_fixture,
        segments=[],
        lookup_base=tmp_path,
    )
    assert dest == tmp_path / "variablesbrowsertype" / "lookup.txt"


async def test_generate_lookup_file_custom_output(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={"rows": []})
    custom = tmp_path / "custom" / "out.txt"
    dest = await generate_lookup_file(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        rsid="rsid",
        date_range=date_range_fixture,
        segments=[],
        lookup_base=tmp_path,
        output_path=custom,
    )
    assert dest == custom
    assert dest.exists()


async def test_generate_lookup_file_skips_incomplete_rows(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={
        "rows": [
            {"value": "Apple", "itemId": 6},
            {"value": "NoId"},          # missing itemId
            {"itemId": 99},             # missing value
        ]
    })
    dest = await generate_lookup_file(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        rsid="rsid",
        date_range=date_range_fixture,
        segments=[],
        lookup_base=tmp_path,
    )
    content = dest.read_text(encoding="utf-8")
    assert "Apple|6" in content
    assert "NoId" not in content
    assert "|99" not in content


# ---------------------------------------------------------------------------
# search_lookup_value
# ---------------------------------------------------------------------------


async def test_search_lookup_value_local_cache_hit(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    lookup_path = tmp_path / "variablesbrowsertype" / "lookup.txt"
    write_lookup_file(lookup_path, {"Apple": "6"}, "variables/browsertype", "Legend", "rsid", "2025-01-01", "2025-12-31")

    result = await search_lookup_value(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        value="Apple",
        rsid_list=["rsid1", "rsid2"],
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert result == "6"
    mock_client.get_report.assert_not_called()


async def test_search_lookup_value_found_in_rsid(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={
        "rows": [{"value": "Samsung", "itemId": 24}]
    })
    result = await search_lookup_value(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        value="Samsung",
        rsid_list=["rsid1"],
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert result == "24"
    lookup_path = tmp_path / "variablesbrowsertype" / "lookup.txt"
    assert "Samsung|24" in lookup_path.read_text(encoding="utf-8")


async def test_search_lookup_value_stops_at_first_match(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={
        "rows": [{"value": "Samsung", "itemId": 24}]
    })
    result = await search_lookup_value(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        value="Samsung",
        rsid_list=["rsid1", "rsid2", "rsid3"],
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert result == "24"
    # Should stop after first RSID finds the value
    assert mock_client.get_report.call_count == 1


async def test_search_lookup_value_not_found_returns_none(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={"rows": [{"value": "Apple", "itemId": 6}]})
    result = await search_lookup_value(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        value="UnknownBrowser",
        rsid_list=["rsid1"],
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert result is None


async def test_search_lookup_value_skips_failed_rsids(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(
        side_effect=[
            Exception("network error"),
            {"rows": [{"value": "Opera", "itemId": 33}]},
        ]
    )
    result = await search_lookup_value(
        client=mock_client,
        client_name="Legend",
        dimension="variables/browsertype",
        value="Opera",
        rsid_list=["rsid1", "rsid2"],
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert result == "33"


# ---------------------------------------------------------------------------
# run_lookup_generation flow
# ---------------------------------------------------------------------------


async def test_run_lookup_generation_delegates(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={
        "rows": [{"value": "Apple", "itemId": 6}]
    })
    config = LookupGenerationConfig(dimension="variables/browsertype", rsid="trillioncoverscom")
    dest = await run_lookup_generation(
        client=mock_client,
        client_name="Legend",
        config=config,
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert dest == tmp_path / "variablesbrowsertype" / "lookup.txt"
    assert dest.exists()


async def test_run_lookup_generation_custom_output_file(tmp_path: Path, mock_client: MagicMock, date_range_fixture: DateRange) -> None:
    mock_client.get_report = AsyncMock(return_value={"rows": []})
    custom = str(tmp_path / "custom.txt")
    config = LookupGenerationConfig(
        dimension="variables/browsertype",
        rsid="rsid",
        output_file=custom,
    )
    dest = await run_lookup_generation(
        client=mock_client,
        client_name="Legend",
        config=config,
        date_range=date_range_fixture,
        lookup_base=tmp_path,
    )
    assert dest == Path(custom)
