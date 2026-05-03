# `adobe-downloader` — Implementation Status

This file is the live progress tracker for the build described in the technical plan (`docs/Adobe_Downloader_Technical_Plan.md`).

**See §16 of the plan for the orchestration framework.** Briefly:

- Read this file at session start.
- Update the **Current State** block and **Session Log** at session end.
- Commit per sub-step using format `Step <N.M>: <description>`.
- `git log` is the source of truth; this file is the human-readable view.

Status legend: `☐ todo` · `🔄 in-progress` · `✅ done` · `⚠️ blocked`

---

## Current State

**Active step:** Step 12 — Composite job runner

**Last commit:** `Step 11: lookup generation`

**Next concrete action:** Begin Step 12. Implement `flows/composite_job.py` and wire composite job YAML configs. The composite runner executes a sequence of steps (report_download, segment_creation, lookup_generation, transform_concat) where each step's output can be referenced by later steps via `step_output` sources. Validate with a full bot investigation composite job (3 RSIDs × 2 days) that runs end-to-end and resolves inter-step references correctly.

**In-flight (uncommitted) work:** *(none)*

**Blockers:** *(none)*

---

## Phase 0 — Audit and Preparation

### ✅ Step 0 — File inventory and disposition
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `docs/file_inventory.md` exists and lists all 68 JS files + ~115 non-JS files with disposition tags.
- **Notes:** `legacy_js/` is the authoritative source (replaces `Full__Repo_XML` project knowledge reference); CLAUDE.md and IMPLEMENTATION_STATUS.md updated to reflect this.

### ✅ Step 0.5 — Data migration
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `scripts/migrate_data.py` runs cleanly (no warnings); migrated files verified in `data/`, `jobs/inputs/`, `jobs/templates/`, `credentials/`, `docs/reference/`; `docs/data_migration_guide.md` exists.
- **Notes:** Fixed a header-extraction bug (commented example was being picked up instead of active header string). Script is idempotent — safe to re-run.

### ✅ Step 0.75 — Capture test fixtures
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `tests/fixtures/` contains input JSONs and expected CSVs for all 6 transform types, plus 3 compiled request bodies.
- **Notes:** Fixtures are synthetic (derived from JS source analysis, not real API calls). After Step 5 (first live download), supplement with real API responses to catch edge cases. See `tests/fixtures/README.md` for full documentation.

---

## Phase 1 — Foundation

### ✅ Step 1 — Project scaffold + config + logging + templates
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `adobe-downloader validate --config jobs/examples/<any>.yaml` parses all 10 examples and all 19 templates without schema errors. File-not-found warnings (exit 2) are expected for examples referencing local data paths.
- **Notes:** One pre-existing non-job-config file (`client_config_template.yaml`) correctly fails validation — it is a credential template, not a job config. `RsidSource.list` field renamed to `rsid_list` with alias `list` to avoid Python builtin shadowing bug.

### ✅ Step 2 — Auth + API client
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `adobe-downloader list-users --client Legend` — CLI wired and imports verified. Live token-fetch + user-list validation requires running against real credentials.
- **Notes:** `core/auth.py` posts to IMS token endpoint with client-credentials grant; 5-minute expiry buffer via `time.monotonic()`. `AdobeClient` caches token in-memory, exposes `get_users()` (paginated), `get_authenticated_user()`, and stubs for `get_report()`, `create_segment()`, `share_segment()`, `get_report_suites()`. Rate-limiter hook intentionally deferred to Step 3.

### ✅ Step 3 — Rate limiter
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** 10 pytest tests pass: 4 sync (retryable classification) + 6 async (execute result, args, 50-request window, global pause delay, pause expiry, concurrency cap). `asyncio_mode = "auto"` added to `pyproject.toml`; `pytest-asyncio` added as dev dependency.
- **Notes:** `_get()` and `_post()` private helpers wrap every `AdobeClient` call with rate limiter + tenacity retry (429/500/502/503, 5 attempts, exponential backoff). 429 triggers `set_pause(10s)` before the next tenacity sleep.

### ✅ Step 4 — Request builder
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** 11 pytest tests pass: 3 fixture-match tests (botInvestigationMetricsByBrowser, botFilterExcludeMetricsByMonth, toplineMetricsForRsidValidation) + 8 structural invariant tests. `load_report_registry()` loads 50 report definitions from 8 YAML files cleanly.
- **Notes:** `ReportDefinitionInline.metrics` contains ADDITIONAL metrics only (not visitors/visits); builder always prepends visitors (sort:desc) and visits (sort:desc) as columnIds 0 and 1. `report_def.segments` = base/fixed segments; `segments` param to `build_request()` = runtime extra segments (e.g. a specific bot rule). `config/report_definitions.py` provides `ReportDefinitionFile` Pydantic model + `load_report_registry()` for resolving `report_ref`/`report_group` in Step 5+.

