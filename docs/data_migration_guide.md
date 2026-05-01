# Data Migration Guide

Step 0.5 of the `adobe-downloader` build. Documents what was migrated from `legacy_js/`, where it went, and what format changes were made.

Run the migration at any time (idempotent, append-only — never deletes sources):

```
python scripts/migrate_data.py
python scripts/migrate_data.py --dry-run   # preview without writing
```

---

## Target directory layout

```
data/
  rsid_lists/             # RSID clean-name lists (plain text, one per line)
  country_segment_lookup.json
  rsid_country_thresholds/
  report_headers/         # Per-report CSV column definitions (YAML)
    _archive/             # Capita-specific header files (JS, no conversion)
  segment_lists/Legend/   # Segment list JSONs consumed by download jobs
  lookups/                # Dimension lookup files (pipe-delimited text)
    variablesbrowsertype/
    variablesmarketingchannel/
    variablesmonitorresolution/
    variablesgeoregion/
  saved_segments/         # Saved segment definition JSONs
  user_lists/             # Adobe user lists
  report_suite_lists/     # Dated RSID lists from Legend Report Suite Updater
    _archive/
  Legend_useful_ids.txt

jobs/
  inputs/
    bot_rule_lists/       # Bot rule CSVs (DimSegmentId + botRuleName columns)
    bot_compare_lists/    # Bot compare CSVs
    segment_creation_lists/ # Segment creation input CSVs
  templates/
    client_config_template.yaml

credentials/              # gitignored — never commit
  clientLegend.yaml

docs/reference/
  common_metrics.md
  common_dimensions.md
```

---

## What was migrated and how

### RSID lists (`data/rsid_lists/`)

Source: `legacy_js/usefulInfo/Legend/{name}.js` — JS `const` arrays of strings.

Conversion: JS string array → plain text, one entry per line, comment lines stripped.

| Source file | Target file |
|---|---|
| `rsidList.js` | `data/rsid_lists/rsidList.txt` |
| `rsidListIterateCountries.js` | `data/rsid_lists/rsidListIterateCountries.txt` |
| `rsidListOneReportOnly.js` | `data/rsid_lists/rsidListOneReportOnly.txt` |
| `rsidListTesting.js` | `data/rsid_lists/rsidListTesting.txt` |
| `botValidationRsidList.js` | `data/rsid_lists/botValidationRsidList.txt` |
| `botInvestigationMinThresholdVisits.js` | `data/rsid_lists/botInvestigationMinThresholdVisits.txt` |
| `excludedRsidCleanNames.js` | `data/rsid_lists/excludedRsidCleanNames.txt` |
| `StringsForCountries.js` | `data/rsid_lists/StringsForCountries.txt` |

### Country segment lookup (`data/country_segment_lookup.json`)

Source: `legacy_js/usefulInfo/Legend/countrySegmentLookup.js` — JS `const` wrapping a JSON-compatible object array.

Conversion: JS wrapper stripped, inner JSON array parsed and re-serialised. 231 entries with fields `SegmentId`, `SegmentName`, `DimValueId`, `DimValueName`.

### RSID×country threshold data (`data/rsid_country_thresholds/`)

Source: `legacy_js/usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js` — generated snapshot of which RSID×country combinations exceeded the visit threshold (date range 2025-12-01 to 2026-01-01).

Conversion: same as above. 310 entries with fields `rsidCleanName`, `geocountry`, `segmentId`, `visits`.

This is operational data from a past run. It is consumed by jobs that need to know which RSID×country matrix to use without re-running the investigation phase.

### Report header definitions (`data/report_headers/*.yaml`)

Source: `legacy_js/config/headers/{report_name}/Legend.js` — one file per report type, each defining a `let headers = '...'` comma-delimited column string.

Conversion: active `let headers` line extracted (comment lines skipped), split on `,`, written as YAML with `report_name` and `columns` keys. 48 Legend header files converted.

The Capita variant (`VisitsConversionsByGeoRegion/Capita.js`) is archived as-is to `data/report_headers/_archive/` — no conversion needed.

These YAML files will be consumed in **Step 4** (request builder) when report definitions are assembled.

