# Memo: Architecture Principles for `adobe-downloader`

**To:** Project Stakeholders  
**From:** Technical Architecture Review  
**Date:** April 2026  
**Re:** Core design philosophy for the new Adobe Analytics download tooling

---

## Context

We are building `adobe-downloader`, a Python CLI tool for downloading, transforming, and managing Adobe Analytics report data. This memo sets out the principles that will govern the architecture. The intent is to establish a shared understanding of *how the tool thinks* and *how people will use it* before we commit to implementation details.

---

## Principle 1: Configuration Over Code

Every job — from a one-off report pull to a 24-hour bot investigation across 50 report suites — is expressed as a YAML config file. No job should require editing Python source code.

Report definitions, credentials, RSID lists, date ranges, and processing options are all declared in config. The tool ships with **commented templates** that explain every field, expected values, and common choices. Creating a new job should be: copy a template, change 3–5 fields, run. Config files are validated at load time with Pydantic. Invalid configs fail immediately with clear messages — never after two hours of downloading.

---

## Principle 2: Report Definitions Are a Shared Library

The most error-prone part of the current system is specifying reports — getting the right dimension ID, the right metrics, the right row limit, the right CSV headers. In the new system, reports are defined once in `report_definitions/*.yaml` and referenced by name:

```yaml
# In a job config — this is all you need:
report_ref: botInvestigationMetricsByDay

# The system looks up the dimension, metrics, row_limit, segments,
# and csv_headers from report_definitions/bot_investigation.yaml
```

Reports can be grouped (e.g., `bot_investigation` contains all 13 report types). A job config can reference an entire group and the system iterates every report:

```yaml
report_group: bot_investigation   # downloads all 13 reports
```

Inline report definitions are supported for genuine one-offs, but they are the exception. The standard path is: reference by name, trust the definition, move on. This preserves the best quality of the current `clientLegend.yaml` — named report configs you can reference anywhere — while making them version-controlled, well-structured, and impossible to accidentally break by editing the wrong line.

Adding a new report type or modifying metrics is a one-line change in one file, not a coordinated edit across header files, client YAML, and download functions.

---

## Principle 3: Jobs Are Chains, Not Scripts

The most valuable workflows are multi-step: update RSID lists → download data → validate completeness → re-download missing files → transform JSON to CSV → concatenate. Today, each step is a separate block of code that a developer uncomments and runs manually.

In the new system, a single **composite job config** declares the full chain. The key mechanism is **output references**: each step declares what it produces, and subsequent steps can reference those outputs. This replaces the manual "note this filename, paste it into the next command" pattern.

Steps support `depends_on` for conditional execution and individual resume — if a job fails at step 3, re-running it skips completed steps and picks up where it left off.

---

## Principle 4: Every Request Is Tracked

Every API request the tool makes is registered in a SQLite state database before it executes, and its outcome is recorded after. This gives us:

- **Resume.** Kill a 24-hour job, restart it, and completed requests are skipped automatically.
- **Validation.** After a run, query the state DB to find failed or missing requests — no bespoke filename-generation scripts needed.
- **Visibility.** `adobe-downloader status --config job.yaml` shows progress at any time.
- **Metadata without filenames.** Transforms can look up a file's report type, RSID, date range, and segment from the state DB instead of parsing the filename.

---

## Principle 5: Optimise Expensive Operations Automatically

The Adobe Analytics API has strict rate limits and some requests are slow. Two built-in optimisations:

**Shared-report detection.** When processing multiple bot rules, identical requests are downloaded once and file-copied for each subsequent rule. For 10 bot rules across 30 RSIDs, this eliminates hundreds of redundant API calls.

**Sliding-window rate limiter with global pause.** On a 429, all requests pause globally rather than retrying individually.

These are part of the engine, not opt-in features.

---

## Principle 6: One Tool, One Interface

Every workflow is launched the same way: `adobe-downloader run --config <path>`. The config file determines what happens. Utility operations (list users, search lookups, check status) are exposed as additional subcommands, but the core pattern is always: **write a config, run it.**

---

## Principle 7: Files Have a Lifecycle

Every file type has a defined lifecycle:

- **Downloaded JSON** → after transform, moved to `_processed/` (not deleted by default)
- **Individual CSVs** → optionally zipped after concatenation
- **Concatenated CSVs** → the primary deliverable, never automatically deleted
- **State databases and logs** → kept indefinitely for auditing