---

## Phase 2 — Report Download

### ✅ Step 5 — Basic download (single request)
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `adobe-downloader run -c jobs/validation/step5_live_validation.yaml` (RSID `trillioncoverscom`, report `botInvestigationMetricsByBrowser`, Jan 2025) returned 984 rows across 2 pages; page-0 JSON saved to `C:/Users/EdwardGurton/Documents/adobe_test_output/Legend/JSON/`. Structure (columnIds, dimension, rows) matches expected shape. Note: pagination (totalPages > 1) is a known limitation deferred to Step 6.
- **Notes:** `flows/report_download.py` — `download_report(client, request_body, output_path)` makes one API call and saves JSON; `make_output_path()` matches JS naming convention (`{base}/{client}/JSON/{client}_{report}{_extra}_{DIMSEG{id}_}{from}_{to}.json`). `load_report_group()` added to `config/report_definitions.py`. `run` CLI command wired: resolves report defs (report_ref / report_group / inline), resolves first RSID (single/list/file), iterates report defs sequentially. Fixed Windows terminal Unicode encoding (→/✓ → ASCII). 35 tests pass.

### ✅ Step 6 — Date, RSID, and segment iteration
- **Started:** 2026-05-01
- **Completed:** 2026-05-01
- **Validation:** `adobe-downloader validate -c jobs/validation/step6_live_validation.yaml` passes. Config covers 2 RSIDs × 3 months (6 download slots). Live run against real API would produce 6 files. 20 new tests (55 total) cover all iteration modes.
- **Notes:** `iterate_dates()` handles full/month/day intervals including partial months and year boundaries. `iterate_rsids()` handles single/list/file sources. `iterate_segments()` yields (seg_id_for_filename, seg_ids_for_request) pairs — inline adds all IDs to every request (no filename suffix); segment_list_file yields one pair per segment. `run` command now iterates RSIDs × date intervals × segments × report defs. step_output/latest_segment_list segment sources raise NotImplementedError (resolved at composite job level in Step 12).

### ✅ Step 7 — State persistence
- **Started:** 2026-05-02
- **Completed:** 2026-05-02
- **Validation:** 76 tests passing (21 new). `run` command now skips completed requests on resume, copies shared-report files when canonical_request_id is set. `status`, `retry`, `reset` subcommands implemented. Live kill-and-restart validation requires a real multi-RSID run.
- **Notes:** `adobe_downloader/state_manager.py` — SQLite 3-table schema (jobs/requests/step_state), `StateManager` class, `compute_request_key()`, `compute_job_id()`, `compute_request_body_hash()`. State DB at `<output_base>/<client>/.state/<job_id>.db`. Shared-report detection: second request with same request_body_hash in same job gets `canonical_request_id` set; `run` copies canonical file instead of re-downloading.

---

## Phase 3 — Transform + Concatenate

### ✅ Step 8 — Base transform + CSV concatenation
- **Started:** 2026-05-02
- **Completed:** 2026-05-02
- **Validation:** 99 tests passing (23 new). `transform_report()` matches fixtures byte-for-byte for both dimensional (rows) and summary (summaryData.totals) shapes. `concatenate_csvs()` merges multiple CSVs correctly, respects file patterns, and supports custom header renaming. `transform` CLI command wired.
- **Notes:** `_parse_filename_parts()` uses longest-match against `data/report_headers/` YAMLs to correctly split `{report_name}` from `{file_name_extra}` (e.g. RSID suffix) in filenames. `make_csv_output_path()` converts `.../JSON/...json` to `.../CSV/...csv`.

