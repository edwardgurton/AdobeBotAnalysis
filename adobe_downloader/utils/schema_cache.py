"""Local file-based cache for Adobe Analytics dimension and metric metadata."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path("data/schema_cache")
_DIM_DIR = _CACHE_ROOT / "dimensions"
_MET_DIR = _CACHE_ROOT / "metrics"
_CALC_FILE = _CACHE_ROOT / "calculated_metrics.json"
_INDEX_DIR = _CACHE_ROOT / "index"
_LAST_UPDATED_FILE = _INDEX_DIR / "last_updated.json"
_DIM_INDEX_FILE = _INDEX_DIR / "dimensions_index.md"
_MET_INDEX_FILE = _INDEX_DIR / "metrics_index.md"


def _ensure_dirs() -> None:
    for d in (_DIM_DIR, _MET_DIR, _INDEX_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Read / write per-RSID caches
# ---------------------------------------------------------------------------


def write_dimensions(rsid: str, dimensions: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    (_DIM_DIR / f"{rsid}.json").write_text(
        json.dumps(dimensions, indent=2), encoding="utf-8"
    )
    _record_updated(f"dimensions/{rsid}")


def read_dimensions(rsid: str) -> list[dict[str, Any]] | None:
    p = _DIM_DIR / f"{rsid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[return-value]


def write_metrics(rsid: str, metrics: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    (_MET_DIR / f"{rsid}.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    _record_updated(f"metrics/{rsid}")


def read_metrics(rsid: str) -> list[dict[str, Any]] | None:
    p = _MET_DIR / f"{rsid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[return-value]


def write_calculated_metrics(metrics: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    _CALC_FILE.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    _record_updated("calculated_metrics")


def read_calculated_metrics() -> list[dict[str, Any]] | None:
    if not _CALC_FILE.exists():
        return None
    return json.loads(_CALC_FILE.read_text(encoding="utf-8"))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# TTL checking
# ---------------------------------------------------------------------------


def _record_updated(key: str) -> None:
    _ensure_dirs()
    data = _read_last_updated()
    data[key] = datetime.now(tz=timezone.utc).date().isoformat()
    _LAST_UPDATED_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_last_updated() -> dict[str, str]:
    if not _LAST_UPDATED_FILE.exists():
        return {}
    return json.loads(_LAST_UPDATED_FILE.read_text(encoding="utf-8"))  # type: ignore[return-value]


def is_stale(key: str, ttl_days: int) -> bool:
    """Return True if the cache entry is missing or older than ttl_days."""
    data = _read_last_updated()
    if key not in data:
        return True
    last = date.fromisoformat(data[key])
    return (date.today() - last).days >= ttl_days


def dimensions_stale(rsid: str, ttl_days: int) -> bool:
    return is_stale(f"dimensions/{rsid}", ttl_days)


def metrics_stale(rsid: str, ttl_days: int) -> bool:
    return is_stale(f"metrics/{rsid}", ttl_days)


def calculated_metrics_stale(ttl_days: int) -> bool:
    return is_stale("calculated_metrics", ttl_days)


# ---------------------------------------------------------------------------
# Index rebuild
# ---------------------------------------------------------------------------


def rebuild_index() -> None:
    """Regenerate the grep-friendly markdown index files from all cached JSON files."""
    _ensure_dirs()
    _rebuild_dimensions_index()
    _rebuild_metrics_index()


def _rebuild_dimensions_index() -> None:
    # Collect all dimensions across all RSIDs: id → {name, type, rsids, is_classification, parent}
    by_id: dict[str, dict[str, Any]] = {}

    for json_file in sorted(_DIM_DIR.glob("*.json")):
        rsid = json_file.stem
        try:
            dims: list[dict[str, Any]] = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for dim in dims:
            dim_id: str = dim.get("id", "")
            if not dim_id:
                continue
            if dim_id not in by_id:
                is_classification = "." in dim_id.split("/")[-1]
                parent = dim_id.rsplit(".", 1)[0] if is_classification else None
                by_id[dim_id] = {
                    "name": dim.get("name", dim_id),
                    "type": dim.get("type", "unknown"),
                    "rsids": [],
                    "is_classification": is_classification,
                    "parent": parent,
                    "description": dim.get("description", ""),
                }
            by_id[dim_id]["rsids"].append(rsid)

    lines = [
        "# Dimensions Index",
        f"Last updated: {date.today().isoformat()}",
        "",
        "Each entry lists the dimension ID, display name, the RSIDs where it is available,",
        "its type, and whether it is a classification of another dimension.",
        "This file is auto-generated — do not edit manually.",
        "",
    ]
    for dim_id, info in sorted(by_id.items()):
        classification_flag = "Yes" if info["is_classification"] else "No"
        parent_fragment = (
            f" | Parent: {info['parent']}" if info["is_classification"] and info["parent"] else ""
        )
        lines.append(f"## {dim_id} | {info['name']}")
        lines.append(f"RSIDs: {', '.join(sorted(info['rsids']))}")
        lines.append(
            f"Type: {info['type']} | Classification: {classification_flag}{parent_fragment}"
        )
        if info["description"]:
            lines.append(f"Description: {info['description']}")
        lines.append("")

    _DIM_INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")


def _rebuild_metrics_index() -> None:
    # Collect standard metrics per RSID
    by_id: dict[str, dict[str, Any]] = {}

    for json_file in sorted(_MET_DIR.glob("*.json")):
        rsid = json_file.stem
        try:
            metrics: list[dict[str, Any]] = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for met in metrics:
            met_id: str = met.get("id", "")
            if not met_id:
                continue
            if met_id not in by_id:
                by_id[met_id] = {
                    "name": met.get("name", met_id),
                    "type": met.get("type", "unknown"),
                    "rsids": [],
                    "description": met.get("description", ""),
                    "kind": "standard",
                }
            by_id[met_id]["rsids"].append(rsid)

    # Append calculated metrics (company-wide, no per-RSID association)
    if _CALC_FILE.exists():
        try:
            calc: list[dict[str, Any]] = json.loads(_CALC_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            calc = []
        for met in calc:
            met_id = met.get("id", "")
            if not met_id or met_id in by_id:
                continue
            by_id[met_id] = {
                "name": met.get("name", met_id),
                "type": "calculated",
                "rsids": [],
                "description": met.get("description", ""),
                "kind": "calculated",
            }

    lines = [
        "# Metrics Index",
        f"Last updated: {date.today().isoformat()}",
        "",
        "Each entry lists the metric ID, display name, the RSIDs where it is available",
        "(blank for calculated metrics, which are company-wide), its type, and kind",
        "(standard or calculated).",
        "This file is auto-generated — do not edit manually.",
        "",
    ]
    for met_id, info in sorted(by_id.items()):
        rsid_line = ", ".join(sorted(info["rsids"])) if info["rsids"] else "company-wide"
        lines.append(f"## {met_id} | {info['name']}")
        lines.append(f"RSIDs: {rsid_line}")
        lines.append(f"Type: {info['type']} | Kind: {info['kind']}")
        if info["description"]:
            lines.append(f"Description: {info['description']}")
        lines.append("")

    _MET_INDEX_FILE.write_text("\n".join(lines), encoding="utf-8")
