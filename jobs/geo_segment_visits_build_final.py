"""
Post-process the transform_all_concat.csv from geo_segment_visits_jun2026.yaml.

Reads the raw concat output and produces a clean CSV with:
  segment, report_suite, date, unique_visitors, visits, first_time_visits

Usage:
  python jobs/geo_segment_visits_build_final.py
"""

import re
import sys
from pathlib import Path

import pandas as pd

CONCAT_FILE = Path(
    "C:/Users/EdwardGurton/Documents/Work/Adobe Downloads/Legend/CSV/transform_all_concat.csv"
)
OUTPUT_FILE = Path(
    "C:/Users/EdwardGurton/Documents/Work/Adobe Downloads/geo_segment_visits_final.csv"
)

SEGMENT_MAP = {
    "cookie": "Cookie Banner Geos",
    "noncookie": "Non Cookie Banner Geos",
}
RSID_MAP = {
    "coverscom": "Covers",
    "sbr": "SBR (Sportsbook Review)",
    "adcom": "ADCOM (apuestasdeportivas)",
    "oddspedia": "Oddspedia",
}

_EXTRA_RE = re.compile(r"geoSegmentVisitsByDay_([^_]+)_\d{4}-\d{2}-\d{2}")


def parse_extra(filename: str) -> tuple[str, str]:
    m = _EXTRA_RE.search(str(filename))
    if not m:
        return "unknown", "unknown"
    extra = m.group(1)
    seg_raw, rsid_raw = extra.split("-", 1)
    return SEGMENT_MAP.get(seg_raw, seg_raw), RSID_MAP.get(rsid_raw, rsid_raw)


def main() -> None:
    if not CONCAT_FILE.exists():
        print(f"File not found: {CONCAT_FILE}", file=sys.stderr)
        print("Run the job first: adobe-downloader run -c jobs/geo_segment_visits_jun2026.yaml")
        sys.exit(1)

    df = pd.read_csv(CONCAT_FILE)
    df["segment"], df["report_suite"] = zip(*df["fileName"].apply(parse_extra))

    result = df[["segment", "report_suite", "day", "unique_visitors", "visits", "first_time_visits"]].rename(
        columns={"day": "date"}
    )
    result = result.sort_values(["segment", "report_suite", "date"]).reset_index(drop=True)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)
    print(f"Written {len(result):,} rows -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