### ✅ Step 9 — Specialised transforms
- **Started:** 2026-05-03
- **Completed:** 2026-05-03
- **Validation:** 20 new tests pass (119 total); all 5 specialised transforms produce byte-for-byte matches against fixtures.
- **Notes:** Created `adobe_downloader/transforms/specialized.py` — `transform_bot_investigation` (delegates to base), `transform_bot_validation` (appends requestName/botRuleName/rsidName from parts[1..3]), `transform_bot_rule_compare` (hardcoded headers, complex filename parse), `transform_final_bot_rule_metrics` (appends botRuleName/rsidName from parts[4]/parts[3] + fromDate/toDate), `transform_summary_total_only` (delegates to base). `transform_report_dispatch()` + `_detect_transform_type()` for auto-routing. Fixed `LegendFinalBotMetricsCurrentIncludeByYear.yaml` and `LegendFinalBotMetricsDevelopmentIncludeByYear.yaml` (were missing botRuleName and rsidName columns); fixed `tests/fixtures/transforms/final_bot_rule_metrics/expected.csv` header accordingly.

---

## Phase 4 — Segments + Lookups

### ✅ Step 10 — Segment creation
- **Started:** 2026-05-03
- **Completed:** 2026-05-03
- **Validation:** 35 new tests pass (154 total). `run_segment_creation()` creates single + dual condition segments, handles Compare/Validate/Special rows, writes compare CSV, validate CSV, and segment list JSON. `get-segment` and `search-lookup` CLI commands wired. Live API validation requires running against real credentials with a segment creation list CSV.
- **Notes:** `segments/create_segment.py` — dimension mapping, predicate builders, lookup file resolver, `resolve_dimension_value()` (raises `LookupError` if value missing from local file). `flows/segment_creation.py` — `run_segment_creation()`, `transform_to_bot_rule_name()`, `transform_to_validate_bot_rule_name()`, `_ensure_max_length()`. `utils/rsid_lookup.py` — `load_rsid_lookup()`, `lookup_rsid()`, `find_latest_rsid_file()`. `segments/dim_to_segments.py` stub raises `NotImplementedError` — fully wired in Step 12. `AdobeClient.create_segment()` and `AdobeClient.share_segment()` were already implemented in Step 2.

### ✅ Step 11 — Lookup generation
- **Started:** 2026-05-03
- **Completed:** 2026-05-03
- **Validation:** 21 new tests pass (175 total). `generate_lookup_file()` downloads dimension values, writes sorted `value|id` pairs with header. `search_lookup_value()` checks local cache first, then iterates RSIDs and updates file incrementally. `run_lookup_generation()` wired to `run` CLI. Live API validation requires running against real credentials for `BrowserType` and comparing to `data/lookups/variablesbrowsertype/lookup.txt`.
- **Notes:** `segments/lookup_generator.py` — `clean_dim_name()`, `write_lookup_file()`, `merge_into_lookup_file()`, `generate_lookup_file()`. `segments/lookup_searcher.py` — `search_lookup_value()` iterates RSID list, stops early when target found, skips failed RSIDs. `flows/lookup_generation.py` — thin orchestrator. CLI `run` command now dispatches `lookup_generation` job type via `_run_lookup_generation_job()`. `lookup_base` defaults to `data/lookups/` relative to CWD.

---

## Phase 5 — Composite Jobs

### ☐ Step 12 — Composite job runner
- **Started:** —
- **Completed:** —
- **Validation:** Full bot investigation composite job (3 RSIDs × 2 days) runs end-to-end, with output references resolving correctly between steps and step-level resume working.
- **Notes:**

### ☐ Step 13 — Bot rule comparison flow
- **Started:** —
- **Completed:** —
- **Validation:** 2 RSIDs × 1 rule run completes; segment files and AllTraffic file-copy outputs verified against expected.
- **Notes:**

### ☐ Step 14 — Final bot metrics flow
- **Started:** —
- **Completed:** —
- **Validation:** 3 RSIDs × 1 segment list run completes; all expected output files present.
- **Notes:**

---

## Phase 6 — Post-processing + Polish

### ☐ Step 15 — Post-processing + job history
- **Started:** —
- **Completed:** —
- **Validation:** After a job completes, JSONs are moved to `_processed/`, individual CSVs are zipped, `.history/job_history.jsonl` has a new line, and `.history/configs/` contains the archived config. `adobe-downloader history` and `adobe-downloader cleanup` work.
- **Notes:**

### ☐ Step 16 — Test mode
- **Started:** —
- **Completed:** —
- **Validation:** `--test` flag applied to a real job config limits the downloads as defined in `test_limits` block.
- **Notes:**

### ☐ Step 17 — Validation flow
- **Started:** —
- **Completed:** —
- **Validation:** Job started and killed; `adobe-downloader validate-output` detects missing files and re-downloads them successfully.
- **Notes:**

### ☐ Step 18 — Report suite updater
- **Started:** —
- **Completed:** —
- **Validation:** Generated RSID lists match (or are an explainable superset/subset of) the current JS-generated RSID lists.
- **Notes:**

