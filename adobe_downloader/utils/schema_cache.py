"""Local file-based cache for Adobe Analytics dimension and metric metadata."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

_CACHE_ROOT = Path("data/schema_cache")
_DIM_DIR = _CACHE_ROOT / "dimensions"
_MET_DIR = _CACHE_ROOT / "metrics"
_CALC_FILE = _CACHE_ROOT / "calculated_metrics.json"
_INDEX_DIR = _CACHE_ROOT / "index"
_LAST_UPDATED_FILE = _INDEX_DIR / "last_updated.json"
_DIM_INDEX_FILE = _INDEX_DIR / "dimensions_index.md"
_MET_INDEX_FILE = _INDEX_DIR / "metrics_index.md"

_SEMANTIC_ROOT = Path("data/semantic_layer")

_SEMANTIC_FIELDS = ("display_name", "use_when", "preferred_over", "contexts", "notes")


def _ensure_dirs() -> None:
    for d in (_DIM_DIR, _MET_DIR, _INDEX_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Read / write per-RSID caches
# ---------------------------------------------------------------------------


def write_dimensions(rsid: str, dimensions: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    (_DIM_DIR / f"{rsid}.json").write_text(json.dumps(dimensions, indent=2), encoding="utf-8")
    _record_updated(f"dimensions/{rsid}")


def read_dimensions(rsid: str) -> list[dict[str, Any]] | None:
    p = _DIM_DIR / f"{rsid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[return-value]


def write_metrics(rsid: str, metrics: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    (_MET_DIR / f"{rsid}.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Semantic layer
# ---------------------------------------------------------------------------


def load_semantic_annotations(kind: str) -> dict[str, dict[str, Any]]:
    """Return {id: annotation_dict} from data/semantic_layer/{kind}s.yaml.

    kind: "dimension" or "metric". Returns {} if file absent or unparseable.
    Only the fields listed in _SEMANTIC_FIELDS are kept.
    """
    path = _SEMANTIC_ROOT / f"{kind}s.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        entry_id: str = entry.get("id", "")
        if not entry_id:
            continue
        result[entry_id] = {k: entry[k] for k in _SEMANTIC_FIELDS if k in entry}
    return result


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def search_schema(
    query: str,
    type_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Search cached dimensions and/or metrics for query substring.

    Args:
        query: Case-insensitive substring matched against id, name, description.
        type_filter: "dimension", "metric", or None (search both).

    Returns:
        List of result dicts sorted by id, each containing:
        id, name, type, description, rsids (list), kind (dimension/standard/calculated).
    """
    q = query.lower()
    results: dict[str, dict[str, Any]] = {}

    def _matches(item: dict[str, Any]) -> bool:
        return (
            q in item.get("id", "").lower()
            or q in item.get("name", "").lower()
            or q in item.get("description", "").lower()
        )

    if type_filter in (None, "dimension") and _DIM_DIR.exists():
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
                    by_id[dim_id] = {**dim, "rsids": [], "kind": "dimension"}
                by_id[dim_id]["rsids"].append(rsid)
        for item in by_id.values():
            if _matches(item):
                results[item["id"]] = item

    if type_filter in (None, "metric"):
        by_id_met: dict[str, dict[str, Any]] = {}
        if _MET_DIR.exists():
            for json_file in sorted(_MET_DIR.glob("*.json")):
                rsid = json_file.stem
                try:
                    mets: list[dict[str, Any]] = json.loads(json_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for met in mets:
                    met_id: str = met.get("id", "")
                    if not met_id:
                        continue
                    if met_id not in by_id_met:
                        by_id_met[met_id] = {**met, "rsids": [], "kind": "standard"}
                    by_id_met[met_id]["rsids"].append(rsid)
        for item in by_id_met.values():
            if _matches(item):
                results[item["id"]] = item

        if _CALC_FILE.exists():
            try:
                calc: list[dict[str, Any]] = json.loads(_CALC_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                calc = []
            for met in calc:
                met_id = met.get("id", "")
                if not met_id or met_id in results:
                    continue
                item = {**met, "rsids": [], "kind": "calculated"}
                if _matches(item):
                    results[met_id] = item

    # Inject semantic layer annotations (read-only join on local YAML, no API call)
    if type_filter in (None, "dimension"):
        for ann_id, ann in load_semantic_annotations("dimension").items():
            if ann_id in results:
                results[ann_id].update(ann)
    if type_filter in (None, "metric"):
        for ann_id, ann in load_semantic_annotations("metric").items():
            if ann_id in results:
                results[ann_id].update(ann)

    return sorted(results.values(), key=lambda x: x.get("id", ""))


# ---------------------------------------------------------------------------
# Cache status
# ---------------------------------------------------------------------------


def cache_status(ttl_days: int = 30) -> dict[str, Any]:
    """Return freshness information for all cached RSIDs.

    Returns a dict:
        {
            "dimensions": {rsid: {"updated": str|None, "fresh": bool, "days_old": int|None}},
            "metrics":    {rsid: ...},
            "calculated_metrics": {"updated": str|None, "fresh": bool, "days_old": int|None},
        }
    """
    last_updated = _read_last_updated()
    today = date.today()

    def _entry(key: str) -> dict[str, Any]:
        updated = last_updated.get(key)
        if updated is None:
            return {"updated": None, "fresh": False, "days_old": None}
        last = date.fromisoformat(updated)
        days_old = (today - last).days
        return {"updated": updated, "fresh": days_old < ttl_days, "days_old": days_old}

    dim_rsids = sorted(f.stem for f in _DIM_DIR.glob("*.json")) if _DIM_DIR.exists() else []
    met_rsids = sorted(f.stem for f in _MET_DIR.glob("*.json")) if _MET_DIR.exists() else []

    return {
        "dimensions": {rsid: _entry(f"dimensions/{rsid}") for rsid in dim_rsids},
        "metrics": {rsid: _entry(f"metrics/{rsid}") for rsid in met_rsids},
        "calculated_metrics": _entry("calculated_metrics"),
    }
