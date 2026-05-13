"""Tests for the `schema` CLI command group — Step 23."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

import adobe_downloader.utils.schema_cache as schema_cache
from adobe_downloader.cli import main

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_DIMS: list[dict[str, Any]] = [
    {"id": "variables/browser", "name": "Browser", "type": "string", "description": "Browser type"},
    {"id": "variables/geocountry", "name": "Countries", "type": "string", "description": ""},
]
_METS: list[dict[str, Any]] = [
    {"id": "metrics/pageviews", "name": "Page Views", "type": "int", "description": ""},
    {"id": "metrics/visits", "name": "Visits", "type": "int", "description": "Visit count"},
]
_CALC: list[dict[str, Any]] = [
    {"id": "cm3938_abc", "name": "Engaged Visits", "type": "calculated", "description": ""},
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all schema_cache file operations to a temp directory."""
    cache = tmp_path / "schema_cache"
    monkeypatch.setattr(schema_cache, "_CACHE_ROOT", cache)
    monkeypatch.setattr(schema_cache, "_DIM_DIR", cache / "dimensions")
    monkeypatch.setattr(schema_cache, "_MET_DIR", cache / "metrics")
    monkeypatch.setattr(schema_cache, "_CALC_FILE", cache / "calculated_metrics.json")
    monkeypatch.setattr(schema_cache, "_INDEX_DIR", cache / "index")
    monkeypatch.setattr(schema_cache, "_LAST_UPDATED_FILE", cache / "index" / "last_updated.json")
    monkeypatch.setattr(schema_cache, "_DIM_INDEX_FILE", cache / "index" / "dimensions_index.md")
    monkeypatch.setattr(schema_cache, "_MET_INDEX_FILE", cache / "index" / "metrics_index.md")
    monkeypatch.setattr(schema_cache, "_SEMANTIC_ROOT", tmp_path / "semantic_layer")


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _write_schema_config(tmp_path: Path) -> Path:
    config = tmp_path / "schema.yaml"
    config.write_text(
        "job_type: schema_discovery\n"
        "client: TestClient\n"
        "rsids:\n"
        "  source: single\n"
        "  single: rsid_a\n",
        encoding="utf-8",
    )
    return config


def _write_wrong_config(tmp_path: Path) -> Path:
    config = tmp_path / "report_download.yaml"
    config.write_text(
        "job_type: report_download\n"
        "client: TestClient\n"
        "rsids:\n"
        "  source: single\n"
        "  single: rsid_a\n"
        "date_range:\n"
        "  from: '2025-01-01'\n"
        "  to: '2025-01-31'\n"
        "report:\n"
        "  name: toplineMetrics\n"
        "  metrics: [metrics/visits]\n"
        "  csv_headers: [Visits]\n"
        "output:\n"
        "  base_folder: /tmp/out\n",
        encoding="utf-8",
    )
    return config


# ---------------------------------------------------------------------------
# schema --help
# ---------------------------------------------------------------------------


def test_schema_group_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["schema", "--help"])
    assert result.exit_code == 0
    assert "fetch" in result.output
    assert "search" in result.output
    assert "status" in result.output


