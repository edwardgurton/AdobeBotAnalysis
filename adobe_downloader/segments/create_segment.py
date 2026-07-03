"""Build Adobe Analytics segment definition dicts and resolve dimension values."""

import re
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Dimension mapping tables (originally ported from createSegmentFromList.js,
# now curated in data/segment_creation_dimensions.yaml — see `adobe-downloader
# add-dimension` to add a new one)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS_CONFIG_PATH = _REPO_ROOT / "data" / "segment_creation_dimensions.yaml"


def _load_dimension_config(
    path: Path,
) -> tuple[dict[str, str], dict[str, str], frozenset[str]]:
    """Build (mapping, descriptions, requires_lookup) from the dimension whitelist YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = raw.get("dimensions", []) if isinstance(raw, dict) else []

    mapping: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    requires_lookup: set[str] = set()
    for entry in entries:
        names: list[str] = entry["names"]
        adobe_variable: str = entry["adobe_variable"]
        description: str = entry.get("description", names[0])
        for name in names:
            mapping[name] = adobe_variable
            descriptions[name] = description
            if entry.get("requires_lookup", False):
                requires_lookup.add(name)
    return mapping, descriptions, frozenset(requires_lookup)


DIMENSION_MAPPING, DIMENSION_DESCRIPTIONS, DIMENSIONS_REQUIRING_LOOKUP = _load_dimension_config(
    DIMENSIONS_CONFIG_PATH
)

ALLOWED_DIMENSIONS: frozenset[str] = frozenset(DIMENSION_MAPPING.keys())


# ---------------------------------------------------------------------------
# Dimension helpers
# ---------------------------------------------------------------------------


def get_dimension_id(dimension: str) -> str | None:
    """Return the Adobe variable ID for *dimension*, or ``None``."""
    return DIMENSION_MAPPING.get(dimension.strip())


def get_dimension_description(dimension: str) -> str:
    """Return the description string used in segment predicates."""
    return DIMENSION_DESCRIPTIONS.get(dimension.strip(), dimension.strip())


def requires_lookup(dimension: str) -> bool:
    """Return ``True`` if *dimension* needs a numeric-ID lookup."""
    return dimension.strip() in DIMENSIONS_REQUIRING_LOOKUP


def normalize_monitor_resolution(value: str) -> str:
    """Normalise ``800x600`` → ``800 x 600`` (space around 'x')."""
    return re.sub(r"(\d+)\s*x\s*(\d+)", r"\1 x \2", value, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Lookup file
# ---------------------------------------------------------------------------


def load_lookup_file(lookup_path: Path) -> dict[str, str]:
    """Read a ``value|numericId`` lookup file, skipping comment lines."""
    result: dict[str, str] = {}
    if not lookup_path.exists():
        return result
    for line in lookup_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")):
            continue
        parts = stripped.split("|", 1)
        if len(parts) == 2:
            result[parts[0].strip()] = parts[1].strip()
    return result


def resolve_dimension_value(
    dimension: str,
    value: str,
    lookup_base: Path,
) -> tuple[str, bool]:
    """Return ``(resolved_value, is_numeric)`` for the given dimension/value.

    For numeric dimensions, looks up the local lookup file.  Raises
    ``LookupError`` if the value is not found and no API fallback is available.
    """
    processed = value
    if "monitor" in dimension.lower() or "resolution" in dimension.lower():
        processed = normalize_monitor_resolution(processed)

    if not requires_lookup(dimension):
        return processed, False

    adobe_dim = get_dimension_id(dimension)
    if not adobe_dim:
        raise ValueError(f"No Adobe dimension ID for: {dimension!r}")

    clean_dim = re.sub(r"[^a-zA-Z0-9]", "", adobe_dim)
    lookup_path = lookup_base / clean_dim / "lookup.txt"
    lookup = load_lookup_file(lookup_path)

    if processed in lookup:
        return lookup[processed], True

    raise LookupError(
        f"Value {processed!r} not found in lookup for dimension {dimension!r} "
        f"(file: {lookup_path}). Run 'search-lookup' to populate the lookup file."
    )


# ---------------------------------------------------------------------------
# Predicate builders
# ---------------------------------------------------------------------------


def _build_predicate(
    dimension: str,
    value: str,
    is_numeric: bool,
) -> dict:
    adobe_dim = get_dimension_id(dimension)
    if not adobe_dim:
        raise ValueError(f"No Adobe dimension ID for: {dimension!r}")
    desc = get_dimension_description(dimension)
    val_node = {"func": "attr", "name": adobe_dim}
    if is_numeric:
        return {"val": val_node, "func": "eq", "num": int(value), "description": desc}
    return {"str": value, "val": val_node, "description": desc, "func": "streq"}


# ---------------------------------------------------------------------------
# Segment definition builders
# ---------------------------------------------------------------------------


def build_single_condition_segment(
    name: str,
    rsid: str,
    dimension: str,
    value: str,
    is_numeric: bool,
) -> dict:
    """Return a segment definition dict for a single-predicate segment."""
    pred = _build_predicate(dimension, value, is_numeric)
    return {
        "name": name,
        "description": "",
        "definition": {
            "container": {
                "func": "container",
                "context": "visits",
                "pred": pred,
            },
            "func": "segment",
            "version": [1, 0, 0],
        },
        "isPostShardId": True,
        "rsid": rsid,
    }


def build_dual_condition_segment(
    name: str,
    rsid: str,
    dimension1: str,
    value1: str,
    is_numeric1: bool,
    dimension2: str,
    value2: str,
    is_numeric2: bool,
) -> dict:
    """Return a segment definition dict for an AND dual-predicate segment."""
    pred1 = _build_predicate(dimension1, value1, is_numeric1)
    pred2 = _build_predicate(dimension2, value2, is_numeric2)
    return {
        "name": name,
        "description": "",
        "definition": {
            "container": {
                "func": "container",
                "context": "visits",
                "pred": {
                    "func": "container",
                    "context": "hits",
                    "pred": {"func": "and", "preds": [pred1, pred2]},
                },
            },
            "func": "segment",
            "version": [1, 0, 0],
        },
        "isPostShardId": True,
        "rsid": rsid,
    }
