"""Tests for adobe_downloader/utils/schema_cache.py — Step 21."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import adobe_downloader.utils.schema_cache as schema_cache
from adobe_downloader.utils.schema_cache import (
    calculated_metrics_stale,
    dimensions_stale,
    is_stale,
    metrics_stale,
    read_calculated_metrics,
    read_dimensions,
    read_metrics,
    rebuild_index,
    write_calculated_metrics,
    write_dimensions,
    write_metrics,
)

_SAMPLE_DIMS: list[dict[str, Any]] = [
    {"id": "variables/browser", "name": "Browser", "type": "string", "description": "Browser used"},
    {
        "id": "variables/evar2.pagetag",
        "name": "Page Tag",
        "type": "string",
        "description": "GTM tag name",
    },
]

_SAMPLE_METRICS: list[dict[str, Any]] = [
    {"id": "metrics/pageviews", "name": "Page Views", "type": "int", "description": ""},
    {"id": "metrics/event3", "name": "Event 3", "type": "int", "description": ""},
]

_SAMPLE_CALC: list[dict[str, Any]] = [
    {"id": "cm3938_abc", "name": "Engaged Visits", "type": "calculated", "description": ""},
]


@pytest.fixture(autouse=True)
def _patch_cache_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all schema_cache paths to a temp directory."""
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


# ---------------------------------------------------------------------------
# Dimensions read/write round-trip
# ---------------------------------------------------------------------------


def test_write_read_dimensions_round_trip() -> None:
    write_dimensions("rsid_a", _SAMPLE_DIMS)
    result = read_dimensions("rsid_a")
    assert result == _SAMPLE_DIMS


def test_read_dimensions_missing_returns_none() -> None:
    assert read_dimensions("nonexistent_rsid") is None


def test_write_dimensions_creates_json_file(tmp_path: Path) -> None:
    write_dimensions("rsid_b", _SAMPLE_DIMS)
    json_file = schema_cache._DIM_DIR / "rsid_b.json"
    assert json_file.exists()
    loaded = json.loads(json_file.read_text(encoding="utf-8"))
    assert loaded == _SAMPLE_DIMS


# ---------------------------------------------------------------------------
# Metrics read/write round-trip
# ---------------------------------------------------------------------------


def test_write_read_metrics_round_trip() -> None:
    write_metrics("rsid_a", _SAMPLE_METRICS)
    result = read_metrics("rsid_a")
    assert result == _SAMPLE_METRICS


def test_read_metrics_missing_returns_none() -> None:
    assert read_metrics("nonexistent_rsid") is None


# ---------------------------------------------------------------------------
# Calculated metrics read/write round-trip
# ---------------------------------------------------------------------------


def test_write_read_calculated_metrics_round_trip() -> None:
    write_calculated_metrics(_SAMPLE_CALC)
    result = read_calculated_metrics()
    assert result == _SAMPLE_CALC


def test_read_calculated_metrics_missing_returns_none() -> None:
    assert read_calculated_metrics() is None


# ---------------------------------------------------------------------------
# TTL / staleness
# ---------------------------------------------------------------------------


def test_is_stale_missing_key_returns_true() -> None:
    assert is_stale("dimensions/rsid_x", ttl_days=30) is True


def test_is_stale_fresh_entry_returns_false() -> None:
    write_dimensions("rsid_fresh", _SAMPLE_DIMS)
    assert dimensions_stale("rsid_fresh", ttl_days=30) is False


def test_is_stale_old_entry_returns_true(tmp_path: Path) -> None:
    write_dimensions("rsid_old", _SAMPLE_DIMS)
    # Override the recorded date to be 31 days ago
    old_date = (date.today() - timedelta(days=31)).isoformat()
    last_updated = schema_cache._LAST_UPDATED_FILE
    data = json.loads(last_updated.read_text(encoding="utf-8"))
    data["dimensions/rsid_old"] = old_date
    last_updated.write_text(json.dumps(data), encoding="utf-8")
    assert dimensions_stale("rsid_old", ttl_days=30) is True


def test_is_stale_exactly_at_ttl_returns_true() -> None:
    write_dimensions("rsid_edge", _SAMPLE_DIMS)
    edge_date = (date.today() - timedelta(days=30)).isoformat()
    last_updated = schema_cache._LAST_UPDATED_FILE
    data = json.loads(last_updated.read_text(encoding="utf-8"))
    data["dimensions/rsid_edge"] = edge_date
    last_updated.write_text(json.dumps(data), encoding="utf-8")
    # exactly 30 days old, ttl_days=30 → stale
    assert dimensions_stale("rsid_edge", ttl_days=30) is True