def test_schema_fetch_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["schema", "fetch", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output


def test_schema_search_help(runner: CliRunner) -> None:
    result = runner.invoke(main, ["schema", "search", "--help"])
    assert result.exit_code == 0
    assert "--query" in result.output
    assert "--type" in result.output


# ---------------------------------------------------------------------------
# schema fetch
# ---------------------------------------------------------------------------


def test_schema_fetch_wrong_job_type(runner: CliRunner, tmp_path: Path) -> None:
    config = _write_wrong_config(tmp_path)
    result = runner.invoke(main, ["schema", "fetch", "-c", str(config)])
    assert result.exit_code == 1
    assert "schema_discovery" in result.output


def test_schema_fetch_success(runner: CliRunner, tmp_path: Path) -> None:
    config = _write_schema_config(tmp_path)

    mock_client = MagicMock()
    mock_client.get_dimensions = AsyncMock(return_value=_DIMS)
    mock_client.get_metrics = AsyncMock(return_value=_METS)
    mock_client.get_calculated_metrics = AsyncMock(return_value=_CALC)
    mock_client.close = AsyncMock()

    with (
        patch("adobe_downloader.core.api_client.AdobeClient", return_value=mock_client),
        patch(
            "adobe_downloader.flows.schema_discovery.run_schema_discovery", new=AsyncMock()
        ) as mock_run,
    ):
        result = runner.invoke(main, ["schema", "fetch", "-c", str(config)])

    assert result.exit_code == 0, result.output
    assert "Schema cache updated" in result.output
    assert "TestClient" in result.output
    mock_run.assert_awaited_once()


def test_schema_fetch_credential_error(runner: CliRunner, tmp_path: Path) -> None:
    config = _write_schema_config(tmp_path)

    with patch(
        "adobe_downloader.core.api_client.AdobeClient",
        side_effect=FileNotFoundError("credentials not found"),
    ):
        result = runner.invoke(main, ["schema", "fetch", "-c", str(config)])

    assert result.exit_code == 1
    assert "credentials not found" in result.output


# ---------------------------------------------------------------------------
# schema search — empty cache
# ---------------------------------------------------------------------------


def test_schema_search_empty_cache(runner: CliRunner) -> None:
    result = runner.invoke(main, ["schema", "search", "--query", "browser"])
    assert result.exit_code == 0
    assert "No matches" in result.output


# ---------------------------------------------------------------------------
# schema search — with populated cache
# ---------------------------------------------------------------------------


def test_schema_search_dimension_match(runner: CliRunner) -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    result = runner.invoke(main, ["schema", "search", "--query", "browser"])
    assert result.exit_code == 0
    assert "browser" in result.output.lower()
    assert "Browser" in result.output
    assert "dimension" in result.output


def test_schema_search_metric_match(runner: CliRunner) -> None:
    schema_cache.write_metrics("rsid_a", _METS)
    result = runner.invoke(main, ["schema", "search", "--query", "visits"])
    assert result.exit_code == 0
    assert "visits" in result.output.lower()
    assert "standard" in result.output


def test_schema_search_type_filter_dimension_excludes_metrics(runner: CliRunner) -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    schema_cache.write_metrics("rsid_a", _METS)
    result = runner.invoke(main, ["schema", "search", "--query", "browser", "--type", "dimension"])
    assert result.exit_code == 0
    assert "dimension" in result.output
    assert "standard" not in result.output


def test_schema_search_type_filter_metric_excludes_dimensions(runner: CliRunner) -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    schema_cache.write_metrics("rsid_a", _METS)
    result = runner.invoke(main, ["schema", "search", "--query", "visits", "--type", "metric"])
    assert result.exit_code == 0
    assert "standard" in result.output
    assert "dimension" not in result.output


def test_schema_search_no_matches(runner: CliRunner) -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    result = runner.invoke(main, ["schema", "search", "--query", "zzz_nonexistent"])
    assert result.exit_code == 0
    assert "No matches" in result.output


def test_schema_search_calculated_metric(runner: CliRunner) -> None:
    schema_cache.write_calculated_metrics(_CALC)
    result = runner.invoke(main, ["schema", "search", "--query", "engaged"])
    assert result.exit_code == 0
    assert "calculated" in result.output
    assert "company-wide" in result.output


# ---------------------------------------------------------------------------
# schema status
# ---------------------------------------------------------------------------


def test_schema_status_empty_cache(runner: CliRunner) -> None:
    result = runner.invoke(main, ["schema", "status"])
    assert result.exit_code == 0
    assert "No dimension cache entries" in result.output
    assert "No metric cache entries" in result.output


def test_schema_status_fresh(runner: CliRunner) -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    schema_cache.write_metrics("rsid_a", _METS)
    result = runner.invoke(main, ["schema", "status"])
    assert result.exit_code == 0
    assert "FRESH" in result.output
    assert "rsid_a" in result.output


def test_schema_status_stale_with_zero_ttl(runner: CliRunner) -> None:
    schema_cache.write_dimensions("rsid_a", _DIMS)
    result = runner.invoke(main, ["schema", "status", "--ttl", "0"])
    assert result.exit_code == 0
    assert "STALE" in result.output


# ---------------------------------------------------------------------------
# schema search — semantic layer
# ---------------------------------------------------------------------------


def test_schema_search_no_semantic_layer(runner: CliRunner) -> None:
    """No dimensions.yaml → results show no semantic fields."""
    schema_cache.write_dimensions("rsid_a", _DIMS)
    result = runner.invoke(main, ["schema", "search", "--query", "browser"])
    assert result.exit_code == 0
    assert "Display Name" not in result.output
    assert "Use When" not in result.output


def test_schema_search_with_dimension_semantic_layer(runner: CliRunner, tmp_path: Path) -> None:
    """dimensions.yaml present → annotated dimension gains semantic fields."""
    sem_dir = tmp_path / "semantic_layer"
    sem_dir.mkdir(parents=True, exist_ok=True)
    (sem_dir / "dimensions.yaml").write_text(
        "- id: variables/browser\n"
        "  display_name: Browser Type\n"
        "  use_when: Segment by browser vendor\n"
        "  contexts: [bot_investigation]\n"
        "  notes: Use browsertype lookup for IDs\n",
        encoding="utf-8",
    )
    schema_cache.write_dimensions("rsid_a", _DIMS)
    result = runner.invoke(main, ["schema", "search", "--query", "browser"])
    assert result.exit_code == 0
    assert "Browser Type" in result.output
    assert "Segment by browser vendor" in result.output
    assert "bot_investigation" in result.output
    assert "Use browsertype lookup for IDs" in result.output


def test_schema_search_partial_semantic_layer(runner: CliRunner, tmp_path: Path) -> None:
    """Only annotated IDs gain semantic fields; unannotated IDs are unaffected."""
    sem_dir = tmp_path / "semantic_layer"
    sem_dir.mkdir(parents=True, exist_ok=True)
    (sem_dir / "dimensions.yaml").write_text(
        "- id: variables/browser\n  display_name: Browser Type\n",
        encoding="utf-8",
    )
    schema_cache.write_dimensions("rsid_a", _DIMS)
    # geocountry is not annotated — searching it should not show Display Name
    result = runner.invoke(main, ["schema", "search", "--query", "geocountry"])
    assert result.exit_code == 0
    assert "Display Name" not in result.output


def test_schema_search_with_metric_semantic_layer(runner: CliRunner, tmp_path: Path) -> None:
    """metrics.yaml present → annotated metric gains semantic fields."""
    sem_dir = tmp_path / "semantic_layer"
    sem_dir.mkdir(parents=True, exist_ok=True)
    (sem_dir / "metrics.yaml").write_text(
        "- id: metrics/visits\n  display_name: Sessions\n  use_when: Primary engagement metric\n",
        encoding="utf-8",
    )
    schema_cache.write_metrics("rsid_a", _METS)
    result = runner.invoke(main, ["schema", "search", "--query", "visits"])
    assert result.exit_code == 0
    assert "Sessions" in result.output
    assert "Primary engagement metric" in result.output
