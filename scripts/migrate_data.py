#!/usr/bin/env python3
"""
Step 0.5: Migrate data files from legacy_js/ to their target locations.

Run from the repo root:
    python scripts/migrate_data.py [--dry-run]

Reads from: legacy_js/
Writes to:  data/, jobs/inputs/, jobs/templates/, docs/reference/, credentials/

Never deletes source files. Migration is append-only.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY = REPO_ROOT / "legacy_js"
DRY_RUN = "--dry-run" in sys.argv

_log_lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    _log_lines.append(msg)


def _ensure_dir(path: Path) -> None:
    if not DRY_RUN:
        path.mkdir(parents=True, exist_ok=True)


def copy_file(src: Path, dst: Path) -> None:
    _ensure_dir(dst.parent)
    if not DRY_RUN:
        shutil.copy2(src, dst)
    prefix = "[dry] " if DRY_RUN else ""
    log(f"  {prefix}copy  {src.relative_to(REPO_ROOT)}  ->  {dst.relative_to(REPO_ROOT)}")


def write_text(dst: Path, content: str) -> None:
    _ensure_dir(dst.parent)
    if not DRY_RUN:
        dst.write_text(content, encoding="utf-8")
    prefix = "[dry] " if DRY_RUN else ""
    log(f"  {prefix}write {dst.relative_to(REPO_ROOT)}")


def write_json(dst: Path, data: object) -> None:
    write_text(dst, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


# ── JS parsing helpers ─────────────────────────────────────────────────────────


def extract_js_string_array(js_text: str) -> list[str]:
    """Extract uncommented string values from a JS const string array."""
    results = []
    for line in js_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        for m in re.findall(r"'([^']*)'", stripped):
            if m:
                results.append(m)
    return results


def extract_js_object_array(js_text: str) -> list[dict]:
    """Extract a JSON-compatible object array from a JS const declaration."""
    start = js_text.index("[")
    end = js_text.rindex("]") + 1
    return json.loads(js_text[start:end])


def extract_js_header_string(js_text: str) -> str:
    """Extract the CSV headers value from a JS header file, skipping comment lines."""
    for line in js_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        m = re.search(r"let\s+headers\s*=\s*'([^']+)'", stripped)
        if m:
            return m.group(1)
    raise ValueError("Could not extract headers string")


# ── Migration helpers ──────────────────────────────────────────────────────────


def migrate_string_array_js(src: Path, dst: Path) -> None:
    """Convert a JS string array to a plain-text file (one entry per line)."""
    entries = extract_js_string_array(src.read_text(encoding="utf-8"))
    write_text(dst, "\n".join(entries) + "\n")


def migrate_object_array_js(src: Path, dst: Path) -> None:
    """Convert a JS JSON-compatible object array to a .json file."""
    try:
        data = extract_js_object_array(src.read_text(encoding="utf-8"))
        write_json(dst, data)
    except (json.JSONDecodeError, ValueError) as exc:
        log(f"  WARN  could not parse {src.name}: {exc} — skipping")


def migrate_header_js(src: Path, report_name: str, dst: Path) -> None:
    """Convert a JS header file to a YAML file with a columns list."""
    try:
        header_str = extract_js_header_string(src.read_text(encoding="utf-8"))
    except ValueError as exc:
        log(f"  WARN  {src.relative_to(REPO_ROOT)}: {exc} — skipping")
        return
    columns = [c.strip() for c in header_str.split(",") if c.strip()]
    lines = [f"report_name: {report_name}", "columns:"]
    lines.extend(f"  - {col}" for col in columns)
    write_text(dst, "\n".join(lines) + "\n")


def migrate_plain_dir(src_dir: Path, dst_dir: Path, pattern: str = "*") -> None:
    """Copy all files matching pattern from src_dir into dst_dir."""
    for src in sorted(src_dir.glob(pattern)):
        if src.is_file():
            copy_file(src, dst_dir / src.name)


# ── Main ───────────────────────────────────────────────────────────────────────


def main() -> None:
    if DRY_RUN:
        log("=== DRY RUN — no files will be written ===\n")

    # 1. RSID list JS files → data/rsid_lists/*.txt
    log("\n[1] RSID list JS files -> data/rsid_lists/")
    legend_info = LEGACY / "usefulInfo" / "Legend"
    rsid_dst = REPO_ROOT / "data" / "rsid_lists"
    string_array_files = [
        "rsidList",
        "rsidListIterateCountries",
        "rsidListOneReportOnly",
        "rsidListTesting",
        "botValidationRsidList",
        "botInvestigationMinThresholdVisits",
        "excludedRsidCleanNames",
        "StringsForCountries",
    ]
    for name in string_array_files:
        src = legend_info / f"{name}.js"
        if src.exists():
            migrate_string_array_js(src, rsid_dst / f"{name}.txt")
        else:
            log(f"  SKIP  {name}.js — not found")

    # 2. Object-array JS files → JSON
    log("\n[2] Object-array JS files -> JSON")
    migrate_object_array_js(
        legend_info / "countrySegmentLookup.js",
        REPO_ROOT / "data" / "country_segment_lookup.json",
    )
    migrate_object_array_js(
        legend_info / "botInvestigationRsidCountriesMinThreshold.js",
        REPO_ROOT / "data" / "rsid_country_thresholds" / "botInvestigationRsidCountriesMinThreshold.json",
    )

    # 3. Header JS files → data/report_headers/*.yaml
    log("\n[3] Header JS files -> data/report_headers/")
    headers_src = LEGACY / "config" / "headers"
    headers_dst = REPO_ROOT / "data" / "report_headers"
    for report_dir in sorted(headers_src.iterdir()):
        if not report_dir.is_dir():
            continue
        legend_js = report_dir / "Legend.js"
        if legend_js.exists():
            migrate_header_js(legend_js, report_dir.name, headers_dst / f"{report_dir.name}.yaml")
        capita_js = report_dir / "Capita.js"
        if capita_js.exists():
            # Archived — copy verbatim, no conversion
            copy_file(capita_js, headers_dst / "_archive" / f"{report_dir.name}_Capita.js")

    # 4. Segment list JSONs → data/segment_lists/Legend/
    log("\n[4] Segment list JSONs -> data/segment_lists/Legend/")
    migrate_plain_dir(
        LEGACY / "config" / "segmentLists" / "Legend",
        REPO_ROOT / "data" / "segment_lists" / "Legend",
        "*.json",
    )

    # 5. Dimension lookup files → data/lookups/{dim}/lookup.txt
    log("\n[5] Dimension lookup files -> data/lookups/")
    for dim in [
        "variablesbrowsertype",
        "variablesmarketingchannel",
        "variablesmonitorresolution",
        "variablesgeoregion",
    ]:
        src = legend_info / dim / "lookup.txt"
        if src.exists():
            copy_file(src, REPO_ROOT / "data" / "lookups" / dim / "lookup.txt")
        else:
            log(f"  SKIP  {dim}/lookup.txt — not found")

    # 6. Saved segment JSONs → data/saved_segments/
    log("\n[6] Saved segment JSONs -> data/saved_segments/")
    migrate_plain_dir(
        legend_info / "Segments",
        REPO_ROOT / "data" / "saved_segments",
        "*.json",
    )

    # 7. User list JSONs → data/user_lists/
    log("\n[7] User list JSONs -> data/user_lists/")
    migrate_plain_dir(
        legend_info / "userLists",
        REPO_ROOT / "data" / "user_lists",
        "*.json",
    )

    # 8. Report suite lists → data/report_suite_lists/
    log("\n[8] Report suite lists -> data/report_suite_lists/")
    migrate_plain_dir(
        legend_info / "ReportSuiteLists",
        REPO_ROOT / "data" / "report_suite_lists",
        "*.txt",
    )
    # Root-level legendReportSuites.txt is an older snapshot — archive it
    rsl_root = legend_info / "legendReportSuites.txt"
    if rsl_root.exists():
        copy_file(rsl_root, REPO_ROOT / "data" / "report_suite_lists" / "_archive" / "legendReportSuites.txt")

    # 9. LegendUsefulIds.txt → data/
    log("\n[9] LegendUsefulIds.txt -> data/")
    lid = legend_info / "LegendUsefulIds.txt"
    if lid.exists():
        copy_file(lid, REPO_ROOT / "data" / "Legend_useful_ids.txt")

    # 10. Job input CSVs → jobs/inputs/
    log("\n[10] Job input CSVs -> jobs/inputs/")
    csv_map = {
        "BotRuleLists": "bot_rule_lists",
        "BotCompareLists": "bot_compare_lists",
        "segmentCreationLists": "segment_creation_lists",
    }
    for src_subdir, dst_subdir in csv_map.items():
        migrate_plain_dir(
            legend_info / src_subdir,
            REPO_ROOT / "jobs" / "inputs" / dst_subdir,
            "*.csv",
        )

    # 11. Client config template → jobs/templates/
    log("\n[11] Client config template -> jobs/templates/")
    copy_file(
        LEGACY / "config" / "client_configs" / "clientTemplate.yaml",
        REPO_ROOT / "jobs" / "templates" / "client_config_template.yaml",
    )

    # 12. Legend credentials → credentials/ (gitignored)
    log("\n[12] Legend credentials -> credentials/")
    legend_creds = LEGACY / "config" / "client_configs" / "clientLegend.yaml"
    if legend_creds.exists():
        copy_file(legend_creds, REPO_ROOT / "credentials" / "clientLegend.yaml")
    # Ensure credentials/ is in .gitignore
    gitignore = REPO_ROOT / ".gitignore"
    gitignore_text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if "credentials/" not in gitignore_text:
        if not DRY_RUN:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write("\n# OAuth credentials — never commit\ncredentials/\n")
        log("  added credentials/ to .gitignore")

    # 13. General reference docs → docs/reference/
    log("\n[13] General reference docs -> docs/reference/")
    for src_name, dst_name in [
        ("CommonMetrics", "common_metrics.md"),
        ("CommonDimensions", "common_dimensions.md"),
    ]:
        src = LEGACY / "usefulInfo" / "General" / src_name
        if src.exists():
            copy_file(src, REPO_ROOT / "docs" / "reference" / dst_name)
        else:
            log(f"  SKIP  {src_name} — not found")

    # 14. Write migration log
    log("\nDone. Migration complete.")
    log_path = REPO_ROOT / "data" / ".migration_log.txt"
    if not DRY_RUN:
        _ensure_dir(log_path.parent)
        log_path.write_text("\n".join(_log_lines) + "\n", encoding="utf-8")
        print(f"\nLog written to {log_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