### ☐ Step 19 — End-to-end validation
- **Started:** —
- **Completed:** —
- **Validation:** Full bot investigation, full bot validation, cube report, and RSID-updater→investigation→validate→transform pipelines all run against real Adobe data and produce outputs that match (or are an explainable improvement on) the JS production runs.
- **Notes:**

---

## Session Log

*Append-only. One entry per session. Most recent at the bottom.*

<!-- Template:
### YYYY-MM-DD
- **Worked on:** Step X.Y
- **Commits:** `<sha-range>` (N commits)
- **Done this session:** ...
- **Left in flight:** ...
- **Next action:** ...
-->

### 2026-05-01 (session 1)
- **Worked on:** Steps 0 and 0.5
- **Commits:** `Step 0: File inventory and disposition`, `Step 0.5: Data migration script and guide` (2 commits)
- **Done this session:** Updated CLAUDE.md and IMPLEMENTATION_STATUS.md to replace `Full__Repo_XML` reference with `legacy_js/` directory. Inventoried all 68 JS files and ~115 non-JS files with disposition tags (`docs/file_inventory.md`). Wrote `scripts/migrate_data.py` which converts JS arrays to plain text/JSON, extracts header definitions to YAML, and copies all data files to their target locations. Fixed a comment-line regex bug in header extraction. Produced `docs/data_migration_guide.md` documenting all migrations and exclusions.
- **Left in flight:** Nothing.
- **Next action:** Step 1 — Project scaffold. Create `pyproject.toml`, package skeleton, Pydantic job config schemas, logging setup.

### 2026-05-01 (session 2)
- **Worked on:** Step 1
- **Commits:** `Step 1.1: pyproject.toml + package skeleton + logging + CLI entry point`, `Step 1.2: 19 job config templates + 10 worked examples` (2 commits)
- **Done this session:** Created `pyproject.toml` (setuptools build system, 5 dependencies: click/httpx/pydantic/pyyaml/tenacity). Created `adobe_downloader/` package with `__init__.py`, `cli.py` (Click CLI with validate + stub commands), `config/schema.py` (Pydantic discriminated union covering all 6 job types), `config/loader.py` (YAML load + file reference checks + credential check), `utils/logging.py` (dual-handler logging). Fixed Python 3.13 builtin-shadowing bug: `RsidSource.list` renamed to `rsid_list` with alias. Created 19 job config templates in `jobs/templates/` and 10 worked Legend examples in `jobs/examples/`. All validate cleanly.
- **Left in flight:** Nothing.
- **Next action:** Step 2 — `core/auth.py` (OAuth token fetch, 5-minute expiry buffer) + `core/api_client.py` (`AdobeClient`). Validate with `adobe-downloader list-users --client Legend`.

### 2026-05-01 (session 4)
- **Worked on:** Step 3
- **Commits:** `Step 3: core/rate_limiter.py — sliding-window limiter + 429 global pause + tenacity retry; wire into AdobeClient; 10 passing tests` (1 commit)
- **Done this session:** Created `adobe_downloader/core/rate_limiter.py` — `SlidingWindowRateLimiter` (12 req/6s sliding window, `asyncio.Semaphore` for concurrency cap, `set_pause()` for global 429 pause, `execute()` with 120s `asyncio.wait_for` timeout). `make_retry()` returns a `tenacity` decorator wired to call `set_pause(10s)` on 429 before retrying (5 attempts, exponential backoff 2–30s, retries on 429/500/502/503). Refactored `AdobeClient` to use `_get()` / `_post()` helpers that go through the limiter + retry; all 6 public methods updated. Added `pytest-asyncio` dev dependency; `asyncio_mode = "auto"` in `pyproject.toml`. 10 tests written and passing.
- **Left in flight:** Nothing.
- **Next action:** Step 4 — `core/request_builder.py`. Port JS request-body construction for ranked reports. Validate against fixtures in `tests/fixtures/`.

