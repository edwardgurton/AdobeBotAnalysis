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

**Active step:** *(none yet — build has not started)*

**Last commit:** *(n/a)*

**Next concrete action:** Begin Step 0 — File inventory and disposition. Open `Full__Repo_XML` in the project files, walk every JS file, and record disposition (port / consolidate / eliminate / data-migrate / archive / defer) in `docs/file_inventory.md`.

**In-flight (uncommitted) work:** *(none)*

**Blockers:** *(none)*

---

## Phase 0 — Audit and Preparation

### ☐ Step 0 — File inventory and disposition
- **Started:** —
- **Completed:** —
- **Validation:** `docs/file_inventory.md` exists and lists every file in the JS repo with a disposition tag.
- **Notes:**

### ☐ Step 0.5 — Data migration
- **Started:** —
- **Completed:** —
- **Validation:** `scripts/migrate_data.py` runs cleanly; migrated files exist in the new locations per §15.6 of the plan; `docs/data_migration_guide.md` exists.
- **Notes:**

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

*(no entries yet)*
