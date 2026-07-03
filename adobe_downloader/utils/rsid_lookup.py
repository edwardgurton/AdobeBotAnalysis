"""RSID name-to-ID lookup from pipe-delimited report suite list files."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPORT_SUITE_LISTS_DIR = _REPO_ROOT / "data" / "report_suite_lists"


def load_rsid_lookup(file_path: Path) -> dict[str, str]:
    """Load a report suites file into a {clean_name: rsid} dict.

    File format (colon-separated): ``rsid:CleanName``
    """
    mapping: dict[str, str] = {}
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        rsid, clean_name = line.split(":", 1)
        mapping[clean_name.strip()] = rsid.strip()
    return mapping


def find_latest_rsid_file(rsid_dir: Path) -> Path | None:
    """Return the most recently modified .txt file in *rsid_dir*."""
    candidates = [
        p for p in rsid_dir.glob("*.txt") if not p.name.startswith("_")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def lookup_rsid(clean_name: str, file_path: Path) -> str | None:
    """Return the rsid for *clean_name*, or ``None`` if not found."""
    mapping = load_rsid_lookup(file_path)
    # Try exact match first, then case-insensitive
    if clean_name in mapping:
        return mapping[clean_name]
    lower = clean_name.lower()
    for k, v in mapping.items():
        if k.lower() == lower:
            return v
    return None


def resolve_rsid_names(
    rsid_list: list[str],
    rsid_dir: Path | None = None,
) -> list[str]:
    """Resolve any clean names in *rsid_list* to real RSIDs.

    Values that are already RSIDs (not found as clean names) pass through unchanged.
    Uses the most recently modified file in *rsid_dir* (defaults to
    data/report_suite_lists/).
    """
    lookup_dir = rsid_dir if rsid_dir is not None else _REPORT_SUITE_LISTS_DIR
    latest = find_latest_rsid_file(lookup_dir)
    if latest is None:
        return rsid_list
    mapping = load_rsid_lookup(latest)
    resolved: list[str] = []
    for name in rsid_list:
        lower = name.lower()
        match = mapping.get(name) or next(
            (v for k, v in mapping.items() if k.lower() == lower), None
        )
        resolved.append(match if match is not None else name)
    return resolved