The guiding rule: **the tool never silently deletes data.** Disk is cheap; re-downloading is expensive. Cleanup is always explicit and opt-in (`adobe-downloader cleanup --older-than 90d`).

---

## Principle 8: Jobs Leave a Trail

Every completed job appends a record to a human-readable history log: what ran, when, how long, how many requests succeeded or failed, where the outputs went. The config file used is automatically archived with a timestamp.

This means you can always answer "what config did I use for last month's bot investigation?" without relying on memory or shell history. It also means onboarding a new team member is: "look at `.history/configs/` to see every job we've run — pick one as your starting point."

---

## Principle 9: Separate What Changes from What Doesn't

| Category | Location | In Git? | Changes How Often |
|---|---|---|---|
| Code | `src/adobe_downloader/` | Yes | On release |
| Report definitions | `report_definitions/` | Yes | Rarely |
| Templates | `jobs/templates/` | Yes | When workflows change |
| Reference data | `data/` | Yes | When RSID lists update |
| Job configs | `jobs/` | No | Every run |
| Credentials | `credentials/` | No | Rarely |
| Outputs + history | `<base_folder>/` | N/A | Every run |

The repo stays clean. Everything needed to reconstruct any workflow is version-controlled.

---

## Principle 10: The Tool Serves the Workflow

The architecture is designed around how people actually work: they repeat similar jobs monthly with small parameter changes (new dates, occasionally a new RSID or bot rule). The system makes this easy — copy last month's archived config, change the dates, run. A new team member should be productive within an hour of cloning the repo.

---

## How People Will Use This Tool

### A typical monthly bot investigation

1. **Start from history.** Open `.history/configs/`, find last month's bot investigation config. Copy it to `jobs/`.

2. **Edit three fields.** Change the `to:` date, maybe bump the version tag in `file_name_extra`. Everything else — the report definitions, RSID lists, segment IDs, transform type — is referenced by name, not re-entered.

3. **Run it.** `adobe-downloader run --config jobs/legend_cp_bot-investigation-v6.yaml`. Walk away. The tool logs progress to console and file, tracks every request in the state DB, and handles rate limits.

4. **Check progress** (optional). `adobe-downloader status --config jobs/legend_cp_bot-investigation-v6.yaml` from another terminal.

5. **It finishes.** The job history log records what happened. The config is archived. The concatenated CSVs are in the expected folder, ready for Power BI.

6. **If it fails mid-run.** Re-run the same command. The state DB knows which requests completed. It picks up where it left off.

### A new bot rule validation

1. **Create the bot rule CSV.** Same format as always — `dimSegmentId, botRuleName` columns.

2. **Copy the template.** `cp jobs/templates/bot_validation_list_of_rules.yaml jobs/legend_cp_bot-validation-newrule.yaml`.

3. **Fill in the blanks.** The template has `# <-- UPDATE THIS` markers. Change the CSV filename, the date range. The report definitions, shared-report optimisation, and transform type are already configured in the template.

4. **Run.** The composite job handles the chain: download → validate → retry missing → transform → concat.

### A one-off cube report

1. **Check the templates.** `jobs/templates/cube_report.yaml` has the full 3-step chain: create segments for one dimension → iterate segments with the other dimension → transform and concat.

2. **The tricky part — defining the report.** If the report already exists in `report_definitions/`, just reference it by name. If it's truly new, define it inline in the job config. Once it's proven useful, promote it to `report_definitions/` for future reuse.

3. **Run.** The composite runner creates the segments, feeds the segment list into the download step, transforms, and concatenates. You don't need to note filenames between steps — the output reference system handles it.

### Onboarding a new team member

1. Clone the repo. Run `pip install -e .`.
2. Copy `credentials/client_template.yaml` → `credentials/Legend.yaml`, fill in API keys.
3. Set the output folder in a job config.
4. Run `adobe-downloader run --config jobs/examples/legend_dl_bot-filter-exclude-monthly.yaml --test` to verify the setup with a small test download.
5. Browse `jobs/templates/` and `.history/configs/` to see what workflows exist and how they've been configured in the past.

---

## Summary

The core idea: **YAML in, data out, state tracked, steps chained, history kept.** A developer who has never seen the codebase should be able to look at a template, understand what it does from the comments and report references, fill in their parameters, and run it. The architecture eliminates the need to understand Python to operate the tool, while keeping the Python clean and extensible for those who do.

---

*This memo is for decision-making purposes. The full technical plan covers project structure, module design, config schemas, state persistence, rate limiting, CLI surface, file lifecycle, job history, template system, migration sequence, and worked examples.*