def test_metrics_stale_fresh() -> None:
    write_metrics("rsid_m", _SAMPLE_METRICS)
    assert metrics_stale("rsid_m", ttl_days=7) is False


def test_calculated_metrics_stale_fresh() -> None:
    write_calculated_metrics(_SAMPLE_CALC)
    assert calculated_metrics_stale(ttl_days=30) is False


def test_calculated_metrics_stale_missing() -> None:
    assert calculated_metrics_stale(ttl_days=30) is True


# ---------------------------------------------------------------------------
# rebuild_index — dimensions
# ---------------------------------------------------------------------------


def test_rebuild_index_creates_files() -> None:
    write_dimensions("rsid_a", _SAMPLE_DIMS)
    rebuild_index()
    assert schema_cache._DIM_INDEX_FILE.exists()
    assert schema_cache._MET_INDEX_FILE.exists()


def test_rebuild_dimensions_index_contains_dimension_id() -> None:
    write_dimensions("rsid_a", _SAMPLE_DIMS)
    rebuild_index()
    content = schema_cache._DIM_INDEX_FILE.read_text(encoding="utf-8")
    assert "variables/browser" in content
    assert "Browser" in content


def test_rebuild_dimensions_index_classification_flagged() -> None:
    write_dimensions("rsid_a", _SAMPLE_DIMS)
    rebuild_index()
    content = schema_cache._DIM_INDEX_FILE.read_text(encoding="utf-8")
    # Page Tag is a classification (has dot in local part)
    assert "variables/evar2.pagetag" in content
    assert "Classification: Yes" in content
    assert "Parent: variables/evar2" in content


def test_rebuild_dimensions_index_non_classification_flagged() -> None:
    write_dimensions("rsid_a", _SAMPLE_DIMS)
    rebuild_index()
    content = schema_cache._DIM_INDEX_FILE.read_text(encoding="utf-8")
    # variables/browser has no dot — should be Classification: No
    browser_section = content[content.index("variables/browser"):]
    first_type_line = next(
        line for line in browser_section.splitlines() if line.startswith("Type:")
    )
    assert "Classification: No" in first_type_line


def test_rebuild_dimensions_index_cross_rsid() -> None:
    """Dimensions present in multiple RSIDs show all RSIDs."""
    shared_dim = [{"id": "variables/browser", "name": "Browser", "type": "string"}]
    write_dimensions("rsid_x", shared_dim)
    write_dimensions("rsid_y", shared_dim)
    rebuild_index()
    content = schema_cache._DIM_INDEX_FILE.read_text(encoding="utf-8")
    rsid_line = next(
        line for line in content.splitlines() if line.startswith("RSIDs:") and "rsid_x" in line
    )
    assert "rsid_x" in rsid_line
    assert "rsid_y" in rsid_line


# ---------------------------------------------------------------------------
# rebuild_index — metrics
# ---------------------------------------------------------------------------


def test_rebuild_metrics_index_standard_metric() -> None:
    write_metrics("rsid_a", _SAMPLE_METRICS)
    rebuild_index()
    content = schema_cache._MET_INDEX_FILE.read_text(encoding="utf-8")
    assert "metrics/pageviews" in content
    assert "Page Views" in content
    assert "Kind: standard" in content


def test_rebuild_metrics_index_calculated_metric_company_wide() -> None:
    write_calculated_metrics(_SAMPLE_CALC)
    rebuild_index()
    content = schema_cache._MET_INDEX_FILE.read_text(encoding="utf-8")
    assert "cm3938_abc" in content
    assert "Engaged Visits" in content
    assert "company-wide" in content
    assert "Kind: calculated" in content


def test_rebuild_index_empty_cache_produces_valid_files() -> None:
    """rebuild_index with no data should produce valid (empty body) index files."""
    rebuild_index()
    dim_content = schema_cache._DIM_INDEX_FILE.read_text(encoding="utf-8")
    met_content = schema_cache._MET_INDEX_FILE.read_text(encoding="utf-8")
    assert "# Dimensions Index" in dim_content
    assert "# Metrics Index" in met_content
