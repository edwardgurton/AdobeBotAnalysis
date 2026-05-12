# `adobe-downloader` — Project Memory

This file is loaded automatically at the start of every Claude Code session in this repo. Keep it lean.

## What this project is

`adobe-downloader` is a Python CLI tool for downloading, transforming, and managing Adobe Analytics report data. It replaces a legacy JS codebase (`downloadAdobeTableLocal`).

The tool is feature-complete and end-to-end validated. User documentation lives in `user-docs/`.

## Maintenance session protocol

1. **Confirm.** State what you're about to do and wait for confirmation before coding.
2. **Work.** Follow the hard conventions below. Break larger changes into commits.
3. **Validate.** Run `ruff format`, `ruff check`, `mypy`, and `pytest` before committing.

If resuming in-flight work, read `IMPLEMENTATION_STATUS.md` to understand where things were left.

## Hard conventions

These are non-negotiable:

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

- Work on `main`. One commit per logical change.
- Never commit anything from `jobs/` (run configs), `credentials/`, or any output folder.

## Where things live

- **User docs:** `user-docs/` — HTML manual, Claude reference, technical reference
- **Legacy JS source:** `legacy_js/` — reference only, do not modify
- **Test fixtures:** `tests/fixtures/`
- **Reference data:** `data/` (RSID lists, segment lists, lookups, bot rule lists)
- **Report definitions:** `report_definitions/*.yaml` — 50 named reports in 8 groups
- **Job config templates:** `jobs/templates/` — commented example YAML for each job type
- **Worked examples:** `jobs/examples/` — real Legend job configs
