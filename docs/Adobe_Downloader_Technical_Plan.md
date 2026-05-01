# `adobe-downloader` — Technical Plan

## Document Purpose

This is the complete technical plan for `adobe-downloader`, a Python CLI tool for downloading, transforming, and managing Adobe Analytics report data. It covers core principles, project structure, module design, job config schema, state persistence, rate limiting, CLI design, output structure, config template system, migration sequence, risk flags, and open questions.

---

## 1. Core Principles

### 1.1 Configuration Over Code

Every job is expressed as a YAML config file. Report definitions, credentials, RSID lists, date ranges, and processing options are all declared in config. The tool ships with commented templates that explain every field. Creating a new job is: copy a template, change a few fields, run. Configs are validated at load time with Pydantic — invalid configs fail immediately, never after hours of downloading.

### 1.2 Jobs Are Chains, Not Scripts

The most valuable workflows are multi-step. A single composite job config declares the full chain. Each step declares what it produces, and subsequent steps can reference those outputs by step ID. Steps support `depends_on` for conditional execution and individual resume — if a job fails at step 3, re-running it skips completed steps.

### 1.3 Every Request Is Tracked

Every API request is registered in a SQLite state database before it executes, and its outcome is recorded after. This gives us resume (kill and restart without re-downloading), validation (query the DB for missing requests), visibility (`adobe-downloader status`), and metadata without filename parsing.

### 1.4 Optimise Expensive Operations Automatically

Shared-report detection downloads identical requests once and copies for each subsequent consumer. The sliding-window rate limiter with global pause prevents 429 cascades. These are part of the engine, not opt-in features.

### 1.5 One Tool, One Interface

Every workflow — bot investigation, bot validation, bot rule comparison, cube reports, segment creation, lookups, final metrics — is launched the same way: `adobe-downloader run --config <path>`. The `--config` flag points at a YAML file, and the YAML determines what happens.

### 1.6 Separate What Changes from What Doesn't

Code, report definitions, and reference data are version-controlled. Job configs, credentials, and outputs are not. The Git repo stays clean.

### 1.7 Async by Default, Sequential When Needed

API calls run concurrently within a step (up to the rate limit). Job steps run sequentially (because most have genuine data dependencies). If parallel steps are ever needed, the composite runner can be extended.

### 1.8 Python 3.12+, Minimal Dependencies

`httpx`, `click`, `pyyaml`, `pydantic`, `tenacity`. Everything else is stdlib. No ORM, no task queue, no Docker. This is a workstation tool.

### 1.9 Report Definitions Are a Shared Library

Report definitions (which dimension, which metrics, which segment, which row limit, which CSV headers) are defined once in `report_definitions/*.yaml` and referenced by name in job configs. A job config says `report_ref: botInvestigationMetricsByDay`, not a 15-line inline block of metric IDs. This preserves the best feature of the current `clientLegend.yaml` — named report configs that can be referenced anywhere — while moving them out of the credentials file and into version-controlled, well-structured YAML.

Report definitions can be grouped (e.g., `bot_investigation` contains all 13 report types). A job config can reference an entire group with `report_group: bot_investigation`, and the system iterates every report in the group. Inline report definitions are supported for genuine one-offs, but they are the exception, not the default.

### 1.10 Files Have a Lifecycle

Downloaded JSON files, transformed CSVs, concatenated outputs, state databases, and logs all have a defined lifecycle. The default is to keep everything — disk is cheap, re-downloading is expensive. But every stage has an opt-in cleanup:

- **JSON files** are moved to a `_processed/` folder after successful transform (not deleted by default).
- **Individual CSVs** are optionally zipped after concatenation.
- **Concatenated CSVs** are the primary deliverable and are never automatically deleted.
- **State databases** are kept indefinitely (they're small and useful for auditing).
- **Logs** are kept indefinitely alongside outputs.

The user controls retention through `post_processing` config fields. The tool never silently deletes data.

### 1.11 Jobs Leave a Trail

Every completed job appends a record to a human-readable job history log: what ran, when, how long it took, how many requests succeeded/failed, and where the outputs went. Completed job configs are automatically archived with a timestamp, so you can always answer "what config did I use for last month's bot investigation?" without relying on memory or shell history.

The history log, archived configs, and state databases together form a complete audit trail. This matters because jobs run for hours, the same workflows repeat monthly, and the person running a job in July needs to know exactly what happened in June.

### 1.12 The Tool Serves the Workflow, Not the Other Way Around

The architecture is designed around how people actually work: they repeat similar jobs monthly with small parameter changes (new dates, occasionally a new RSID or bot rule). The system should make this easy — copy last month's config, change the dates, run. Templates, report references, config archival, and chained flows all serve this principle. A new team member should be productive within an hour of cloning the repo.

---

## 2. Project Structure

```
adobe-downloader/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
├── .gitignore
│
├── docs/
│   ├── file_inventory.md              # Phase 0 audit: every JS file + its disposition
│   └── data_migration_guide.md        # Instructions for migrating JS data files
│
├── src/
│   └── adobe_downloader/
│       ├── __init__.py
│       ├── __main__.py                # enables `python -m adobe_downloader`
│       ├── cli.py                     # Click CLI entry point
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── auth.py                # OAuth token fetch + caching
│       │   ├── api_client.py          # Adobe Analytics API client
│       │   ├── rate_limiter.py        # Async sliding-window rate limiter
│       │   └── request_builder.py     # Request body compilation
│       │
│       ├── jobs/
│       │   ├── __init__.py
│       │   ├── config_schema.py       # Pydantic models for job YAML validation
│       │   ├── job_runner.py          # Orchestrates job execution from config
│       │   ├── state_manager.py       # SQLite job state persistence
│       │   └── test_mode.py           # Test mode limit application
│       │
│       ├── flows/
│       │   ├── __init__.py
│       │   ├── report_download.py     # Download + date/rsid/segment iteration
│       │   ├── transform_concat.py    # JSON→CSV + concatenation
│       │   ├── segment_creation.py    # Create segments from CSV list
│       │   ├── lookup_generation.py   # Dimension lookup file generation
│       │   ├── validation.py          # Post-download validation + retry
│       │   ├── rsid_update.py         # Report suite list updater
│       │   ├── country_investigation.py # Country×RSID matrix generation
│       │   ├── bot_rule_compare.py    # Bot rule comparison orchestrator
│       │   └── final_bot_metrics.py   # Cross-site final metrics
│       │
│       ├── transforms/
│       │   ├── __init__.py
│       │   ├── base.py                # Base transform logic
│       │   ├── bot_investigation.py
│       │   ├── bot_rule_compare.py
│       │   ├── bot_validation.py
│       │   ├── final_bot_metrics.py
│       │   └── summary_total.py
│       │
│       ├── segments/
│       │   ├── __init__.py
│       │   ├── create_segment.py      # API call to create segment
│       │   ├── share_segment.py       # Share segment with users
│       │   ├── dim_to_segments.py     # Fetch dimension values → create segments
│       │   ├── save_segment.py        # Fetch + save segment definition JSON
│       │   ├── lookup_searcher.py     # Search lookup files
│       │   └── lookup_generator.py    # Generate lookup files
│       │
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── logging.py             # Dual-handler logging (console + file)
│       │   ├── dates.py               # Date utilities
│       │   ├── csv_concat.py          # CSV concatenation
│       │   ├── paths.py               # Path resolution
│       │   ├── rsid_lookup.py         # RSID name→ID mapping
│       │   ├── bot_rules_csv.py       # Parse bot rule CSVs (download/transform/segmentList modes)
│       │   ├── extract_value.py       # Extract value IDs from API responses
│       │   ├── file_io.py             # JSON save, file read helpers
│       │   └── post_process.py        # Delete JSON, zip CSVs after completion
│       │
│       └── config/
│           ├── __init__.py
│           └── loader.py              # Config loading, credential resolution, path expansion
│
├── credentials/
│   └── client_template.yaml           # Committed template with blank values
│
├── jobs/
│   ├── templates/                     # Committed config templates with instructional comments
│   │   ├── README.md
│   │   ├── single_report_download.yaml
│   │   ├── multi_rsid_report_download.yaml
│   │   ├── bot_investigation_full.yaml
│   │   ├── bot_investigation_all_rsids.yaml
│   │   ├── bot_investigation_countries.yaml
│   │   ├── bot_validation_list_of_rules.yaml
│   │   ├── bot_validation_single_rule.yaml
│   │   ├── bot_rule_compare_csv_batch.yaml
│   │   ├── bot_rule_compare_single.yaml
│   │   ├── final_bot_metrics.yaml
│   │   ├── segment_creation.yaml
│   │   ├── lookup_generation.yaml
│   │   ├── cube_report.yaml
│   │   ├── transform_concat_only.yaml
│   │   ├── spike_sizing.yaml
│   │   └── rsid_update.yaml
│   │
│   └── examples/                      # Worked examples with real values
│       ├── legend_dl_bot-filter-exclude-monthly.yaml
│       ├── legend_cp_bot-investigation-v5.yaml
│       ├── legend_cp_bot-investigation-countries-v5.yaml
│       ├── legend_cp_bot-validation-oddspedia-r5.yaml
│       ├── legend_cp_bot-compare-oddspedia-r5.yaml
│       ├── legend_cp_final-metrics-apr25.yaml
│       ├── legend_sg_oddspedia-adhoc-jan26-r5.yaml
│       ├── legend_lu_browsertype.yaml
│       ├── legend_cp_cube-clickouts-channel-region.yaml
│       └── legend_tc_adhoc-investigation.yaml
│
├── request_templates/
│   ├── base_request.yaml              # Base request body
│   └── base_segment.yaml             # Base segment definition
│
├── report_definitions/
│   ├── bot_investigation.yaml         # 13 bot investigation report types
│   ├── bot_investigation_unfiltered.yaml
│   ├── bot_filter.yaml                # Exclude/include metrics-by-month
│   ├── bot_validation.yaml            # Bot-specific + shared validation reports
│   ├── final_bot_metrics.yaml
│   ├── lookup.yaml
│   └── clickouts.yaml
│
├── data/
│   ├── dimension_mappings.yaml        # Friendly name → Adobe dimension ID
│   ├── allowed_dimensions.yaml
│   ├── common_metrics.yaml
│   ├── rsid_lists/                    # Pipe-delimited rsid:CleanName files
│   ├── rsid_country_lists/            # Generated RSID×country matrix files
│   ├── segment_lists/                 # Created segment list JSONs
│   │   └── Legend/
│   ├── bot_rule_lists/                # Bot rule CSVs for validation
│   ├── bot_compare_lists/             # Bot rule CSVs for comparison
│   ├── segment_creation_lists/        # Input CSVs for segment creation
│   ├── segment_lookups/               # Country segment lookups etc.
│   └── lookups/                       # Dimension lookup files
│       ├── variablesbrowsertype/
│       └── variablesgeoregion/
│
├── scripts/
│   └── migrate_data.py                # One-time JS→Python data migration
│
└── tests/
    ├── __init__.py
    ├── fixtures/                       # Known-good input/output pairs
    │   ├── transforms/
    │   ├── request_bodies/
    │   └── filenames/
    ├── test_request_builder.py
    ├── test_rate_limiter.py
    ├── test_config_schema.py
    ├── test_transforms.py
    └── test_dates.py
```

### Key Structural Decisions

**`src/` layout.** Prevents accidental imports from the working directory.

**`report_definitions/` directory.** The single biggest consolidation. A report definition YAML co-locates dimension, metrics, segment(s), row limit, and CSV headers. This eliminates the `reportConfig` section of the client YAML and the entire `config/headers/` directory (50+ files). Report definitions can also encode the filtered/unfiltered distinction — same metrics, different segment (or no segment), same file.

Report definitions are the **shared library** that job configs reference. Here is what `report_definitions/bot_investigation.yaml` looks like:

```yaml
# report_definitions/bot_investigation.yaml
# All 13 bot investigation report types — filtered variant (with master bot segment)

group: bot_investigation
description: "Bot investigation reports with master bot filter applied"
transform_type: bot_investigation

# Shared defaults for all reports in this group
defaults:
  segments:
    - s3938_66fe79408ff02713f66ed76b  # Master Bot Filter
  metrics:
    - metrics/event3                         # Unique Visitors
    - cm3938_602b915cb99757640284234e        # Visits
    - cm3938_66d0bfba05c95b4eca739eb4       # Engaged Visits
    - metrics/itemtimespent                  # Total Seconds Spent
    - metrics/pageviews                      # Page Views
  csv_headers: [id, value, unique_visitors, visits, engaged_visits, total_seconds_spent, page_views, fileName, fromDate, toDate]

# Individual reports — only fields that differ from defaults
reports:
  botInvestigationMetricsByDay:
    dimension: variables/daterangeday
    row_limit: 500
    csv_headers: [id, day, unique_visitors, visits, engaged_visits, total_seconds_spent, page_views, fileName, fromDate, toDate]

  botInvestigationMetricsByMarketingChannel:
    dimension: variables/marketingchannel
    row_limit: 50

  botInvestigationMetricsByDevice:
    dimension: variables/mobiledevicetype
    row_limit: 500

  botInvestigationMetricsByDomain:
    dimension: variables/filtereddomain
    row_limit: 500

  botInvestigationMetricsByMonitorResolution:
    dimension: variables/monitorresolution
    row_limit: 500

  botInvestigationMetricsByHourOfDay:
    dimension: variables/timeparthourofday
    row_limit: 25

  botInvestigationMetricsByOperatingSystem:
    dimension: variables/operatingsystem
    row_limit: 500

  botInvestigationMetricsByPageURL:
    dimension: variables/evar2
    row_limit: 500

  botInvestigationMetricsByRegion:
    dimension: variables/georegion
    row_limit: 500

  botInvestigationMetricsByUserAgent:
    dimension: variables/evar23
    row_limit: 500

  botInvestigationMetricsByBrowserType:
    dimension: variables/browsertype
    row_limit: 500

  botInvestigationMetricsByBrowser:
    dimension: variables/browser
    row_limit: 500

  botInvestigationMetricsByMobileManufacturer:
    dimension: variables/mobilemanufacturer
    row_limit: 500
```

Job configs reference these by name (`report_ref: botInvestigationMetricsByDay`) or by group (`report_group: bot_investigation`). The unfiltered variant is a second file (`bot_investigation_unfiltered.yaml`) with identical structure but no segment in the defaults. This means adding or modifying a report type is a one-line change in one file, not a coordinated edit across header files, client YAML, and download functions.

**`jobs/templates/` directory.** Every major workflow has a commented template. Templates are the primary user interface — they replace the `FollowAlongSteps/` directory and the `callFunction.js` block-uncommenting pattern.

**`data/segment_lists/` directory.** Segment creation produces output here; download jobs consume from here. This is the bridge that enables chained flows like: create segments → download data using those segments.

**Credentials co-located.** Inside the repo directory (gitignored). Simpler than `~/.adobe_downloader/`. A `--credentials-path` CLI flag overrides if needed.

---

## 3. Module Design

### 3.1 Core Layer

| Module | Responsibility |
|---|---|
| `core/auth.py` | OAuth token fetch with in-memory caching + TTL. Refresh when expired or within 5 minutes of expiry. Uses `httpx`. |
| `core/api_client.py` | `AdobeClient` class: single entry point for all Adobe API calls. Holds auth, headers, base URL. Methods: `get_report()`, `create_segment()`, `share_segment()`, `get_report_suites()`, `get_users()`, `get_authenticated_user()`. All methods go through the rate limiter. |
| `core/rate_limiter.py` | Async sliding-window rate limiter (12 requests per 6 seconds). Two layers: sliding window + tenacity retry with backoff. See Section 7. |
| `core/request_builder.py` | `build_request(report_def, date_range, rsid, segments)` — assembles request body from a report definition dict + runtime parameters. |

```python
class AdobeClient:
    """Single entry point for all Adobe Analytics API calls."""
    
    def __init__(self, client_name: str, credentials_path: Path):
        self._credentials = load_credentials(client_name, credentials_path)
        self._token: str | None = None
        self._token_expiry: float = 0
        self._http = httpx.AsyncClient(timeout=120)
        self._rate_limiter = RateLimiter()
    
    async def authenticate(self) -> str: ...
    async def get_report(self, request_body: dict) -> dict: ...
    async def create_segment(self, segment_def: dict) -> dict: ...
    async def share_segment(self, segment_id: str, user_ids: list[str]) -> None: ...
    async def get_report_suites(self, limit: int = 1000) -> dict: ...
    async def get_users(self) -> list[dict]: ...
    async def get_authenticated_user(self) -> dict: ...
    async def close(self) -> None: ...
```

### 3.2 Flow Layer

| Module | What It Does |
|---|---|
| `flows/report_download.py` | Download + date/RSID/segment iteration. `download_report()` handles a single request. `iterate_dates()` and `iterate_rsids()` are async generators. Supports three RSID source types (`file`, `list`, `single`) and three segment source types (`inline`, `segment_list_file`, `step_output`). Also supports `rsid_country_matrix` for RSID×country iteration. |
| `flows/transform_concat.py` | JSON→CSV transform + concatenation. Transform function selected from config (`transform_type` field). One generic `process_json_files()` that takes a transform function as argument. |
| `flows/segment_creation.py` | Create segments from a CSV list. Dimension mapping from `data/dimension_mappings.yaml`. Outputs a segment list JSON to `data/segment_lists/` for consumption by downstream jobs. Also generates compare and validate CSVs. |
| `flows/lookup_generation.py` | Generate dimension lookup files. Builds the report definition in memory — no client YAML mutation. |
| `flows/validation.py` | Post-download validation. Compares state DB completed requests against actual files on disk. Reports missing/empty/invalid files. Optionally re-downloads missing files. |
| `flows/rsid_update.py` | Fetch all report suites, run topline metrics, filter by threshold, generate updated RSID list files. Archives previous versions with date stamp. |
| `flows/country_investigation.py` | Phase 1: generate country×RSID matrix (which countries per RSID exceed a visit threshold). Phase 2: iterate the matrix with bot investigation downloads. |
| `flows/bot_rule_compare.py` | Orchestrate bot rule comparison downloads across dimensions. Integrates AllTraffic file-copy optimisation via the state manager's canonical request mechanism. Supports both single-rule and CSV-batch modes. |
| `flows/final_bot_metrics.py` | Download final bot rule metrics across all RSIDs using a segment list as input. Iterates RSIDs × segments. |

### 3.3 Transform Layer

One module per transform type, all implementing a common interface:

```python
def transform(file_path: Path, metadata: RequestMetadata | None = None) -> TransformResult:
    """
    Transform a JSON file to CSV.
    
    Args:
        file_path: Path to the input JSON file.
        metadata: Optional metadata from state DB. If provided, used instead of filename parsing.
    
    Returns:
        TransformResult with success/empty/error status and CSV data.
    """
```

The `metadata` parameter is the key improvement — transforms can get report type, RSID, date range, and segment info from the state DB instead of parsing filenames. For backward compatibility with pre-existing JSON files, the filename-parsing fallback is retained.

### 3.4 Segment Layer

| Module | What It Does |
|---|---|
| `segments/create_segment.py` | Single API call to create a segment. |
| `segments/share_segment.py` | Share a segment with specified user IDs. |
| `segments/dim_to_segments.py` | Download dimension values from a report, create one segment per value, save segment list JSON. Used by cube report flow. |
| `segments/save_segment.py` | Fetch a segment definition from the API and save the JSON locally. |
| `segments/lookup_searcher.py` | Search lookup files for a dimension value's numeric ID. |
| `segments/lookup_generator.py` | Generate lookup files by downloading all values for a dimension. |

### 3.5 Utility Layer

| Module | What It Does |
|---|---|
| `utils/logging.py` | Dual-handler logging: console (INFO) + file (DEBUG). Log files written to `<output>/<client>/.logs/`. Set up in Phase 1, used everywhere. |
| `utils/dates.py` | `subtract_days()`, `generate_date_ranges()`, next-date arithmetic. |
| `utils/csv_concat.py` | Concatenate CSV files with optional header overrides. |
| `utils/paths.py` | Resolve JSON/CSV storage folder paths from config. |
| `utils/rsid_lookup.py` | Pipe-delimited RSID file lookup (name→ID and ID→name). |
| `utils/bot_rules_csv.py` | Parse bot rule CSVs with three modes: `download` (returns segment+rule pairs), `transform` (returns processing strings), `segment_list` (returns path to segment list JSON). |
| `utils/extract_value.py` | Extract `itemId` values from Adobe API responses. |
| `utils/file_io.py` | JSON save/load helpers. |
| `utils/post_process.py` | Delete JSON after transform, zip CSVs after concatenation. |

### 3.6 Key Consolidations

**50+ header files → report definitions.** CSV headers are defined alongside the metrics and dimensions they describe.

**`addRequestDetails.js` / `deleteRequestDetails.js` → eliminated.** The request builder accepts a report definition dict directly.

**`retrieveLegendRsid.js` / `retrieveValue.js` → `utils/rsid_lookup.py`.** Pipe-delimited format retained.

**`FollowAlongSteps/` → `jobs/templates/`.** Step-by-step VS Code execution replaced by `adobe-downloader run --config <file>`.

**`readBotRulesFromCSV.js` → `utils/bot_rules_csv.py`.** Same three-mode interface, now shared across all flows.

---

## 4. Job Config Schema

### 4.1 Job Types

```
report_download      — Download reports with date/RSID/segment iteration
transform_concat     — Transform JSON→CSV and concatenate
segment_creation     — Create segments from a CSV list
lookup_generation    — Generate dimension lookup files
rsid_update          — Fetch and filter report suite lists
composite            — Multi-step chained workflow
```

### 4.2 Universal Fields

```yaml
job_type: report_download | transform_concat | segment_creation | lookup_generation | rsid_update | composite
client: Legend
description: "Human-readable description of this job"

date_range:
  from: "2025-01-01"        # absolute date
  to: "2025-03-31"          # absolute date
  # OR relative:
  # to: today
  # lookback_days: 90

test_mode: false
test_limits:
  max_rsids: 3
  max_date_intervals: 2
  max_segments: 5

resume: true                 # skip completed requests on restart (default: true)

post_processing:
  delete_json_after_transform: false
  zip_csvs_after_concat: true

output:
  base_folder: "/Users/edwardgurton/Documents/Work/Adobe Downloads"
```

### 4.3 Report Download

The primary way to specify a report is by reference. The full specification lives in `report_definitions/` and the job config just names it:

```yaml
job_type: report_download

# Option A (preferred): Reference a named report
report_ref: botInvestigationMetricsByDay
# The system looks this up in report_definitions/ and gets the dimension,
# metrics, row_limit, segments, and csv_headers automatically.

# Option B: Reference an entire group (downloads all reports in the group)
# report_group: bot_investigation
# Downloads all 13 bot investigation reports. Each becomes a separate request.

# Option C (one-offs only): Define inline
# report:
#   name: myCustomReport
#   dimension: variables/daterangeday
#   row_limit: 500
#   segments: []
#   metrics:
#     - metrics/event3
#   csv_headers: [id, day, unique_visitors, fileName, fromDate, toDate]

rsids:
  source: file | list | single
  file: data/rsid_lists/legend_all.txt
  # list: [Coverscom, Casinoorg]
  # single: trillioncoverscom
  batch_size: 12

# Segment iteration (optional — for cube reports and segment-driven downloads)
segments:
  source: inline | segment_list_file | step_output | latest_segment_list

interval: full | month | day

transform:
  enabled: true
  type: standard | bot_investigation | bot_rule_compare | bot_validation | final_bot_metrics | summary_total
  concat: true
```

`report_ref` and `report_group` are resolved at config load time. If the referenced name doesn't exist in any `report_definitions/*.yaml` file, Pydantic validation fails immediately with a clear message. This prevents typos from surfacing hours into a download.

### 4.4 Transform + Concatenate (Standalone)

```yaml
job_type: transform_concat
transform:
  type: bot_investigation
  source_pattern: ".*Coverscom-FullRun-V4-Daily.*\\.json$"
  source_folder: null       # null = default JSON folder
  output_subfolder: "Coverscom-V4"

concat:
  enabled: true
  file_pattern: ".*csv"
  custom_headers:
    1: Feature
```

### 4.5 Segment Creation

```yaml
job_type: segment_creation
segment_creation:
  input_csv: data/segment_creation_lists/Oddspedia-AdHoc-Jan26-RoundFive.csv
  share_with_users:
    - "200419062"
  test_mode_row: null       # set to row number for test mode

output:
  compare_list_path: data/bot_compare_lists/
  validate_list_path: data/bot_rule_lists/
  segment_list_path: data/segment_lists/Legend/  # <-- segment list JSON saved here
```

### 4.6 RSID Update

```yaml
job_type: rsid_update
rsid_update:
  investigation_threshold: 1000
  validation_threshold: 1000
  include_virtual: false

output:
  base_folder: data/rsid_lists/
```

### 4.7 Composite Jobs and Chained Flows

Composite jobs declare a sequence of steps. The key mechanism is **output references** — each step produces named outputs, and subsequent steps can reference them.

```yaml
job_type: composite
steps:
  - step: segment_creation
    id: create_segments
    segment_creation:
      input_csv: data/segment_creation_lists/MyRules.csv
      share_with_users: ["200419062"]
    # Produces: segment_list_file, compare_list_file, validate_list_file

  - step: report_download
    id: download_validation
    report_group: bot_validation
    bot_rules:
      source: step_output        # <-- consumes output of previous step
      step_id: create_segments
      output_key: validate_list_file

  - step: validate_output
    id: validate
    config_ref: download_validation
    retry: true

  - step: transform_concat
    id: transform
    depends_on: validate          # <-- only runs if validate succeeds
    transform:
      type: bot_validation
```

**Standard output keys by step type:**

| Step Type | Output Key | Value |
|---|---|---|
| `segment_creation` | `segment_list_file`, `compare_list_file`, `validate_list_file` | Paths to generated files |
| `report_download` | `job_id`, `json_folder` | Job ID for state DB, path to downloaded files |
| `transform_concat` | `csv_folder`, `concatenated_file` | Paths to outputs |
| `generate_country_matrix` | `matrix_file` | Path to RSID×country JSON |
| `rsid_update` | `investigation_list`, `validation_list` | Paths to generated RSID lists |
| `validate_output` | `missing_count` | Number of missing/invalid files |
| `dim_to_segments` | `segment_list_file` | Path to created segment list JSON |

**Shared-report optimisation** is configured within composite steps:

```yaml
  - step: report_download
    report_group: bot_validation
    optimisation:
      shared_reports: true
      shared_report_names:
        - botFilterExcludeMetricsByMonth
        - botFilterIncludeMetricsByMonth
```

When enabled, the job runner detects identical requests across bot rules, downloads them once (canonical), and copies the file for each subsequent consumer (derived).

**Resume behaviour:** Each step is tracked as a sub-job in the state DB. On resume, completed steps are skipped (their outputs reloaded), the interrupted step picks up from its last completed request, and pending steps remain queued.

### 4.8 Worked Example: Cube Report

The most complex chained flow — 3-dimension analysis where segments for one dimension feed into downloads across another:

```yaml
job_type: composite
client: Legend
description: "Clickouts by Marketing Channel × Geo Region"

steps:
  - step: dim_to_segments
    id: create_channel_segments
    dim_to_segments:
      dimension: variables/marketingchannel.marketing-channel-attribution
      rsid: trillioncoverscom
      additional_segments:
        - s3938_61bb0165a88ab931afa78e4c  # Master Bot Filter EXCLUDE
      num_pairs: 1

  - step: report_download
    id: download_cube
    report:
      name: LegendClickoutsByGeoregionNAOnly
      dimension: variables/georegion
      segments:
        - s3938_61bb0165a88ab931afa78e4c
        - s3938_681e521d16e3be6770921fa8  # USA and Canada Only
      metrics:
        - cm3938_67877f0e25c74e65d1f3f449
        - cm3938_68655d7318c56ac719c11a44
        - cm3938_68655dd05c74c471e8de44d0
        - cm3938_68655e0b18c56ac719c11a47
      csv_headers: [id, region, raw_clickouts_linear_7d, raw_clickouts_participation_7d, unique_visit_clickouts_linear_7d, unique_visit_clickouts_participation_7d, fileName, fromDate, toDate]
    rsids:
      source: single
      single: trillioncoverscom
    segments:
      source: step_output
      step_id: create_channel_segments
      output_key: segment_list_file
    interval: month
    file_name_extra: "MCRunV1"

  - step: transform_concat
    id: transform
    depends_on: download_cube
    transform:
      type: standard
      source_pattern: ".*MCRunV1.*\\.json$"
    concat:
      enabled: true

date_range:
  from: "2023-07-01"
  to: "2025-06-30"
```

### 4.9 Validation with Pydantic

All configs are validated at load time. Invalid configs fail fast with clear error messages before any API calls.

```python
class JobConfig(BaseModel):
    job_type: Literal["report_download", "transform_concat", "segment_creation", 
                       "lookup_generation", "rsid_update", "composite"]
    client: str
    description: str = ""
    date_range: DateRange | None = None
    test_mode: bool = False
    test_limits: TestLimits = TestLimits()
    resume: bool = True
```

---

## 5. Job File Naming Convention

### Format

```
<client>_<job_type_code>_<descriptor>[_<qualifier>].yaml
```

### Job Type Codes

| Code | Job Type |
|---|---|
| `dl` | report_download |
| `tc` | transform_concat |
| `sg` | segment_creation |
| `lu` | lookup_generation |
| `ru` | rsid_update |
| `cp` | composite |

### Examples

```
legend_cp_bot-investigation-v5.yaml
legend_dl_bot-filter-exclude-monthly.yaml
legend_tc_bot-investigation-coverscom-v4.yaml
legend_sg_oddspedia-adhoc-jan26-r5.yaml
legend_lu_browsertype.yaml
legend_ru_monthly-refresh.yaml
legend_cp_cube-clickouts-channel-region.yaml
```

---

## 6. State Persistence Design

### 6.1 Storage: SQLite

Queryable, concurrent-safe for single-runner jobs, scalable to 10,000+ requests, zero dependencies (stdlib).

### 6.2 Schema

```sql
CREATE TABLE jobs (
    job_id          TEXT PRIMARY KEY,
    config_path     TEXT NOT NULL,
    config_hash     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    total_requests  INTEGER DEFAULT 0,
    error_message   TEXT
);

CREATE TABLE requests (
    request_id          TEXT PRIMARY KEY,
    job_id              TEXT NOT NULL REFERENCES jobs(job_id),
    request_key         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL,
    started_at          TEXT,
    completed_at        TEXT,
    retry_count         INTEGER DEFAULT 0,
    error_message       TEXT,
    output_path         TEXT,
    canonical_request_id TEXT REFERENCES requests(request_id),  -- for shared-report optimisation
    UNIQUE(job_id, request_key)
);

CREATE TABLE step_state (
    step_id         TEXT NOT NULL,
    job_id          TEXT NOT NULL REFERENCES jobs(job_id),
    status          TEXT NOT NULL DEFAULT 'pending',
    outputs         TEXT,           -- JSON: {"segment_list_file": "/path/to/file.json", ...}
    started_at      TEXT,
    completed_at    TEXT,
    PRIMARY KEY (job_id, step_id)
);

CREATE INDEX idx_requests_job_status ON requests(job_id, status);
```

The `canonical_request_id` column enables shared-report optimisation: NULL means a standard or canonical request; non-NULL points to the canonical request whose file should be copied.

The `step_state` table tracks composite job step completion, including serialised outputs for reference by downstream steps.

### 6.3 State File Location

```
<output_base_folder>/<client>/.state/<job_id>.db
```

### 6.4 Resume Behaviour

1. Compute `job_id` from config path + content hash.
2. If state DB exists and `resume: true`: skip completed requests, re-queue pending/failed/in_progress.
3. If config has changed since last run (detected via `config_hash`), warn and ask for confirmation.
4. For composite jobs: skip completed steps, reload their outputs from `step_state`, resume from the interrupted step.

---

## 7. Rate Limiter Design

### 7.1 Architecture

Two layers:

**Layer 1: Sliding Window** — enforces 12 requests per 6 seconds. Implemented with an `asyncio.Semaphore`-like mechanism using a deque of timestamps.

**Layer 2: Retry with Backoff** — `tenacity` decorators on API call methods. Catches 429, 500, 502, 503. On 429, triggers a global pause across all requests.

### 7.2 Implementation

```python
class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int = 12, window_seconds: float = 6.0, max_concurrent: int = 12):
        self._max_requests = max_requests
        self._window = window_seconds
        self._timestamps: deque[float] = deque()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()
        self._pause_until: float = 0
    
    async def acquire(self): ...    # Wait for available slot
    def release(self): ...          # Release slot
    def set_pause(self, duration: float = 10.0): ...  # Global pause after 429
    
    async def execute(self, coro_func, *args, request_id: str = "unknown", **kwargs):
        await self.acquire()
        try:
            return await coro_func(*args, **kwargs)
        finally:
            self.release()
```

### 7.3 Deadlock Prevention

`asyncio.wait_for()` wraps each request with a 120-second timeout. No `setInterval` / `process.exit` hacks needed — the rate limiter is an async context manager that cleans up on `__aexit__`.

---

## 8. CLI Design

### 8.1 Library: `click`

Subcommand composition, automatic `--help`, file path validation, environment variable defaults. Single dependency.

### 8.2 Subcommands

```
adobe-downloader run --config <path> [--test] [--no-resume] [--dry-run]
    Execute a job.

adobe-downloader status --config <path>
    Print job state: requests by status, last error, estimated completion.

adobe-downloader retry --config <path> [--failed-only] [--reset-errors]
    Re-queue requests.

adobe-downloader reset --config <path> [--confirm]
    Clear all state for a job.

adobe-downloader validate --config <path>
    Validate a config file: parse YAML, check Pydantic schema, verify referenced files exist.

adobe-downloader validate-output --config <path> [--retry] [--dry-run]
    Check that all expected output files exist and are valid.

adobe-downloader update-rsids --client <name> --from <date> --to <date>
    [--investigation-threshold 1000] [--validation-threshold 1000] [--include-virtual]
    Fetch report suites, filter by threshold, generate RSID list files.

adobe-downloader list-rsids --client <name>
    Fetch and display all report suites.

adobe-downloader list-users --client <name>
    List all Adobe users for a client.

adobe-downloader get-segment <segment-id> --client <name> [--output <path>]
    Fetch and save a segment definition JSON.

adobe-downloader search-lookup --client <name> --dimension <dim> --value <search>
    Search lookup files for a dimension value's numeric ID.

adobe-downloader history --client <name> [--last 10] [--status completed] [--since 2025-06-01]
    Show recent job history from the job log.

adobe-downloader cleanup --client <name> --older-than <days>d --type processed-json|logs|state
    Remove old processed files. Never runs automatically — always explicit.

adobe-downloader version
    Print version.
```

### 8.3 Entry Point

```toml
[project.scripts]
adobe-downloader = "adobe_downloader.cli:main"
```

---

## 9. Output Directory Structure

```
<base_folder>/
└── <client>/
    ├── .state/                          # Job state databases
    │   └── <job_id>.db
    ├── .logs/                           # Job log files
    │   └── <job_id>_<timestamp>.log
    ├── .history/                        # Job history + archived configs
    │   ├── job_history.jsonl            # Append-only job completion log
    │   └── configs/                     # Archived configs from completed jobs
    │       └── 2025-07-15_legend_cp_bot-investigation-v5.yaml
    ├── json/
    │   ├── <job_name>/                  # One subfolder per job
    │   └── _processed/                  # Transformed JSONs moved here
    ├── csv/
    │   ├── <job_name>/                  # Individual CSVs
    │   └── _concatenated/               # Final concatenated CSVs
    ├── zip/
    │   └── <job_name>/
    └── lookups/
        └── variablesbrowsertype/
```

File naming follows the existing convention: `<client>_<reportName>_<fileNameExtra>_[DIMSEG<segmentId>_]<fromDate>_<toDate>.json`. This is preserved for backward compatibility — transforms must be able to process both old and new files during the transition period.

---

## 10. File Lifecycle and Retention

### 10.1 The Journey of a File

Every file in the system follows a predictable path:

**Downloaded JSON files:** `json/<job_name>/` → after successful transform, moved to `json/_processed/<job_name>/` (not deleted). The `_processed` folder signals "these have been transformed — safe to clean up if disk is tight." Default: keep indefinitely.

**Transformed CSV files:** Written to `csv/<job_name>/`. These are intermediate products. After concatenation, individual CSVs remain in place but are optionally zipped to `zip/<job_name>/`.

**Concatenated CSV files:** Written to `csv/_concatenated/<job_name>_concatenated.csv`. This is the primary deliverable — the file that gets loaded into Power BI or shared with stakeholders. Never automatically deleted.

**State databases:** Kept in `.state/<job_id>.db`. Small (typically <1MB even for large jobs). Kept indefinitely. Useful for auditing what happened months later.

**Log files:** Kept in `.logs/<job_id>_<timestamp>.log`. Kept indefinitely. Useful for debugging failures.

### 10.2 Retention Configuration

```yaml
post_processing:
  # What to do with JSON files after successful transform
  json_after_transform: move     # move | delete | keep
  #   move   = move to _processed/ (default, recommended)
  #   delete = delete after transform (saves disk, not recommended for first runs)
  #   keep   = leave in place (uses most disk but safest)

  # What to do with individual CSVs after concatenation
  csvs_after_concat: keep        # keep | zip | delete
  #   keep   = leave individual CSVs in place (default)
  #   zip    = compress to zip/<job_name>/ after concat
  #   delete = delete individual CSVs after concat (only concatenated file remains)

  # Cleanup utility (manual, not automatic)
  # adobe-downloader cleanup --client Legend --older-than 90d --type processed-json
  # This deletes files from _processed/ older than 90 days. Never runs automatically.
```

### 10.3 Guiding Principle

**Default is to keep everything.** Disk space is cheap. Re-downloading 50,000 API requests because someone deleted intermediate files is expensive (hours of time, API quota consumed). The tool provides explicit cleanup mechanisms but never silently deletes data. The user must opt in to deletion, and the safest options are the defaults.

---

## 11. Job History and Config Archival

### 11.1 Job History Log

Every completed job (success or failure) appends a record to `<base_folder>/<client>/.history/job_history.jsonl`. Each line is a JSON object:

```json
{
  "job_id": "legend_cp_bot-investigation-v5_a3f2b1",
  "config_path": "jobs/legend_cp_bot-investigation-v5.yaml",
  "started_at": "2025-07-15T09:23:41Z",
  "completed_at": "2025-07-15T21:14:02Z",
  "duration_minutes": 710,
  "status": "completed",
  "total_requests": 4620,
  "completed_requests": 4618,
  "failed_requests": 2,
  "output_folder": "/Users/edwardgurton/Documents/Work/Adobe Downloads/Legend/csv/bot-investigation-v5/",
  "archived_config": ".history/configs/2025-07-15_legend_cp_bot-investigation-v5.yaml"
}
```

This is human-readable (JSONL = one JSON object per line, easy to grep/filter). It answers "what did I run last month?" and "how long did it take?" without opening state databases.

**CLI access:**

```
adobe-downloader history --client Legend [--last 10] [--status completed] [--since 2025-06-01]
    Show recent job history.
```

### 11.2 Config Archival

When a job completes, the config file used is copied to:

```
<base_folder>/<client>/.history/configs/<date>_<config_filename>.yaml
```

This means:
- You can always find the exact config used for any past job.
- If you delete or modify your working job config, the archived copy survives.
- Monthly workflows become easy to repeat: find last month's archived config, copy it back, change the dates.

The archived config is a byte-for-byte copy of the file as it was when the job ran. No modification, no annotation.

### 11.3 How Users Interact with History

**Repeating a monthly job:** Look at `.history/configs/`, find last month's config, copy it to `jobs/`, edit dates, run.

**Debugging a failure:** Check `job_history.jsonl` for the job record, open the state DB for request-level detail, open the log file for debug-level trace.

**Onboarding a new team member:** "Look at `.history/configs/` to see every job we've run. Find the most recent bot investigation config and use it as your starting point."

**Audit trail:** "What exactly did we run for the Q2 bot investigation?" → `grep "bot-investigation" .history/job_history.jsonl` → find the archived config → see every parameter.

---

## 12. Config Template System

### 12.1 Design Principles

- **Templates are committed, job configs are gitignored.** Templates live in `jobs/templates/`. Run configs live in `jobs/`.
- **Every field has an instructional comment** explaining what it does, what values are expected, and common choices.
- **Placeholder values that must be changed are marked with `# <-- UPDATE THIS`.**
- **One template per major workflow.** 16 templates covering every workflow identified in the codebase.

### 12.2 Example: Bot Validation from Rule List

```yaml
# ============================================================================
# Bot Validation — List of Rules
# ============================================================================
# Chain: download validation data → validate completeness → transform/concat
#
# BEFORE RUNNING:
#   1. Create your bot rules CSV in data/bot_rule_lists/
#      Columns: dimSegmentId, botRuleName (reportToIgnore is optional)
#   2. Update the fields marked <-- UPDATE THIS
#   3. Run: adobe-downloader run --config jobs/<your-file>.yaml
#
# EXPECTED DURATION: ~2-4 hours for 5 rules × 30 RSIDs × 24 months
# ============================================================================

job_type: composite
client: Legend
description: "Bot validation for [ROUND NAME]"  # <-- UPDATE THIS

steps:
  - step: report_download
    id: download
    report_group: bot_validation
    bot_rules:
      source: csv_file
      file: data/bot_rule_lists/MyRules_validate.csv  # <-- UPDATE THIS
    optimisation:
      shared_reports: true
      shared_report_names:
        - botFilterExcludeMetricsByMonth
        - botFilterIncludeMetricsByMonth
    rsids:
      source: file
      file: data/rsid_lists/legend_validation_threshold.txt

  - step: validate_output
    id: validate
    config_ref: download
    retry: true

  - step: transform_concat
    id: transform
    depends_on: validate
    transform:
      type: bot_validation
      bot_rules:
        source: csv_file
        file: data/bot_rule_lists/MyRules_validate.csv  # <-- SAME FILE
        mode: transform
    concat:
      enabled: true

date_range:
  from: "2024-02-01"   # <-- UPDATE THIS (typically 24 months back)
  to: "2026-02-01"     # <-- UPDATE THIS (first day of month after end)

output:
  base_folder: "/Users/edwardgurton/Documents/Work/Adobe Downloads"
```

### 12.3 Example: Single Report Download (Simplest Case)

```yaml
# ============================================================================
# Single Report Download — One report, one RSID, one date range
# ============================================================================
# Run: adobe-downloader run --config jobs/<your-file>.yaml
# Duration: Usually under 1 minute.
# ============================================================================

job_type: report_download
client: Legend
description: "One-off download"  # <-- UPDATE THIS

# Option A (preferred): Reference a named report from report_definitions/
report_ref: botInvestigationMetricsByDay  # <-- UPDATE THIS
# Available reports: see report_definitions/*.yaml for all named reports
# Examples: botInvestigationMetricsByDay, botFilterExcludeMetricsByMonth,
#           botInvestigationMetricsByRegion, etc.

# Option B (one-offs): Define inline — use only when you need a report
# that doesn't exist in report_definitions/
# report:
#   name: myCustomReport         # used for file naming
#   dimension: variables/daterangeday
#   row_limit: 500
#   segments: []
#   metrics:
#     - metrics/event3
#     - cm3938_602b915cb99757640284234e
#   csv_headers: [id, day, unique_visitors, visits, fileName, fromDate, toDate]

rsids:
  source: single
  single: trillioncoverscom      # <-- UPDATE THIS (Adobe RSID)

interval: full                   # full | day | month

date_range:
  from: "2025-01-01"             # <-- UPDATE THIS
  to: "2025-03-31"               # <-- UPDATE THIS

transform:
  enabled: false                 # Set true for automatic JSON → CSV
  type: standard

output:
  base_folder: "/Users/edwardgurton/Documents/Work/Adobe Downloads"
```

---

## 13. Migration Sequence

### Phase 0: Audit and Preparation

**Step 0: File inventory and disposition**
- Inventory every file in the JS repo. Mark each as port / consolidate / eliminate / data-migrate / archive / defer.
- Deliverable: `docs/file_inventory.md`.

**Step 0.5: Data migration**
- Write `scripts/migrate_data.py`: convert JS arrays → text files, copy segment lists, lookups, bot rule CSVs.
- Deliverable: `docs/data_migration_guide.md` + migrated data files.

**Step 0.75: Capture test fixtures**
- For each transform type, save representative input JSONs and expected output CSVs.
- Save compiled request bodies for all report types.
- Deliverable: `tests/fixtures/` directory.

### Phase 1: Foundation

**Step 1: Project scaffold + config + logging + templates**
- `pyproject.toml`, directory structure, `.gitignore`.
- `config/loader.py` — credential loading, path resolution.
- `utils/logging.py` — dual-handler logging (console + file).
- `jobs/config_schema.py` — Pydantic models for all job types.
- `cli.py` with `validate` subcommand.
- `jobs/templates/` with all 16 templates.
- `jobs/examples/` with 10 worked examples.
- Validation: `adobe-downloader validate --config <example>` parses and validates.

**Step 2: Auth + API client**
- `core/auth.py` with token caching.
- `core/api_client.py` with `AdobeClient` class including `get_users()`, `get_authenticated_user()`.
- Validation: Fetch a token, make one test API call, `adobe-downloader list-users` works.

**Step 3: Rate limiter**
- `core/rate_limiter.py`.
- Unit tests with mocked timers.
- Validation: Stress test with 50 rapid mock requests.

**Step 4: Request builder**
- `core/request_builder.py`.
- Port `report_definitions/*.yaml`.
- Validation: Compare generated request bodies to JS output and to test fixtures.

### Phase 2: Report Download

**Step 5: Basic download (single request)**
- `flows/report_download.py` — `download_report()`.
- Validation: Download one report, compare JSON to JS version.

**Step 6: Date, RSID, and segment iteration**
- `iterate_dates()`, `iterate_rsids()` in the download flow.
- `segment_list_file` source type for iterating over segments from a JSON file.
- `rsid_country_matrix` source type for RSID×country iteration.
- Validation: Multi-RSID multi-date job + segment-list-driven download.

**Step 7: State persistence**
- `jobs/state_manager.py` with `canonical_request_id` for shared-report optimisation.
- Integrate state tracking into the download flow.
- `cli.py`: `run`, `status`, `retry`, `reset` subcommands.
- Validation: Start job, kill mid-run, restart — completed requests skipped. Shared-report copy works for 2 bot rules.

### Phase 3: Transform + Concatenate

**Step 8: Base transform + CSV concatenation**
- `transforms/base.py`, `utils/csv_concat.py`, `flows/transform_concat.py`.
- Validation: Transform JSONs from Step 6, compare to JS output.

**Step 9: Specialised transforms**
- Port all 5 specialised transforms.
- Port `utils/bot_rules_csv.py`.
- Validate against test fixtures from Step 0.75.
- Validation: Byte-for-byte CSV comparison against fixtures.

### Phase 4: Segments + Lookups

**Step 10: Segment creation**
- `flows/segment_creation.py`, `segments/create_segment.py`, `segments/share_segment.py`.
- `segments/dim_to_segments.py`, `segments/save_segment.py`.
- Segment list output to `data/segment_lists/` with deterministic naming.
- `adobe-downloader get-segment` and `adobe-downloader search-lookup` CLI commands.
- Validation: Create test segment, verify via API. Segment list JSON written and consumable by download job.

**Step 11: Lookup generation**
- `flows/lookup_generation.py`, `segments/lookup_generator.py`, `segments/lookup_searcher.py`.
- Validation: Generate lookup file, compare to existing.

### Phase 5: Composite Jobs

**Step 12: Composite job runner**
- `jobs/job_runner.py`: output reference resolution, `depends_on`, step-level resume.
- `generate_country_matrix` step type.
- `validate_output` step type.
- Validation: Full bot investigation composite (3 RSIDs, 2 days).

**Step 13: Bot rule comparison flow**
- `flows/bot_rule_compare.py`.
- AllTraffic file-copy optimisation via canonical requests.
- Validation: 2 RSIDs × 1 rule, verify segment + AllTraffic files.

**Step 14: Final bot metrics flow**
- `flows/final_bot_metrics.py`.
- Validation: 3 RSIDs × 1 segment list.

### Phase 6: Post-processing + Polish

**Step 15: Post-processing + job history**
- `utils/post_process.py` — JSON move/deletion, CSV zipping.
- Job history logging to `.history/job_history.jsonl`.
- Config archival to `.history/configs/`.
- `adobe-downloader history` CLI command.
- `adobe-downloader cleanup` CLI command.

**Step 16: Test mode**
- `jobs/test_mode.py`, `--test` CLI flag.

**Step 17: Validation flow**
- `flows/validation.py`, `adobe-downloader validate-output` CLI command.
- Validation: Start job, kill, run validate-output, verify missing files detected and re-downloaded.

**Step 18: Report suite updater**
- `flows/rsid_update.py`, `adobe-downloader update-rsids` CLI command, `rsid_update` job type.
- Validation: Compare output RSID lists to current JS-generated lists.

**Step 19: End-to-end validation**
- Full bot investigation pipeline end-to-end.
- Full bot validation workflow (CSV → download → validate → transform).
- Cube report end-to-end.
- RSID updater → bot investigation → validate → transform chain.
- Compare all outputs to JS production runs.

---

## 14. Risk Flags

### 14.1 Filename Parsing is Load-Bearing

Transforms parse filenames to extract metadata. Mitigation: store metadata in the state DB. Transform step reads from DB first, falls back to filename parsing for pre-existing files.

### 14.2 `process.exit(0)` in Iteration Functions

Both `iterateRsidRequests` and `iterateSegmentRequests` call `process.exit(0)` to clean up the rate limiter's `setInterval`. Non-issue in Python — the rate limiter is an async context manager.

### 14.3 Token Refresh is Missing

Current code fetches a fresh token on every call. Mitigation: `core/auth.py` caches with TTL, refreshes within 5 minutes of expiry.

### 14.4 Massive `reportConfig` in Client YAML

~45 report config entries, many near-duplicates. Mitigation: consolidated into `report_definitions/` directory. Client YAML shrinks to credentials + default RSID.

### 14.5 Bot Rule Compare Has Complex Filename Parsing

Extracts 10+ fields from filename with position-dependent logic. Mitigation: state DB metadata + filename-parsing fallback during transition.

### 14.6 Lodash Deep Clone

Non-issue in Python. `yaml.safe_load()` returns fresh dicts.

### 14.7 Scattered RSID Lists

Multiple JS files exporting arrays. Mitigation: consolidated into plain text files in `data/rsid_lists/`.

### 14.8 Shared-Report Optimisation Must Be Preserved

Bot validation downloads shared reports once and copies per rule. Bot rule comparison does the same with AllTraffic files. If this optimisation is lost, API call volume increases significantly for multi-rule jobs. Mitigation: canonical request mechanism in state DB (Section 6.2).

### 14.9 Cross-Item Concatenation Has Business Logic

The bot investigation cross-item concat excludes `botInvestigationMetricsByPageURL` from feature-totals merges and produces two separate outputs (MetricsPerDay, MetricsPerFeature). This logic must be configurable or documented in the composite job config.

### 14.10 Segment List Lifecycle is Load-Bearing

Segment creation produces JSON files that are consumed by downstream download jobs (final metrics, cube reports). The output path must be deterministic and the format stable. Any change breaks the chain.

---

## 15. Open Questions

### 15.1 Report definition inheritance

Many report types share metrics but differ in dimension and row limit. Implement a simple `base` key — one level of inheritance.

### 15.2 Credential environments

Single credential file per client. `--credentials-path` or env var for override.

### 15.3 Cross-item concatenation strategy

Explicit steps in the composite config. Cross-item concat is another `transform_concat` step with a different source pattern. Keeps behaviour explicit.

### 15.4 Parallel job execution

Not in Phase 1. Single jobs already saturate the rate limit.

### 15.5 Minimum Python version

3.12+. Better `asyncio` error messages and no practical reason to support older versions.

### 15.6 `usefulInfo/` directory migration

| Current | New Location |
|---|---|
| `legendReportSuites.txt` | `data/rsid_lists/legend_all.txt` |
| `botInvestigationMinThresholdVisits.js` | `data/rsid_lists/legend_investigation_threshold.txt` |
| `variablesbrowsertype/lookup.txt` | `data/lookups/variablesbrowsertype/lookup.txt` |
| `segmentCreationLists/*.csv` | `data/segment_creation_lists/` |
| `BotRuleLists/*.csv` | `data/bot_rule_lists/` |
| `BotCompareLists/*.csv` | `data/bot_compare_lists/` |
| `countrySegmentLookup.js` | `data/segment_lookups/legend_country_segments.json` |
| `rsidList*.js` | Converted to text → `data/rsid_lists/` |
| `config/segmentLists/Legend/*.json` | `data/segment_lists/Legend/` |

---
## 16. Implementation Orchestration

### 16.1 Why This Section Exists

Sections 1–15 describe the *target* — what the tool looks like once it is built. This section describes *how to build it across multiple work sessions*, where each session may be subject to context-window or plan-tier limits and the build will not finish in one sitting.

The runtime state-tracking machinery in §6 (SQLite request DB, job history JSONL, config archival) tracks what the tool *does once it exists*. It does not track the build process itself. That is the gap this section fills.

The build is orchestrated through three plain files in the repo root:

| File | Purpose | Updated |
|---|---|---|
| `CLAUDE.md` | Persistent context for Claude Code: what the project is, where the plan lives, how to behave each session. | Rarely (when conventions change) |
| `IMPLEMENTATION_STATUS.md` | The live progress tracker — every step from §13 with a status, dates, and notes. | At least once per session |
| Git commit history | The immutable record of what code actually changed when. | Per step (or sub-step) |

`CLAUDE.md` and `IMPLEMENTATION_STATUS.md` are committed to the repo. Together they answer two questions: *"what is this project?"* (CLAUDE.md) and *"where am I in building it?"* (IMPLEMENTATION_STATUS.md).

### 16.2 The Status File

`IMPLEMENTATION_STATUS.md` is pre-populated with every numbered step from §13 (Steps 0 through 19, including 0.5 and 0.75). Each step has:

- **Status**: `☐ todo` / `🔄 in-progress` / `✅ done` / `⚠️ blocked`
- **Started** / **Completed**: ISO dates
- **Validation**: a one-line note recording how the step's validation criterion (from §13) was satisfied
- **Notes**: any deviations from plan, deferred items, or things to revisit

The file also contains a **Current State** block at the top — what step is active right now, what the next concrete action is, and any in-flight work that hasn't been committed yet — and a **Session Log** at the bottom, append-only, one entry per session.

The Current State block is the single most important element. It is what a fresh session reads first and what tells it where to resume. It must always reflect the actual state of the working tree at the moment the session ended.

### 16.3 Session Lifecycle

Every session follows the same four-step protocol. The protocol exists because the alternative — re-deriving "where are we?" from the plan, the codebase, and memory — burns context and produces inconsistent restart points.

**1. Open.** Read `IMPLEMENTATION_STATUS.md` end-to-end. Read the Current State block carefully. If the next action references a specific section of the plan (e.g. "implement §3.2 `state_manager.py`"), read only that section, not the whole plan.

**2. Work.** Execute the next action. If a step is large, break it into sub-steps and commit each one separately. Don't try to land a whole §13 step in one commit unless it's genuinely small.

**3. Checkpoint.** Whenever a sub-step is done, commit it. Commit messages follow the format `Step N.M: <one-line description>`. Tests/validation criteria from §13 are run as part of the checkpoint.

**4. Close.** Before ending the session, update `IMPLEMENTATION_STATUS.md`:
- Mark completed steps `✅ done` with completion date and validation note
- Update the Current State block to reflect the new resume point
- Add a Session Log entry: date, what was done, what's left in flight, the very next concrete action
- Commit the status file change with message `status: end of session <date>`

The Close step is non-negotiable. A session that runs out of context mid-work is fine — what is *not* fine is a session that ends without leaving a clean handoff. If you sense the session is filling up, stop coding and do the Close step while you still have room.

### 16.4 Git as the Immutable Trail

`IMPLEMENTATION_STATUS.md` is the human-readable view of progress. `git log` is the source of truth. If the two ever disagree, `git log` wins and the status file gets corrected.

Conventions:

- One step per branch is overkill for this project; work directly on `main` (or a single long-lived `build` branch) and commit per sub-step.
- Commit message format: `Step <N.M>: <imperative one-line>`. Examples: `Step 1: Project scaffold + Pydantic schemas`, `Step 7.2: SQLite state manager — canonical_request_id`, `Step 9.3: Port bot_investigation transform`.
- The Session Log entry for each session should reference the commit SHA range it covers, so you can `git log <start>..<end>` to see exactly what shipped.

### 16.5 Running This with Claude Code

[Claude Code](https://docs.claude.com/en/docs/claude-code/overview) is Anthropic's terminal-based agentic coding tool. It is the right tool for executing this plan because (a) it operates directly on the repo, (b) it reads `CLAUDE.md` automatically at the start of every session, and (c) it handles the read-files / edit-files / run-tests loop without manual copy-paste. A Pro plan covers Claude Code usage.

#### One-time setup

1. Install Claude Code following the instructions at <https://docs.claude.com/en/docs/claude-code/setup>. The native installer is recommended; npm install is deprecated.
2. From the repo root, run `claude` to verify it starts.
3. Confirm `CLAUDE.md`, `IMPLEMENTATION_STATUS.md`, and the technical plan (`docs/Adobe_Downloader_Technical_Plan.md`) all exist in the repo and are committed.

#### Per-session workflow

Open a terminal in the repo root and run `claude`. The first prompt of every session is the same:

> Read `IMPLEMENTATION_STATUS.md`, then tell me where we are and what the next concrete action is. Do not start coding yet.

Claude Code will read the status file (and `CLAUDE.md` automatically) and report the resume point. Confirm the next action is what you expected, then say "go." Claude executes the work, runs the validation criteria, commits per sub-step, and updates the status file.

When you sense the session is running long, end with:

> Wrap up — finish the current sub-step if you're close, otherwise stop cleanly. Update IMPLEMENTATION_STATUS.md, write a Session Log entry, and commit. Tell me what's left in flight and what to do first next session.

The next session opens with the same first prompt and the loop continues.

#### What to put in CLAUDE.md vs the plan vs the status file

These three files have non-overlapping jobs and the boundaries matter:

- **`CLAUDE.md`** — short, stable, answers "what kind of project is this and how should I behave in every session." Coding conventions (Python 3.12+, minimal deps from §1.8), the session protocol, where to find the plan and status. Target under 100 lines. Doesn't change between sessions.
- **The plan** (`docs/Adobe_Downloader_Technical_Plan.md`) — long, stable, the *spec*. Read on demand, not by default. Claude Code only loads the section relevant to the current step.
- **`IMPLEMENTATION_STATUS.md`** — short-to-medium, *changes every session*, the *log*. Read by default at session start. The state of the build.

If a piece of information would be useful in every session forever, it goes in `CLAUDE.md`. If it would be useful only when working on a specific step, it stays in the plan. If it describes what's been done or what's next, it goes in the status file.

### 16.6 What "Done" Looks Like

The build is complete when:

- Every step in `IMPLEMENTATION_STATUS.md` is marked `✅ done`.
- Step 19 (end-to-end validation) has passed against real production runs.
- The status file's Current State block reads "Build complete — see Session Log for full history."

At that point `IMPLEMENTATION_STATUS.md` becomes a historical record. It can be moved to `docs/build_history.md` if desired, or left in place as a forever-monument to the migration.

---


*End of plan. This document covers every workflow identified in the JS codebase (including all FollowAlongSteps files) and provides a complete specification for module-by-module implementation.*