### 2026-05-01 (session 5)
- **Worked on:** Step 4
- **Commits:** `Step 4.1: core/request_builder.py — build_request(); config/report_definitions.py — Pydantic schema + load_report_registry(); 8 report_definitions/*.yaml group files; 11 passing tests` (1 commit)
- **Done this session:** Created `core/request_builder.py` — `build_request(report_def, date_range, rsid, segments)` always prepends visitors/visits (sort:desc) as columns 0/1, appends `report_def.metrics` from column 2, adds dateRange + base segments + runtime segments to globalFilters, conditionally includes dimension, sets full settings block. Created `config/report_definitions.py` — `ReportDefinitionFile` / `ReportEntry` / `ReportDefinitionDefaults` Pydantic models + `load_report_registry()` that scans `report_definitions/*.yaml` and resolves defaults inheritance. Created 8 `report_definitions/*.yaml` group files covering all 50 Legend reports ported from `legacy_js/config/client_configs/clientLegend.yaml` (bot_investigation, bot_investigation_unfiltered, bot_validation, final_bot_metrics, lookup, topline, segment_builder, clickouts). 21 total tests pass (11 new).
- **Left in flight:** Nothing.
- **Next action:** Step 5 — Basic download. Wire `build_request()` + `load_report_registry()` into a `run` CLI command. Implement single-request download, save JSON to output folder. Validate against JS-generated JSON for one report.

### 2026-05-01 (session 6)
- **Worked on:** Step 5
- **Commits:** `Step 5.1` (flows + CLI + tests), `Step 5.2` (Windows Unicode fix) (2 commits)
- **Done this session:** Created `adobe_downloader/flows/__init__.py` and `adobe_downloader/flows/report_download.py` — `download_report()` + `make_output_path()`. Added `load_report_group()` to `config/report_definitions.py`. Wired `run` CLI command. Fixed Windows terminal Unicode. Live validated: `trillioncoverscom` / `botInvestigationMetricsByBrowser` / Jan 2025 → 984 rows, correct structure. 14 new tests, 35 total.
- **Left in flight:** Nothing.
- **Next action:** Step 6 — date/RSID/segment iteration (`iterate_dates()`, `iterate_rsids()`, `segment_list_file` source, full `run` loop).

### 2026-05-01 (session 7)
- **Worked on:** Step 6
- **Commits:** `Step 6.1` (iteration helpers + 20 tests), `Step 6.2` (run command full loop + validation config) (2 commits)
- **Done this session:** Added `iterate_dates()`, `iterate_rsids()`, `load_segment_list()`, `iterate_segments()` to `flows/report_download.py`. Updated `run` CLI command to drive the full RSIDs × date intervals × segments × reports loop. Created `jobs/validation/step6_live_validation.yaml` (2 RSIDs × 3 months). 55 tests passing.
- **Left in flight:** Nothing.
- **Next action:** Step 7 — SQLite state DB (`jobs/state_manager.py`), `canonical_request_id`, resume-on-restart, `status`/`retry`/`reset` CLI subcommands.

### 2026-05-02 (session 8)
- **Worked on:** Step 7
- **Commits:** `Step 7.1: state_manager.py — SQLite schema, StateManager, canonical_request_id, 21 passing tests`, `Step 7.2: wire StateManager into run command (resume/skip/copy); status, retry, reset CLI subcommands` (2 commits)
- **Done this session:** Created `adobe_downloader/state_manager.py` — SQLite state DB with 3-table schema (jobs/requests/step_state), `StateManager` class with `track_request()` / `mark_complete()` / `mark_failed()` / `is_complete()` / `get_summary()` / `reset_failed()` / `reset_all()` / `full_reset()`. `canonical_request_id` auto-detected by matching `request_body_hash` within a job (enables shared-report file copy). Wired into `run` command: computes `job_id` from config hash, skips completed requests on resume, copies files for canonical-linked requests. Added `--no-resume` flag to `run`. Implemented `status`, `retry` (--failed-only), and `reset` (--confirm) CLI subcommands. 76 tests passing (21 new).
- **Left in flight:** Nothing.
- **Next action:** Step 8 — Base transform + CSV concatenation. Port JSON→CSV transform from `legacy_js/`. Wire `transform` command.

### 2026-05-02 (session 9)
- **Worked on:** Step 8
- **Commits:** `Step 8.1: transforms/base.py — transform_report() JSON→CSV; transforms/concatenate.py — concatenate_csvs(); 23 passing tests`, `Step 8.2: wire transform CLI command — per-file JSON→CSV + optional concatenation` (2 commits)
- **Done this session:** Created `adobe_downloader/transforms/__init__.py`, `adobe_downloader/transforms/base.py` — `transform_report()` handles both dimensional (rows) and summary (summaryData.totals) JSON shapes; `_parse_filename_parts()` uses longest-match YAML lookup to separate report_name from file_name_extra (e.g. RSID appended to stem); `make_csv_output_path()` mirrors JSON path under CSV/. Created `adobe_downloader/transforms/concatenate.py` — `concatenate_csvs()`. Wired `transform` CLI command (per-file JSON→CSV + optional concat). 99 tests pass total (23 new).
- **Left in flight:** Nothing.
- **Next action:** Step 9 — Specialised transforms for bot_investigation, bot_rule_compare, bot_validation, final_bot_rule_metrics, summary_total_only types.

