"""Tests for adobe_downloader/flows/schema_discovery.py — Step 22."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import adobe_downloader.utils.schema_cache as schema_cache
from adobe_downloader.config.schema import RsidSource, SchemaDiscoveryJobConfig
from adobe_downloader.flows.schema_discovery import run_schema_discovery

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DIMS: list[dict[str, Any]] = [
    {"id": "variables/browser", "name": "Browser", "type": "string", "description": ""}
]
_METS: list[dict[str, Any]] = [
    {"id": "metrics/pageviews", "name": "Page Views", "type": "int", "description": ""}
]
_CALC: list[dict[str, Any]] = [
    {"id": "cm3938_abc", "name": "Engaged Visits", "type": "calculated", "description": ""}
]


@pytest.fixture(autouse=True)
def _patch_cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema_cache, "_CACHE_ROOT", tmp_path / "schema_cache")
    monkeypatch.setattr(schema_cache, "_DIM_DIR", tmp_path / "schema_cache" / "dimensions")
    monkeypatch.setattr(schema_cache, "_MET_DIR", tmp_path / "schema_cache" / "metrics")
    monkeypatch.setattr(
        schema_cache, "_CALC_FILE", tmp_path / "schema_cache" / "calculated_metrics.json"
    )
    monkeypatch.setattr(schema_cache, "_INDEX_DIR", tmp_path / "schema_cache" / "index")
    monkeypatch.setattr(
        schema_cache,
        "_LAST_UPDATED_FILE",
        tmp_path / "schema_cache" / "index" / "last_updated.json",
    )
    monkeypatch.setattr(
        schema_cache,
        "_DIM_INDEX_FILE",
        tmp_path / "schema_cache" / "index" / "dimensions_index.md",
    )
    monkeypatch.setattr(
        schema_cache,
        "_MET_INDEX_FILE",
        tmp_path / "schema_cache" / "index" / "metrics_index.md",
    )


def _make_client() -> MagicMock:
    client = MagicMock()
    client.get_dimensions = AsyncMock(return_value=_DIMS)
    client.get_metrics = AsyncMock(return_value=_METS)
    client.get_calculated_metrics = AsyncMock(return_value=_CALC)
    return client


def _job(
    rsid: str = "rsid_a",
    mode: str = "both",
    cache_ttl_days: int = 30,
    force_refresh: bool = False,
) -> SchemaDiscoveryJobConfig:
    return SchemaDiscoveryJobConfig(
        job_type="schema_discovery",
        client="TestClient",
        rsids=RsidSource(source="single", single=rsid),
        mode=mode,  # type: ignore[arg-type]
        cache_ttl_days=cache_ttl_days,
        force_refresh=force_refresh,
    )


# ---------------------------------------------------------------------------
# mode="both" — stale cache triggers all fetches
# ---------------------------------------------------------------------------


async def test_both_mode_fetches_dims_metrics_calc_when_stale() -> None:
    client = _make_client()
    await run_schema_discovery(client, _job(mode="both"))

    client.get_dimensions.assert_awaited_once_with("rsid_a")
    client.get_metrics.assert_awaited_once_with("rsid_a")
    client.get_calculated_metrics.assert_awaited_once()


async def test_both_mode_writes_to_cache() -> None:
    client = _make_client()
    await run_schema_discovery(client, _job(mode="both"))

    assert schema_cache.read_dimensions("rsid_a") == _DIMS
    assert schema_cache.read_metrics("rsid_a") == _METS
    assert schema_cache.read_calculated_metrics() == _CALC


# ---------------------------------------------------------------------------
# Fresh cache — no API calls made
# ---------------------------------------------------------------------------


async def test_fresh_cache_skips_dimensions_fetch() -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    client = _make_client()
    await run_schema_discovery(client, _job(mode="dimensions"))

    client.get_dimensions.assert_not_awaited()


async def test_fresh_cache_skips_metrics_fetch() -> None:
    schema_cache.write_metrics("rsid_a", _METS)
    schema_cache.write_calculated_metrics(_CALC)
    client = _make_client()
    await run_schema_discovery(client, _job(mode="metrics"))

    client.get_metrics.assert_not_awaited()
    client.get_calculated_metrics.assert_not_awaited()


async def test_fresh_cache_no_api_calls_at_all() -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    schema_cache.write_metrics("rsid_a", _METS)
    schema_cache.write_calculated_metrics(_CALC)
    client = _make_client()
    await run_schema_discovery(client, _job(mode="both"))

    client.get_dimensions.assert_not_awaited()
    client.get_metrics.assert_not_awaited()
    client.get_calculated_metrics.assert_not_awaited()


# ---------------------------------------------------------------------------
# force_refresh overrides fresh cache
# ---------------------------------------------------------------------------


async def test_force_refresh_fetches_despite_fresh_cache() -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    schema_cache.write_metrics("rsid_a", _METS)
    schema_cache.write_calculated_metrics(_CALC)
    client = _make_client()
    await run_schema_discovery(client, _job(mode="both", force_refresh=True))

    client.get_dimensions.assert_awaited_once_with("rsid_a")
    client.get_metrics.assert_awaited_once_with("rsid_a")
    client.get_calculated_metrics.assert_awaited_once()


# ---------------------------------------------------------------------------
# mode="dimensions" — only dimensions fetched
# ---------------------------------------------------------------------------


async def test_dimensions_mode_skips_metrics_and_calc() -> None:
    client = _make_client()
    await run_schema_discovery(client, _job(mode="dimensions"))

    client.get_dimensions.assert_awaited_once_with("rsid_a")
    client.get_metrics.assert_not_awaited()
    client.get_calculated_metrics.assert_not_awaited()


# ---------------------------------------------------------------------------
# mode="metrics" — only metrics + calculated fetched
# ---------------------------------------------------------------------------


async def test_metrics_mode_skips_dimensions() -> None:
    client = _make_client()
    await run_schema_discovery(client, _job(mode="metrics"))

    client.get_dimensions.assert_not_awaited()
    client.get_metrics.assert_awaited_once_with("rsid_a")
    client.get_calculated_metrics.assert_awaited_once()


# ---------------------------------------------------------------------------
# Multiple RSIDs
# ---------------------------------------------------------------------------


async def test_multiple_rsids_fetched_individually() -> None:
    job = SchemaDiscoveryJobConfig(
        job_type="schema_discovery",
        client="TestClient",
        rsids=RsidSource(source="list", list=["rsid_x", "rsid_y"]),
        mode="dimensions",
    )
    client = _make_client()
    await run_schema_discovery(client, job)

    assert client.get_dimensions.await_count == 2
    calls = [c.args[0] for c in client.get_dimensions.await_args_list]
    assert "rsid_x" in calls
    assert "rsid_y" in calls


async def test_multiple_rsids_calculated_metrics_fetched_once() -> None:
    """Calculated metrics are company-wide; only fetched once regardless of RSID count."""
    job = SchemaDiscoveryJobConfig(
        job_type="schema_discovery",
        client="TestClient",
        rsids=RsidSource(source="list", list=["rsid_x", "rsid_y"]),
        mode="metrics",
    )
    client = _make_client()
    await run_schema_discovery(client, job)

    client.get_calculated_metrics.assert_awaited_once()


# ---------------------------------------------------------------------------
# rebuild_index always called
# ---------------------------------------------------------------------------


async def test_rebuild_index_always_called() -> None:
    client = _make_client()
    with patch.object(schema_cache, "rebuild_index") as mock_rebuild:
        await run_schema_discovery(client, _job(mode="both"))
        mock_rebuild.assert_called_once()


async def test_rebuild_index_called_even_when_cache_fresh() -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    schema_cache.write_metrics("rsid_a", _METS)
    schema_cache.write_calculated_metrics(_CALC)
    client = _make_client()
    with patch.object(schema_cache, "rebuild_index") as mock_rebuild:
        await run_schema_discovery(client, _job(mode="both"))
        mock_rebuild.assert_called_once()


# ---------------------------------------------------------------------------
# SchemaDiscoveryJobConfig schema validation
# ---------------------------------------------------------------------------


def test_schema_discovery_config_defaults() -> None:
    job = _job()
    assert job.mode == "both"
    assert job.cache_ttl_days == 30
    assert job.force_refresh is False


def test_schema_discovery_config_mode_validation() -> None:
    with pytest.raises(Exception):
        SchemaDiscoveryJobConfig(
            job_type="schema_discovery",
            client="X",
            rsids=RsidSource(source="single", single="r"),
            mode="invalid",  # type: ignore[arg-type]
        )
