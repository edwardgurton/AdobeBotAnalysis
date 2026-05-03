"""RSID name-to-ID lookup from pipe-delimited report suite list files."""

from pathlib import Path


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