### Segment lists (`data/segment_lists/Legend/`)

Source: `legacy_js/config/segmentLists/Legend/*.json` — already JSON, straight copy.

These files are the output of the segment creation flow and serve as input to download jobs.

### Dimension lookup files (`data/lookups/`)

Source: `legacy_js/usefulInfo/Legend/{dim}/lookup.txt` — pipe-delimited text, already in the correct format.

Straight copy, directory structure preserved.

### Saved segments (`data/saved_segments/`)

Source: `legacy_js/usefulInfo/Legend/Segments/*.json` — already JSON, straight copy.

Includes `DualConditionSegment.json` and `SingleConditionSegment.json` (segment definition templates used by segment creation), plus two specific saved segment definitions.

### User lists (`data/user_lists/`)

Source: `legacy_js/usefulInfo/Legend/userLists/userList-2026-01-02.json` — already JSON, straight copy.

Used by the segment sharing step to resolve user IDs.

### Report suite lists (`data/report_suite_lists/`)

Source: `legacy_js/usefulInfo/Legend/ReportSuiteLists/*.txt` — already plain text, straight copy. 10 dated files from 2025-06-01 to 2026-01-05.

The undated `legendReportSuites.txt` (older snapshot) is archived to `_archive/`.

### Job input CSVs (`jobs/inputs/`)

Source: `legacy_js/usefulInfo/Legend/{BotRuleLists,BotCompareLists,segmentCreationLists}/*.csv`

Straight copy into `jobs/inputs/{bot_rule_lists,bot_compare_lists,segment_creation_lists}/`.

These are run-input files, not code — they drive specific bot investigation and validation jobs.

### Client config template (`jobs/templates/client_config_template.yaml`)

Source: `legacy_js/config/client_configs/clientTemplate.yaml` — YAML, straight copy.

This is the template for creating new client credential files.

### Legend client credentials (`credentials/clientLegend.yaml`)

Source: `legacy_js/config/client_configs/clientLegend.yaml` — straight copy.

`credentials/` is gitignored. Never commit this file.

### General reference docs (`docs/reference/`)

Source: `legacy_js/usefulInfo/General/CommonMetrics` and `CommonDimensions` — plain text reference lists.

Copied to `docs/reference/common_metrics.md` and `docs/reference/common_dimensions.md`.

---

## What was NOT migrated (and why)

| Source | Reason |
|---|---|
| `config/client_configs/clientCapita.yaml` | Archived — Capita client out of scope for initial build |
| `config/read_write_settings/readWriteSettings.yaml` | **Eliminated** — read/write path config replaced by output path fields in YAML job configs |
| `config/requests/templateRequest.js` | **Eliminated as a standalone file** — request body structure embedded in `core/request_builder.py` (Step 4) |
| `config/requests/templateSegment.js` | **Eliminated as a standalone file** — segment definition structure embedded in `segments/create_segment.py` (Step 10) |
| `usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js` threshold values | Threshold number (e.g. 1000 visits) goes in job YAML config as a field, not a data file |
| `usefulInfo/Legend/botInvestigationMinThresholdVisits.js` threshold number | Same |
| `usefulInfo/Legend/botInvestigationAdHocList.js` | **Archived** — historical ad-hoc run data |
| `usefulInfo/Legend/createSegmentFromList.js` | **Archived** — duplicate of root-level file |
| `usefulInfo/Legend/legendReportSuites.txt` | **Archived** — superseded by dated files in `ReportSuiteLists/` |
| `legacy_js/temp/*.csv` | **Archived** — transient validation output from past runs |
| `legacy_js/reportSuiteChecks/*.csv` | **Archived** — historical validation output |
| `legacy_js/node_modules/` | **Eliminated** — replaced by pip packages |

---

## Format changes summary

| Source format | Target format | Used for |
|---|---|---|
| JS `const` string array | Plain text (one per line) | RSID lists |
| JS `const` JSON-object array | `.json` | Country segment lookup, RSID×country thresholds |
| JS `let headers = '...'` | YAML with `report_name` + `columns` list | Report header definitions |
| `.json`, `.txt`, `.csv`, `.yaml` | Same format, new path | Everything else |
