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

**Active step:** Step 7 — State persistence

**Last commit:** `Step 6.2: update run command — full RSID x date interval x segment iteration loop`

**Next concrete action:** Begin Step 7. Create `jobs/state_manager.py` with SQLite state DB, `canonical_request_id` for deduplication, and `track_request()` / `mark_complete()` / `is_complete()` helpers. Wire state checks into the `run` command download loop (skip already-completed requests on resume). Add `status`, `retry`, `reset` subcommands to `cli.py`. Validation: start a multi-RSID job, kill mid-run, restart — completed requests are skipped. Shared-report copy works for 2 bot rules.

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

### ☐ Step 7 — State persistence
- **Started:** —
- **Completed:** —
- **Validation:** Job started, killed mid-run, restarted — completed requests are skipped on resume. Shared-report copy works for 2 bot rules.
- **Notes:**

---

## Phase 3 — Transform + Concatenate

### ☐ Step 8 — Base transform + CSV concatenation
- **Started:** —
- **Completed:** —
- **Validation:** Transformed CSVs from Step 6 JSONs match JS output byte-for-byte.
- **Notes:**

### ☐ Step 9 — Specialised transforms
- **Started:** —
- **Completed:** —
- **Validation:** All 5 specialised transforms produce byte-for-byte matches against the fixtures captured in Step 0.75.
- **Notes:**

---

## Phase 4 — Segments + Lookups

### ☐ Step 10 — Segment creation
- **Started:** —
- **Completed:** —
- **Validation:** Test segment created and verifiable via API. Segment list JSON written to `data/segment_lists/` and consumable as input by a downstream download job.
- **Notes:**

### ☐ Step 11 — Lookup generation
- **Started:** —
- **Completed:** —
- **Validation:** Generated lookup file matches the existing JS-generated lookup file.
- **Notes:**

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

### 2026-05-01 (session 3)
- **Worked on:** Step 2
- **Commits:** `Step 2.1: core/auth.py (OAuth token fetch + expiry cache) and core/api_client.py (AdobeClient)`, `Step 2.2: wire list-users CLI command to AdobeClient.get_users()` (2 commits)
- **Done this session:** Created `adobe_downloader/core/auth.py` — async `fetch_token()` posts client-credentials grant to Adobe IMS token endpoint, returns `(access_token, expiry_monotonic)` with 5-minute buffer. Created `adobe_downloader/core/api_client.py` — `AdobeClient` with in-memory token cache, `get_users()` (paginated), `get_authenticated_user()`, and method stubs for `get_report()`, `get_report_suites()`, `create_segment()`, `share_segment()`. Updated `cli.py`: `list-users` command now calls `asyncio.run(AdobeClient.get_users())` with friendly error output. All imports verified clean.
- **Left in flight:** Nothing. Live `adobe-downloader list-users --client Legend` validation requires running with real credentials.
- **Next action:** Step 3 — `core/rate_limiter.py`. Sliding-window limiter + global pause on 429. Wire into `AdobeClient`. Validate with stress test (50 rapid mock requests).
