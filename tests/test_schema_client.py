"""Tests for schema endpoints in AdobeClient — Step 20."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from adobe_downloader.core.api_client import AdobeClient


def _make_response(payload: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _make_client() -> AdobeClient:
    with patch("adobe_downloader.core.api_client.load_credentials") as mock_creds, patch(
        "adobe_downloader.core.api_client.fetch_token"
    ), patch("adobe_downloader.core.api_client.httpx.AsyncClient"):
        mock_creds.return_value = {
            "adobe": {
                "clientID": "cid",
                "clientSecret": "csec",
                "adobeOrgID": "org",
                "globalCompanyID": "company",
            }
        }
        return AdobeClient("TestClient")


# ---------------------------------------------------------------------------
# get_dimensions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_dimensions_returns_list() -> None:
    """get_dimensions returns the full list from the API response."""
    client = _make_client()
    dimensions = [
        {"id": "variables/browser", "name": "Browser", "type": "string"},
        {"id": "variables/evar2.pagetag", "name": "Page Tag", "type": "string"},
    ]
    with patch.object(client, "_get", new=AsyncMock(return_value=_make_response(dimensions))):
        result = await client.get_dimensions("myrsid")
    assert result == dimensions


@pytest.mark.asyncio
async def test_get_dimensions_includes_classifications() -> None:
    """Classification dimensions (with dot in ID) are included, not filtered out."""
    client = _make_client()
    dimensions = [
        {"id": "variables/evar1", "name": "eVar 1", "type": "string"},
        {"id": "variables/evar1.category", "name": "Category", "type": "string"},
        {"id": "variables/evar1.subcategory", "name": "Sub Category", "type": "string"},
    ]
    with patch.object(client, "_get", new=AsyncMock(return_value=_make_response(dimensions))):
        result = await client.get_dimensions("myrsid")
    assert len(result) == 3
    ids = [d["id"] for d in result]
    assert "variables/evar1.category" in ids
    assert "variables/evar1.subcategory" in ids


@pytest.mark.asyncio
async def test_get_dimensions_passes_rsid_and_expansion() -> None:
    """get_dimensions calls the API with rsid and expansion=support params."""
    client = _make_client()
    mock_get = AsyncMock(return_value=_make_response([]))
    with patch.object(client, "_get", new=mock_get):
        await client.get_dimensions("trillioncoverscom")
    call_kwargs = mock_get.call_args
    url = call_kwargs.args[0]
    params = call_kwargs.kwargs.get("params", {})
    assert "dimensions" in url
    assert params.get("rsid") == "trillioncoverscom"
    assert params.get("expansion") == "support"


# ---------------------------------------------------------------------------
# get_metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_metrics_returns_list() -> None:
    """get_metrics returns the full list from the API response."""
    client = _make_client()
    metrics = [
        {"id": "metrics/pageviews", "name": "Page Views", "type": "int"},
        {"id": "metrics/event3", "name": "Event 3", "type": "int"},
    ]
    with patch.object(client, "_get", new=AsyncMock(return_value=_make_response(metrics))):
        result = await client.get_metrics("myrsid")
    assert result == metrics


@pytest.mark.asyncio
async def test_get_metrics_passes_rsid() -> None:
    """get_metrics calls the API with the rsid param."""
    client = _make_client()
    mock_get = AsyncMock(return_value=_make_response([]))
    with patch.object(client, "_get", new=mock_get):
        await client.get_metrics("triadscasino")
    call_kwargs = mock_get.call_args
    url = call_kwargs.args[0]
    params = call_kwargs.kwargs.get("params", {})
    assert "metrics" in url
    assert params.get("rsid") == "triadscasino"


# ---------------------------------------------------------------------------
# get_calculated_metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_calculated_metrics_single_page() -> None:
    """get_calculated_metrics returns all items from a single-page response."""
    client = _make_client()
    payload = {
        "content": [
            {"id": "cm3938_abc", "name": "Engaged Visits"},
            {"id": "cm3938_def", "name": "Bot Rate"},
        ],
        "lastPage": True,
    }
    with patch.object(client, "_get", new=AsyncMock(return_value=_make_response(payload))):
        result = await client.get_calculated_metrics()
    assert len(result) == 2
    assert result[0]["id"] == "cm3938_abc"


@pytest.mark.asyncio
async def test_get_calculated_metrics_paginates() -> None:
    """get_calculated_metrics fetches all pages when lastPage is False."""
    client = _make_client()
    page0 = {"content": [{"id": "cm_1", "name": "Metric 1"}], "lastPage": False}
    page1 = {"content": [{"id": "cm_2", "name": "Metric 2"}], "lastPage": True}
    mock_get = AsyncMock(side_effect=[_make_response(page0), _make_response(page1)])
    with patch.object(client, "_get", new=mock_get):
        result = await client.get_calculated_metrics()
    assert len(result) == 2
    assert mock_get.call_count == 2


@pytest.mark.asyncio
async def test_get_calculated_metrics_list_response() -> None:
    """get_calculated_metrics handles a bare list response (non-paginated API behaviour)."""
    client = _make_client()
    payload = [{"id": "cm_x", "name": "Flat List Metric"}]
    with patch.object(client, "_get", new=AsyncMock(return_value=_make_response(payload))):
        result = await client.get_calculated_metrics()
    assert result == payload


@pytest.mark.asyncio
async def test_get_calculated_metrics_not_rsid_scoped() -> None:
    """get_calculated_metrics does not pass an rsid param."""
    client = _make_client()
    payload = {"content": [], "lastPage": True}
    mock_get = AsyncMock(return_value=_make_response(payload))
    with patch.object(client, "_get", new=mock_get):
        await client.get_calculated_metrics()
    call_kwargs = mock_get.call_args
    params = call_kwargs.kwargs.get("params", {})
    assert "rsid" not in params