### 2026-05-03 (session 10)
- **Worked on:** Step 9
- **Commits:** `Step 9: specialized transforms — bot_investigation, bot_validation, bot_rule_compare, final_bot_rule_metrics, summary_total_only` (1 commit)
- **Done this session:** Created `adobe_downloader/transforms/specialized.py` with 5 specialised transform functions + `transform_report_dispatch()` auto-router. Fixed `LegendFinalBotMetrics*.yaml` header YAMLs (missing botRuleName/rsidName columns) and corrected `final_bot_rule_metrics/expected.csv` header line. 20 new tests, 119 total passing.
- **Left in flight:** Nothing.
- **Next action:** Step 10 — Segment creation. Implement `create_segment()` in `AdobeClient`, wire CLI, validate with real API, write segment list JSON to `data/segment_lists/`.

### 2026-05-03 (session 11)
- **Worked on:** Step 10
- **Commits:** `Step 10: segment creation` (1 commit)
- **Done this session:** Created `adobe_downloader/utils/rsid_lookup.py` (RSID name→ID lookup from colon-separated files, auto-discovery of latest file). Created `adobe_downloader/segments/` package: `create_segment.py` (dimension mapping constants, predicate builders, lookup resolver), `share_segment.py`, `save_segment.py`, `dim_to_segments.py` (stub, wired in Step 12). Created `adobe_downloader/flows/segment_creation.py` — `run_segment_creation()` reads CSV, validates rows, creates single/dual condition segments via API, shares, writes compare/validate CSVs and segment list JSON; bot rule name transforms ported from JS. Updated `cli.py`: `run` command dispatches `segment_creation` job type; added `get-segment` and `search-lookup` commands. 35 new tests, 154 total.
- **Left in flight:** Nothing.
- **Next action:** Step 11 — Lookup generation. `flows/lookup_generation.py`, `segments/lookup_generator.py`, `segments/lookup_searcher.py`. Wire `lookup_generation` job type.

### 2026-05-03 (session 12)
- **Worked on:** Step 11
- **Commits:** `Step 11: lookup generation` (1 commit)
- **Done this session:** Created `adobe_downloader/segments/lookup_generator.py` — `clean_dim_name()`, `write_lookup_file()`, `merge_into_lookup_file()`, `_rows_to_pairs()`, `generate_lookup_file()`. Created `adobe_downloader/segments/lookup_searcher.py` — `search_lookup_value()` checks local file first, then iterates RSID list, merges new discoveries, stops early when target found. Created `adobe_downloader/flows/lookup_generation.py` — thin orchestrator calling `generate_lookup_file()`. Updated `cli.py`: `run` dispatches `lookup_generation` job type; added `_run_lookup_generation_job()` helper. 21 new tests, 175 total passing.
- **Left in flight:** Nothing.
- **Next action:** Step 12 — Composite job runner.

### 2026-05-01 (session 3)
- **Worked on:** Step 2
- **Commits:** `Step 2.1: core/auth.py (OAuth token fetch + expiry cache) and core/api_client.py (AdobeClient)`, `Step 2.2: wire list-users CLI command to AdobeClient.get_users()` (2 commits)
- **Done this session:** Created `adobe_downloader/core/auth.py` — async `fetch_token()` posts client-credentials grant to Adobe IMS token endpoint, returns `(access_token, expiry_monotonic)` with 5-minute buffer. Created `adobe_downloader/core/api_client.py` — `AdobeClient` with in-memory token cache, `get_users()` (paginated), `get_authenticated_user()`, and method stubs for `get_report()`, `get_report_suites()`, `create_segment()`, `share_segment()`. Updated `cli.py`: `list-users` command now calls `asyncio.run(AdobeClient.get_users())` with friendly error output. All imports verified clean.
- **Left in flight:** Nothing. Live `adobe-downloader list-users --client Legend` validation requires running with real credentials.
- **Next action:** Step 3 — `core/rate_limiter.py`. Sliding-window limiter + global pause on 429. Wire into `AdobeClient`. Validate with stress test (50 rapid mock requests).
