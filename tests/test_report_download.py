"""Tests for flows/report_download.py and config/report_definitions.load_report_group()."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from adobe_downloader.config.report_definitions import load_report_group, load_report_registry
from adobe_downloader.config.schema import DateRange
from adobe_downloader.flows.report_download import download_report, make_output_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date(from_date: str, to: str) -> DateRange:
    return DateRange.model_validate({"from": from_date, "to": to})


def _mock_client(response: dict[str, Any]) -> MagicMock:
    client = MagicMock()
    client.get_report = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# make_output_path
# ---------------------------------------------------------------------------

def test_make_output_path_basic():
    path = make_output_path(
        base_folder="/data",
        client="Legend",
        report_name="botInvestigationMetricsByBrowser",
        date_range=_date("2025-01-01", "2025-02-01"),
    )
    assert path == Path("/data/Legend/JSON/Legend_botInvestigationMetricsByBrowser_2025-01-01_2025-02-01.json")


def test_make_output_path_with_file_name_extra():
    path = make_output_path(
        base_folder="/data",
        client="Legend",
        report_name="botInvestigationMetricsByBrowser",
        date_range=_date("2025-01-01", "2025-02-01"),
        file_name_extra="rsidFoo-Totals",
    )
    assert path == Path("/data/Legend/JSON/Legend_botInvestigationMetricsByBrowser_rsidFoo-Totals_2025-01-01_2025-02-01.json")


def test_make_output_path_with_segment_id():
    path = make_output_path(
        base_folder="/data",
        client="Legend",
        report_name="botInvestigationMetricsByBrowser",
        date_range=_date("2025-01-01", "2025-02-01"),
        segment_id="seg123",
    )
    # segment_id is embedded verbatim: DIMSEG{segment_id}
    assert path.name == "Legend_botInvestigationMetricsByBrowser_DIMSEGseg123_2025-01-01_2025-02-01.json"


def test_make_output_path_with_both_extra_and_segment():
    path = make_output_path(
        base_folder="/data",
        client="Legend",
        report_name="myReport",
        date_range=_date("2025-03-01", "2025-04-01"),
        file_name_extra="Totals",
        segment_id="abc",
    )
    assert "Legend_myReport_Totals_" in path.name
    assert "DIMSEGabc" in path.name
    assert path.name.endswith("_2025-03-01_2025-04-01.json")


def test_make_output_path_client_json_subfolder():
    path = make_output_path(
        base_folder=Path("/base"),
        client="ClientX",
        report_name="someReport",
        date_range=_date("2024-06-01", "2024-07-01"),
    )
    assert path.parent == Path("/base/ClientX/JSON")


# ---------------------------------------------------------------------------
# download_report
# ---------------------------------------------------------------------------

async def test_download_report_calls_get_report(tmp_path: Path):
    response = {"rows": [{"itemId": "1", "data": [100, 50]}], "totalPages": 1}
    client = _mock_client(response)
    request_body = {"rsid": "myrsid", "metricContainer": {}}
    out = tmp_path / "Legend" / "JSON" / "Legend_test_2025-01-01_2025-02-01.json"

    result = await download_report(client, request_body, out)

    client.get_report.assert_awaited_once_with(request_body)
    assert result == response


async def test_download_report_creates_parent_directories(tmp_path: Path):
    client = _mock_client({"rows": []})
    out = tmp_path / "deep" / "nested" / "dir" / "report.json"

    await download_report(client, {}, out)

    assert out.parent.exists()


async def test_download_report_writes_valid_json(tmp_path: Path):
    response = {"rows": [{"itemId": "42", "data": [999, 1]}], "totalPages": 1}
    client = _mock_client(response)
    out = tmp_path / "report.json"

    await download_report(client, {}, out)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == response


async def test_download_report_returns_api_response(tmp_path: Path):
    response = {"rows": [], "totalPages": 0, "message": "no data"}
    client = _mock_client(response)
    out = tmp_path / "empty_report.json"

    result = await download_report(client, {}, out)

    assert result is response


async def test_download_report_json_is_pretty_printed(tmp_path: Path):
    response = {"rows": [{"itemId": "1", "data": [10]}]}
    client = _mock_client(response)
    out = tmp_path / "report.json"

    await download_report(client, {}, out)

    raw = out.read_text(encoding="utf-8")
    assert "\n" in raw  # pretty-printed, not single-line


# ---------------------------------------------------------------------------
# load_report_group
# ---------------------------------------------------------------------------

def test_load_report_group_returns_all_reports():
    defs = load_report_group("bot_investigation")
    assert len(defs) > 0
    names = [d.name for d in defs]
    assert "botInvestigationMetricsByBrowser" in names
    assert "botInvestigationMetricsByDay" in names


def test_load_report_group_applies_defaults():
    defs = load_report_group("bot_investigation")
    for d in defs:
        # Every report in this group inherits the Master Bot Filter segment
        assert "s3938_66fe79408ff02713f66ed76b" in d.segments


def test_load_report_group_not_found_raises_key_error():
    with pytest.raises(KeyError, match="no_such_group"):
        load_report_group("no_such_group")


def test_load_report_group_consistent_with_registry():
    """Every report from load_report_group should appear in the flat registry."""
    registry = load_report_registry()
    defs = load_report_group("bot_investigation")
    for d in defs:
        assert d.name in registry
