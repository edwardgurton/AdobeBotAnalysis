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

**Active step:** Step 0.75 — Capture test fixtures

**Last commit:** `Step 0.5: Data migration script and guide`

**Next concrete action:** Begin Step 0.75 — Capture test fixtures. For each transform type, capture a representative input JSON and expected output CSV from actual production runs. Also capture compiled request bodies for all report types. Place in `tests/fixtures/`.

**In-flight (uncommitted) work:** *(none)*

**Blockers:** Need access to actual downloaded JSON files from past production runs to capture fixtures. If no local copies exist, this step may need to defer fixture capture to after Step 5 (first live download).

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

### ☐ Step 0.75 — Capture test fixtures
- **Started:** —
- **Completed:** —
- **Validation:** `tests/fixtures/` contains representative input JSONs and expected output CSVs for every transform type, plus compiled request bodies for all report types.
- **Notes:**

---

## Phase 1 — Foundation

### ☐ Step 1 — Project scaffold + config + logging + templates
- **Started:** —
- **Completed:** —
- **Validation:** `adobe-downloader validate --config <example>` parses and validates every example config without error.
- **Notes:**

### ☐ Step 2 — Auth + API client
- **Started:** —
- **Completed:** —
- **Validation:** `adobe-downloader list-users` returns a list of users from the Adobe API using a freshly fetched and cached token.
- **Notes:**

### ☐ Step 3 — Rate limiter
- **Started:** —
- **Completed:** —
- **Validation:** Stress test with 50 rapid mock requests passes; rate limiter respects sliding window; global pause on simulated 429 works.
- **Notes:**

### ☐ Step 4 — Request builder
- **Started:** —
- **Completed:** —
- **Validation:** Generated request bodies are byte-identical to the JS-generated equivalents for all reports defined in `report_definitions/`.
- **Notes:**

---

## Phase 2 — Report Download

### ☐ Step 5 — Basic download (single request)
- **Started:** —
- **Completed:** —
- **Validation:** Downloaded JSON for one report matches JS-version JSON.
- **Notes:**

### ☐ Step 6 — Date, RSID, and segment iteration
- **Started:** —
- **Completed:** —
- **Validation:** Multi-RSID multi-date job completes correctly; segment-list-driven download iterates the expected number of files.
- **Notes:**

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

### 2026-05-01
- **Worked on:** Steps 0 and 0.5
- **Commits:** `Step 0: File inventory and disposition`, `Step 0.5: Data migration script and guide` (2 commits)
- **Done this session:** Updated CLAUDE.md and IMPLEMENTATION_STATUS.md to replace `Full__Repo_XML` reference with `legacy_js/` directory. Inventoried all 68 JS files and ~115 non-JS files with disposition tags (`docs/file_inventory.md`). Wrote `scripts/migrate_data.py` which converts JS arrays to plain text/JSON, extracts header definitions to YAML, and copies all data files to their target locations. Fixed a comment-line regex bug in header extraction. Produced `docs/data_migration_guide.md` documenting all migrations and exclusions.
- **Left in flight:** Nothing.
- **Next action:** Step 0.75 — Capture test fixtures. Need to confirm whether local production JSON files exist; if not, fixture capture defers to after Step 5.
