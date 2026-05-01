# `adobe-downloader` — Project Memory

This file is loaded automatically at the start of every Claude Code session in this repo. Keep it lean.

## What this project is

`adobe-downloader` is a Python CLI tool that replaces a JS codebase (`downloadAdobeTableLocal`) for downloading, transforming, and managing Adobe Analytics report data. The full architectural spec lives in **`docs/Adobe_Downloader_Technical_Plan.md`**. That document is authoritative — when in doubt, defer to it.

The build is being executed step-by-step from §13 of the plan. Progress is tracked in **`IMPLEMENTATION_STATUS.md`** in the repo root.

## Session protocol (every session, no exceptions)

1. **Open.** Read `IMPLEMENTATION_STATUS.md` end-to-end. Pay particular attention to the **Current State** block. If the next action references a section of the plan, read only that section — do not re-read the whole plan.
2. **Confirm.** Tell the user where we are and what the next concrete action is. Wait for confirmation before coding.
3. **Work.** Execute the next action. For larger steps, break into sub-steps and commit each separately.
4. **Checkpoint.** Run the validation criterion from §13 of the plan. Commit using the format `Step <N.M>: <imperative description>`.
5. **Close.** Before the session ends, update `IMPLEMENTATION_STATUS.md`:
   - Mark completed steps `✅ done` with completion date and validation note.
   - Update the **Current State** block to the new resume point.
   - Append a **Session Log** entry: date, commits, what was done, what's in flight, next action.
   - Commit the status file with message `status: end of session <YYYY-MM-DD>`.

If context is filling up mid-work, stop coding and do the Close step while there's room. A clean handoff is more valuable than a half-finished extra sub-step.

## Hard conventions

These are from §1 of the plan and are non-negotiable:

- **Python 3.12+.** No older versions.
- **Minimal dependencies.** `httpx`, `click`, `pyyaml`, `pydantic`, `tenacity`, plus stdlib. No ORMs, no task queues, no Docker.
- **Configuration over code.** Every job is a YAML config validated by Pydantic at load time. Never hard-code job parameters in Python.
- **Every API request is tracked** in the SQLite state DB before it executes. No exceptions.
- **The tool never silently deletes data.** Cleanup is opt-in and explicit.

## Code style

- Format with `ruff format`. Lint with `ruff check`.
- Type-annotate every function signature. Run `mypy` clean.
- Tests use `pytest`. Fixtures live in `tests/fixtures/`.
- Async by default for I/O. Sequential for steps within a composite job.
- Imports: stdlib first, third-party second, local third. No wildcard imports.

## Git conventions

- Work on `main` (or a long-lived `build` branch), not per-step branches.
- One commit per sub-step. Commit message format: `Step <N.M>: <imperative one-line>`.
- Examples: `Step 1: Pydantic schemas for all job types`, `Step 7.2: SQLite canonical_request_id`, `status: end of session 2026-05-03`.
- Never commit anything from `jobs/` (run configs), `credentials/`, or any output folder.

## Where things live

- **Plan (spec):** `docs/Adobe_Downloader_Technical_Plan.md` — read on demand only
- **Progress (log):** `IMPLEMENTATION_STATUS.md` — read every session
- **Source repo (legacy JS):** `legacy_js/` directory in the repo root — read when porting a specific module
- **Test fixtures:** `tests/fixtures/` (created in Step 0.75)
- **Migrated reference data:** `data/` (created in Step 0.5)

## What NOT to do

- Don't re-read the whole plan at session start. The status file points you to the relevant section.
- Don't skip the Close step. Ever.
- Don't try to land a whole §13 step in one commit unless it's genuinely small (e.g. Step 16 might be one commit; Step 7 absolutely will not be).
- Don't invent dependencies beyond the five listed above without explicitly asking first.
- Don't delete files from the legacy JS repo or from output folders. The migration is one-way (build new, leave old alone) until end-to-end validation in Step 19 passes.
