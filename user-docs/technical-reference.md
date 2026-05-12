# adobe-downloader — Technical Reference

This document describes the internal architecture and data flow of `adobe-downloader` for developers and analysts who want to understand what the code is doing, not just how to invoke it.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  CLI (click commands)                                           │
│   download / validate / segment-create / rsid-update / ...     │
└────────────────────┬────────────────────────────────────────────┘
                     │ calls
┌────────────────────▼────────────────────────────────────────────┐
│  Flows                                                          │
│   composite_job.py  ──► report_download.py                      │
│                    ──► bot_rule_compare.py                      │
│                    ──► final_bot_metrics.py                     │
│                    ──► segment_creation.py                      │
│                    ──► rsid_update.py                           │
│                    ──► validation.py                            │
└────┬──────────────────────────────┬──────────────────────────────┘
     │ uses                         │ uses
┌────▼────────────┐        ┌────────▼─────────────────────────────┐
│  state_manager  │        │  core/                               │
│  (SQLite DB)    │        │   auth.py          (OAuth tokens)    │
│                 │        │   api_client.py    (httpx wrapper)   │
│  jobs table     │        │   rate_limiter.py  (sliding window)  │
│  requests table │        │   request_builder.py (body assembly) │
│  step_state     │        └────────────┬─────────────────────────┘
└─────────────────┘                     │ HTTPS
                              ┌─────────▼───────────┐
                              │  Adobe Analytics API │
                              │  analytics.adobe.io  │
                              └──────────────────────┘
     ┌──────────────────────────────────────────────────┐
     │  config/ (YAML → Pydantic)                       │
     │   loader.py             (credentials + job YAML) │
     │   report_definitions.py (report registry)        │
     │   schema.py             (Pydantic models)        │
     └──────────────────────────────────────────────────┘
     ┌──────────────────────────────────────────────────┐
     │  transforms/                                     │
     │   base.py         (JSON → CSV)                  │
     │   specialized.py  (5 report variants)            │
     │   concatenate.py  (CSV merging)                  │
     └──────────────────────────────────────────────────┘
```

Config feeds into every flow via YAML files loaded and validated by Pydantic at startup. The `StateManager` sits alongside every download loop, recording every request before it is fired and updating its status after completion.

---

## Auth Flow (`core/auth.py`)

`auth.py` is a thin module containing a single async function: `fetch_token`. It has no class and no caching — caching is the responsibility of `AdobeClient`.

**Token fetch**: An HTTP POST is made to `https://ims-na1.adobelogin.com/ims/token/v3` with a `client_credentials` grant type. The scope sent is `openid,AdobeID,additional_info.projectedProductContext`. On success, the JSON response provides `access_token` and `expires_in` (seconds).

**Expiry calculation**: The expiry timestamp is recorded as a monotonic clock value: `time.monotonic() + expires_in - 300`. The 300-second buffer (`_EXPIRY_BUFFER`) means the token is considered stale 5 minutes before its nominal expiry, so it is refreshed proactively rather than waiting for a 401.

**Credentials file format**: `load_credentials` in `config/loader.py` reads `credentials/client{name}.yaml` (falling back to `credentials/{name}.yaml`). The YAML must contain an `adobe` key:

```yaml
adobe:
  clientID: "your-client-id"
  clientSecret: "your-client-secret"
  adobeOrgID: "your-org-id@AdobeOrg"
  globalCompanyID: "your-company-id"
```

`AdobeClient.__init__` extracts all four fields from this dict. The client ID doubles as the `x-api-key` header on every API request.

---

## API Client (`core/api_client.py`)

`AdobeClient` is the single entry point for all Adobe Analytics API calls. It is instantiated once per job with a `client_name` string and owns its own `httpx.AsyncClient` (120-second timeout) and `SlidingWindowRateLimiter`.

**Token management**: `_get_token()` checks `time.monotonic() >= self._token_expiry` on every call. If the token is absent or stale, it awaits `fetch_token` and caches the result. No locking is applied — in practice, the single async task calling `_get_token` at a time means there is no race.

**Request headers**: Every request carries four headers assembled in `_headers()`:
- `Authorization: Bearer <token>`
- `x-api-key: <clientID>`
- `x-proxy-global-company-id: <globalCompanyID>`
- `x-gw-ims-org-id: <adobeOrgID>`

**`_get` / `_post` pattern**: Both methods follow the same structure: obtain a token, define an inner `_call` coroutine decorated with the tenacity retry, then `await _call()`. The actual HTTP verb is delegated to `self._rate_limiter.execute(self._http.get, ...)` or `self._http.post`. After the response returns, `r.raise_for_status()` is called inside `_call` so HTTP error codes propagate as `httpx.HTTPStatusError` and are caught by the tenacity retry predicate.

**Public API methods**:
- `get_report(request_body)` — POST to `/reports`; returns the JSON response dict.
- `get_report_suites(limit=1000)` — GET to `/collections/suites`.
- `create_segment(segment_def)` — POST to `/segments`.
- `share_segment(segment_id, user_ids)` — POST to `/componentmetadata/shares` once per user ID.
- `get_users()` — paginated GET to `/users`, iterates until `lastPage=True`.
- `get_authenticated_user()` — GET to `/users/me`.

---

## Rate Limiter (`core/rate_limiter.py`)

`SlidingWindowRateLimiter` enforces a **12 requests per 6-second sliding window** with a maximum of 12 concurrent in-flight requests.

**Data structures**:
- `_timestamps: deque[float]` — monotonic timestamps of every admitted request within the current window.
- `_semaphore: asyncio.Semaphore(12)` — caps concurrent in-flight requests.
- `_lock: asyncio.Lock()` — serialises mutations of `_timestamps`.
- `_pause_until: float` — monotonic timestamp until which all new requests must wait (set on 429 receipt).

**`acquire()` algorithm**:
1. Await the semaphore (blocks when 12 requests are already in flight).
2. Enter a spin loop:
   a. If `_pause_until` is in the future, sleep until it passes.
   b. Under `_lock`, evict timestamps older than `now - 6.0` seconds from the left of the deque.
   c. If `len(_timestamps) < 12`, append `now` and return (slot acquired).
   d. Otherwise, calculate `wait_for = _timestamps[0] - (now - 6.0)` (time until the oldest timestamp falls out of the window) and sleep.
3. The semaphore remains held until `release()` is called.

**`execute()`**: Calls `acquire()`, then runs the coroutine via `asyncio.wait_for(..., timeout=120)`, then calls `release()` in a `finally` block. This means the semaphore slot is held for the full duration of the HTTP call.

**429 pause behaviour**: `make_retry` returns a tenacity retry decorator. Its `before_sleep` hook checks whether the exception is a 429; if so, it calls `limiter.set_pause(10.0)`, setting `_pause_until = time.monotonic() + 10.0`. All subsequent `acquire()` calls will sleep until the pause expires before trying to grab a window slot. The retry itself then uses exponential backoff (`min=2s, max=30s`) for up to 5 attempts. Status codes 429, 500, 502, and 503 are all retryable.

---

## Request Builder (`core/request_builder.py`)

`build_request` takes a `ReportDefinitionInline`, a `DateRange`, an RSID string, and an optional list of extra segment IDs, and returns a dict suitable for POSTing to `/reports`.

**`globalFilters`** is a list built as follows:
1. A single date range filter: `{"type": "dateRange", "dateRange": "{from}T00:00:00.000/{to}T00:00:00.000"}`.
2. One `{"type": "segment", "segmentId": ...}` entry for each ID in `report_def.segments` (the base/permanent segments always applied to this report type, e.g. a master bot filter).
3. One entry per ID in the `segments` argument (runtime extra segments, e.g. a specific bot rule being tested).

**`metricContainer.metrics`** is always started with `visitors` (columnId 0, sort desc) and `visits` (columnId 1, sort desc), then any additional metrics from `report_def.metrics` appended at columnId 2, 3, … .

**`dimension`** is only added to the body when `report_def.dimension` is not `None` (summary reports that return only totals omit the dimension field entirely).

**`settings`**:
```python
{
    "countRepeatInstances": True,
    "includeAnnotations": True,
    "page": 0,
    "nonesBehavior": "return-nones",
    "limit": report_def.row_limit,
}
```

The `rsid` field is set directly on the top-level body object.

---

## State Management (`state_manager.py`)

Every job gets its own SQLite database at `{base_folder}/{client}/.state/{job_id}.db`. The `job_id` is a 16-character hex string derived from `SHA-256(config_path_resolved + "|" + config_hash)`, making it stable across restarts for the same config file (provided the file content has not changed).

### Schema

**`jobs` table**

| Column | Type | Notes |
|---|---|---|
| `job_id` | TEXT PK | Stable derived hash |
| `config_path` | TEXT | Absolute path of the YAML |
| `config_hash` | TEXT | SHA-256 of YAML content |
| `status` | TEXT | `pending` / `in_progress` / `completed` / `failed` |
| `created_at`, `started_at`, `completed_at` | TEXT | UTC ISO timestamps |
| `total_requests` | INTEGER | Populated on completion |
| `error_message` | TEXT | Set on failure |

**`requests` table**

| Column | Type | Notes |
|---|---|---|
| `request_id` | TEXT PK | UUID4 |
| `job_id` | TEXT FK | References `jobs` |
| `request_key` | TEXT | Human-readable composite key |
| `request_body_hash` | TEXT | SHA-256 of canonical JSON body |
| `status` | TEXT | `pending` / `in_progress` / `completed` / `failed` |
| `created_at`, `started_at`, `completed_at` | TEXT | UTC ISO |
| `retry_count` | INTEGER | Incremented on each failure |
| `error_message` | TEXT | Last error string |
| `output_path` | TEXT | Absolute path of the JSON output file |
| `canonical_request_id` | TEXT FK | Non-NULL when this is a copy of another request |

Unique constraint: `(job_id, request_key)`.

**`step_state` table** (composite jobs only)

| Column | Type | Notes |
|---|---|---|
| `step_id` | TEXT | Step ID from the YAML |
| `job_id` | TEXT FK | References `jobs` |
| `status` | TEXT | `pending` / `in_progress` / `completed` / `failed` |
| `outputs` | TEXT | JSON-serialised outputs dict |
| `started_at`, `completed_at` | TEXT | UTC ISO |

Primary key: `(job_id, step_id)`.

Two indexes: `idx_requests_job_status` on `(job_id, status)` and `idx_requests_body_hash` on `(job_id, request_body_hash)`.

### `canonical_request_id` concept

When `track_request` is called, it computes a SHA-256 hash of the request body (using `json.dumps(body, sort_keys=True)`). It then queries the `requests` table for any existing row in the same job (and, when `step_id` is given, scoped to the same step prefix) that has the same body hash and whose own `canonical_request_id` is `NULL`. If such a row is found, the new row's `canonical_request_id` is set to that row's `request_id`. This marks the new request as a "copy" rather than a "download".

When the download loop encounters a non-NULL `canonical_id`, it calls `get_canonical_output_path(canonical_id)`. If the canonical request is already completed and its output file exists on disk, the output path is copied (`shutil.copy2`) instead of making an API call. This is the mechanism by which AllTraffic files in the bot rule compare flow are downloaded only once per RSID per report, regardless of how many bot rules reference the same RSID.

### Request lifecycle

`pending` → (track_request, then mark_started) → `in_progress` → `completed` or `failed`.

### Resume behaviour

On restart, the flow calls `sm.is_complete(request_key, step_id=step_id)` before building the request body. If the row already has `status = 'completed'`, the request is skipped entirely. No file existence check is performed at this point — if the output file was deleted after the DB was written, `reset_completed_for_path(path)` can be called to revert the row to `pending`.

For composite jobs, `sm.is_step_complete(step_id)` gates the entire step. If True, `sm.get_step_outputs(step_id)` reloads the serialised outputs dict from the `step_state` table and re-injects them into `step_outputs` without re-running the step.

---

## Report Download Flow (`flows/report_download.py`)

`run_report_download` is the core iteration engine. It is called directly for standalone `report_download` jobs and as a delegate from the composite job runner.

### Iteration order

```
for rsid in rsid_list:
    for date_interval in date_intervals:
        for seg_id, seg_ids in all_segments:
            for rd in report_defs:
                ... download ...
```

All four dimensions are expanded upfront before the loop starts (with test limits applied if `test_limits` is set).

### Date interval expansion (`iterate_dates`)

- `interval="full"` — yields the original date range unchanged (one request per RSID per report).
- `interval="month"` — splits the range at calendar month boundaries. December 31 → January 1 is handled explicitly. Yields one `DateRange` per calendar month that overlaps the range.
- `interval="day"` — yields one `DateRange` per day.

Each yielded `DateRange` is a Pydantic model with `from_date` and `to` as ISO strings. The date arithmetic uses `datetime.date` objects.

### RSID sources (`iterate_rsids`)

- `source="single"` — yields the single RSID string from `rsids_cfg.single`.
- `source="list"` — yields from `rsids_cfg.rsid_list` (inline YAML list).
- `source="file"` — reads the file, splits on newlines, strips whitespace, skips blanks, yields each line.

### Segment sources (`iterate_segments`)

- `None` — yields `(None, [])` once (no segment filter, no filename suffix).
- `source="inline"` — yields `(None, ids)` once (all IDs in one request, no filename suffix).
- `source="segment_list_file"` — reads a JSON file that is a list of `{"id": ..., "name": ...}` objects. Yields one `(seg_id, [seg_id])` per entry, so each segment gets its own request and a distinct output filename.
- `source="step_output"` / `source="latest_segment_list"` — these are resolved to `segment_list_file` by the composite job runner before `run_report_download` is called; `iterate_segments` raises `NotImplementedError` if it encounters them directly.

### Output file naming

```
{base}/{client}/JSON/{client}_{report_name}{_extra}_{DIMSEG{seg_id}_}{from}_{to}.json
```

- `_extra` is the `file_name_extra` parameter (underscore-prefixed, absent if `None`).
- `DIMSEG{seg_id}_` is only included when a segment ID is being used as a filename discriminator (i.e. `seg_id` from `iterate_segments` is non-None).

### Canonical deduplication

Before building the request body, the loop calls `sm.is_complete(req_key, step_id)`. The `request_key` is `"{rsid}|{report_name}|{from}|{to}|{sorted_segment_ids}"`. If completed, it is skipped.

If not completed, `sm.track_request` is called, which checks whether the SHA-256 of the request body matches any earlier row in the same step. If it does, a `canonical_request_id` is returned. The download loop then copies the canonical output file rather than issuing an API call.

Downloaded JSON is written to the output path verbatim (pretty-printed with `indent=2`). `StateManager.mark_complete` records the output path in the DB.

---

## Transform Pipeline (`transforms/`)

### Base Transform (`base.py`)

`transform_report` converts one Adobe Analytics JSON file into CSV. The report name is derived from the filename by `_parse_filename_parts`, which splits on `_`, treats the first part as the client name, the last two as dates, and attempts longest-first matching of the middle parts against known header YAML files in `data/report_headers/`. If no YAML is found, the entire middle section is used.

**JSON response shapes supported**:

1. **Dimensional** — has a `rows` key. Each row object contains `itemId` (a numeric string), `value` (the dimension item label), and `data` (list of metric values). The CSV row order is: `itemId, value, data[0], data[1], ..., fileName, fromDate, toDate`.

2. **Summary/totals** — has a `summaryData.totals` key (no `rows`). The CSV row is: `totals[0], totals[1], ..., fileName, fromDate, toDate`.

**Column validation**: After building each row, the transform checks that `len(row) == len(columns)`. A mismatch raises `ValueError` with the row index, column counts, report name, and filename.

**Column headers** are loaded from `data/report_headers/{report_name}.yaml` files. Each YAML has a `columns` list. The order of this list defines both the CSV column order and the expected row length.

**Output**: If `output_path` is provided the CSV is written there (directory created if needed). The CSV text is always returned as a string. CSV output path derivation (`make_csv_output_path`) swaps the `JSON` directory component for `CSV` and changes the suffix to `.csv`.

### Specialised Transforms (`specialized.py`)

Five transform functions are registered in `_TRANSFORM_REGISTRY`. `transform_report_dispatch` selects the right one either from an explicit `transform_type` argument or by calling `_detect_transform_type`, which inspects the filename stem:

- `"-Compare-"` anywhere in `parts[4]` → `bot_rule_compare`
- `parts[1]` starts with `"LegendFinalBotMetrics"` → `final_bot_rule_metrics`
- `parts[1]` starts with `"botFilter"` → `bot_validation`
- `parts[1]` starts with `"botInvestigation"` → `bot_investigation`
- otherwise → `summary_total_only`

**`bot_investigation`**: Delegates entirely to the base `transform_report`. No extra columns.

**`bot_validation`**: Parses the filename as `{client}_{requestName}_{botRuleName}_{rsidName}_{from}_{to}`. Loads headers from the YAML for `requestName`. For each row appends: `fileName, requestName, botRuleName, rsidName`. These four columns must be present at the end of the header YAML definition.

**`transform_final_bot_rule_metrics`**: Filename pattern: `{client}_{reportName}_{fileExtra}_{rsidName}_{botRuleName}_{from}_{to}`. Extracts `rsid_name = parts[3]` and `bot_rule_name = parts[4]`. Loads headers from the YAML for `reportName`. Appends: `fileName, botRuleName, rsidName, fromDate, toDate`.

**`bot_rule_compare`**: Uses hardcoded headers (not a YAML file). The 23-column header string is defined as `_BOT_RULE_COMPARE_HEADERS`. Filename parsing is more complex, handling two patterns:
- AllTraffic: `{client}_{reportType}_{rsid}-{round}_{ruleName}-Compare-{ver}-AllTraffic_{from}_{to}`
- Segment: same but with `DIMSEG{n}_{hash?}_{from}_{to}` before the dates

The dimension is derived from `reportType` by stripping the `"botInvestigationMetricsBy"` prefix. `is_segment` and `is_compare` are booleans stored as lowercase strings in the CSV. Per-row appended columns: `fileName, clientName, reportType, dimension, rsidName, botRuleName, compareVersion, trafficType, isCompare, isSegment, segmentId, segmentHash, startDate, endDate`.

**`summary_total_only`**: Delegates entirely to the base `transform_report`. Used for topline metrics and other aggregate reports.

### Concatenation (`concatenate.py`)

`concatenate_csvs(folder, pattern, output_path, custom_headers)` merges multiple CSVs into one file.

- `pattern` uses `*` as a wildcard, converted to `.*` for `re.search`. Files are sorted alphabetically before processing.
- The header row is taken from the **first** matching file. All subsequent files have their header row dropped (`lines[1:]`).
- `custom_headers` is a `dict[int, str]` mapping 0-based column index to a replacement name. Applied to the header list before writing.
- Empty files and blank lines within files are skipped.
- The output is written as `"\n".join([header_line] + data_lines) + "\n"`.
- Returns the count of files concatenated (0 if none matched).

The composite job runner names the concatenation output `{step_id}_concat.csv` within the CSV folder.

---

## Segment Creation Flow (`segments/create_segment.py` and `flows/segment_creation.py`)

### Input CSV format

`run_segment_creation` reads a CSV with these required columns (parsed via `csv.DictReader`, UTF-8 BOM-safe):

| Column | Description |
|---|---|
| `CompareValidate` | `Compare`, `Validate`, `Compare - Special`, or `Validate - Special` |
| `SegmentName` | Display name for the segment; also used to derive the bot rule name |
| `RSIDCleanName` | Clean report suite name (used to look up the actual RSID) |
| `Dimension1` | Dimension label (e.g. `"Domain"`, `"UserAgent"`) |
| `Dimension1Item` | Value for that dimension |
| `Dimension2` | Optional second dimension |
| `Dimension2Item` | Required if `Dimension2` is set |

All rows are validated before any API calls are made. Validation errors accumulate and are raised together.

### Row processing

For each non-special row:
1. `RSIDCleanName` (with dots removed) is looked up in the RSID lookup file to get the actual RSID.
2. `resolve_dimension_value` is called for each dimension. For numeric dimensions (BrowserType, MonitorResolution, MarketingChannel, Region, and their aliases), it reads `data/lookups/{dim}/lookup.txt` (a `value|numericId` file) and returns the numeric ID. For string dimensions it returns the value unchanged.
3. Either `build_single_condition_segment` or `build_dual_condition_segment` (if `Dimension2` is present) is called to construct the Adobe segment definition dict. Single-condition segments use a `streq` or `eq` predicate in a `visits` container. Dual-condition uses an `and` predicate inside a `hits` container inside a `visits` container.
4. The segment is created via `client.create_segment(seg_def)`.
5. Each user ID in `share_with_users` receives a `client.share_segment` call.

For `Compare - Special` / `Validate - Special` rows no API call is made — the segment ID placeholder `"UPDATE-SEGMENT-ID"` is written to the output instead.

### Output files

Three output files are produced:

**`segment_list_file`** (`{list_name}.json`): A JSON array of `{"id": "...", "name": "..."}` objects for every successfully created segment (non-special rows only). This is the file consumed by downstream `report_download` steps that iterate by segment.

**`compare_list_file`** (`{list_name}_compare.csv`): A CSV with columns `DimSegmentId, botRuleName, reportToIgnore` for every `Compare` / `Compare - Special` row. `botRuleName` is derived by `transform_to_bot_rule_name`, which strips punctuation and spaces from the segment name and abbreviates long dimension names. `reportToIgnore` is the raw `Dimension1` value.

**`validate_list_file`** (`{list_name}_validate.csv`): Same columns, same structure, but for `Validate` / `Validate - Special` rows. The bot rule name transformation uses `transform_to_validate_bot_rule_name`, which additionally converts non-alphanumeric characters (other than `_`) to hyphens.

Both CSV formats are the input format expected by `parse_bot_rule_csv` in `bot_rule_compare.py`.

---

## Dim-to-Segments Flow (`segments/dim_to_segments.py`)

`dim_to_segments` creates one Adobe segment per top-N dimension value, without consulting any input CSV.

**Step 1 — fetch dimension values**: A `ReportDefinitionInline` is constructed with `dimension` set to the target Adobe variable ID (e.g. `variables/geocountry`), `row_limit=num_pairs`, and no metrics. `build_request` produces the request body, and `client.get_report` fetches the ranked report. The response `rows` are filtered to entries that have both `value` and `itemId`.

**Step 2 — create segments**: For each `(value, itemId)` pair, `_build_dim_segment_def` builds a hits-context numeric-equality segment definition using `{"func": "eq", "num": int(item_id)}`. The segment name is `"{dimension} = {value}"`. `client.create_segment` is called; on success the returned `id` and a sanitised `name` (whitespace collapsed, `:` replaced with `-`) are appended to the result list.

**Step 3 — save segment list**: The list of `{"id": ..., "name": ...}` dicts is written as a JSON array to `output_path`. This file has the same format as the `segment_list_file` produced by the segment creation flow and can be referenced by a subsequent `report_download` step via `segments.source = "step_output"`.

The composite job runner places the output at `{output_base}/{client}/segments/{step_id}_segments.json`.

---

## Lookup Generation (`segments/lookup_generator.py`)

`generate_lookup_file` downloads the full list of values for a dimension and writes them to a local lookup file consumed by `resolve_dimension_value`.

**Fetch**: A `ReportDefinitionInline` is constructed with the target dimension, `row_limit=50000`, and no metrics. `build_request` builds the body; `client.get_report` retrieves up to 50,000 value-itemId pairs. The response `rows` are filtered to entries with both `value` and `itemId`.

**Lookup file format** (written to `{lookup_base}/{cleaned_dim_name}/lookup.txt`):

```
/**
 * Lookup Table for {dimension}
 *
 * Maps string values to their numeric IDs for use in Adobe Analytics segments.
 *
 * Client: {client}
 * RSID: {rsid}
 * Date Range: {from} to {to}
 * Last Updated: {YYYY-MM-DD}
 *
 * Format: stringValue|numericId
 */

BotTraffic|1234
Direct|5678
...
```

Lines are sorted alphabetically by the string value. Comment lines starting with `//`, `/*`, or `*` are skipped by `load_lookup_file`.

`merge_into_lookup_file` reads an existing lookup file, merges new pairs (new values overwrite old ones with the same key), and rewrites the file. This is used by the `search-lookup` CLI command to add individual values without re-downloading the full dimension.

The cleaned dimension name used in the directory path is the dimension string with all non-alphanumeric characters removed (e.g. `variables/browsertype` → `variablesbrowsertype`).

---

## RSID Update Flow (`flows/rsid_update.py`)

`run_rsid_update` refreshes the two RSID list files that gate which report suites are included in investigation and validation jobs.

**Steps**:

1. `client.get_report_suites()` is called with `limit=1000`. The `content` list from the response contains dicts with `rsid` and `name` keys.
2. If `include_virtual=False` (the default), report suites whose RSID starts with `vrs_` are dropped.
3. `clean_suite_name` transforms each display name: remove all spaces, remove all dots, remove a trailing `-Production` suffix (case-insensitive). This mirrors the JS convention.
4. An optional exclusion list is loaded from a plain-text file (one clean name per line). Matched suites are excluded from the threshold comparison but still appear in the suite pairs file.
5. If `suite_pairs_dir` is set, a file `legendReportSuites{YYYYMMDD}.txt` is written with the format `{rsid}:{cleanName}` — one per line. This file is the RSID lookup file consumed by `bot_rule_compare` and `final_bot_metrics`.
6. For each RSID, `toplineMetricsForRsidValidation` is fetched from the report registry (a summary report returning totals). `summaryData.totals[1]` is taken as the visit count (index 0 is unique visitors, index 1 is visits).
7. Suites are filtered by two independent thresholds: `investigation_threshold` and `validation_threshold`. Suites meeting the threshold have their `cleanName` written to the respective output file.

**Output files** (written to `{output_base}/`):
- `botInvestigationMinThresholdVisits.txt` — plain text, one clean name per line, with three header comment lines showing the threshold, date range, and generation date.
- `botValidationRsidList.txt` — same format, different threshold.

Before overwriting, existing files are archived to `{output_base}/archive/{stem}_{YYYYMMDD}{suffix}`.

---

## Composite Job Runner (`flows/composite_job.py`)

`run_composite_job` executes a list of steps defined in a `CompositeJobConfig` sequentially. It returns a `dict[step_id, outputs]` mapping.

### Step sequencing algorithm

```
for step in job.steps:
    1. Check depends_on (if set):
       - Look up dep_id in step_outputs (in-memory from this run).
       - If not found, try sm.get_step_outputs(dep_id) (from DB — prior run).
       - If still not found, raise RuntimeError.
    2. Check resume: if sm.is_step_complete(step_id) and not no_resume:
       - Reload outputs from sm.get_step_outputs(step_id).
       - Inject into step_outputs dict.
       - Continue to next step.
    3. sm.mark_step_started(step_id)
    4. await _dispatch_step(...) → outputs dict
    5. sm.mark_step_complete(step_id, outputs)
    6. Store in step_outputs[step_id]
```

If any step raises, `sm.mark_step_failed(step_id, error)` and `sm.mark_job_failed("step failure")` are called, then the exception re-raises.

### Dependency resolution (`depends_on`)

`depends_on` is a single step ID string. It gates execution: if the dependency has not produced outputs (either in the current run or stored in the DB from a prior run), the composite job aborts with a `RuntimeError`. There is no DAG — steps are always executed in their declared order, with `depends_on` acting as a guard rather than a scheduler.

### Output references (`step_output` references)

Several step fields accept a `source: step_output` construct in the YAML:

```yaml
segments:
  source: step_output
  step_id: create_segments
  output_key: segment_list_file
```

`_resolve_segments` detects `source == "step_output"`, looks up `step_outputs[step_id][output_key]`, and converts it to `SegmentSource(source="segment_list_file", file=resolved_path)`. Bot rules in `bot_rule_compare` steps can similarly reference a prior step's output CSV via `bot_rules.source: step_output`.

### Report definition resolution (`_resolve_report_defs`)

Steps can specify reports in three ways (checked in order):
- `report_group: "group_name"` → calls `load_report_group(name)`, returns all reports in that YAML group.
- `report_ref: "report_name"` → calls `load_report_registry()`, returns the single named report.
- `report: {...}` → validates the inline dict as a `ReportDefinitionInline` directly.

### Test mode propagation

The composite job YAML can set `test_mode: true` and a `test_limits` block. When `test_mode` is true, `job.test_limits` is passed to every `run_report_download`, `run_bot_rule_compare`, and `run_final_bot_metrics` call. `apply_all_limits` (in `utils/test_mode.py`) slices each iterable to the configured limits before the download loop begins.

---

## Bot Rule Compare (`flows/bot_rule_compare.py`)

`run_bot_rule_compare` downloads the bot investigation reports in two variants — with and without a segment filter — for each RSID-rule combination.

### Input: bot rule CSV

`parse_bot_rule_csv` reads a CSV with columns `DimSegmentId`, `botRuleName`, `reportToIgnore`. `reportToIgnore` may be a short name (`"Domain"`) or a full report name (`"botInvestigationMetricsByDomain"`). The `DIMENSION_MAPPING` dict maps short names to full names; if neither matches, the name is prefixed with `"botInvestigationMetricsBy"`.

### AllTraffic baseline requests

For each RSID-rule pair, every report in the `bot_rule_compare` report group is visited **except** the one named in `rule.report_to_skip`. For the AllTraffic variant, `segments=[]` is passed to `build_request`, so no segment filter is applied.

The filename includes the investigation name (which encodes the bot rule name and comparison version) so that each bot rule gets a distinct AllTraffic output file even though the API request bodies for the same RSID+report+date combination are identical across rules.

### Segment variant requests

For the Segment variant, `segments=[bot_rule.segment_id]` is passed. The output filename encodes `"-Segment"` and uses `segment_id_for_path=bot_rule.segment_id` so that the `DIMSEG{id}` token appears in the filename.

### Canonical deduplication across AllTraffic files

The request key for each variant includes the output filename (`f"{base_key}|{out_path.name}"`). This means two AllTraffic requests for the same RSID+report+date (but different bot rule names in the filename) have different request keys but identical request body hashes. `track_request` detects the matching body hash and sets `canonical_request_id` on the second row. The download loop then copies the first file's output to the second file's path via `shutil.copy2`, avoiding a redundant API call.

---

## Final Bot Metrics (`flows/final_bot_metrics.py`)

`run_final_bot_metrics` handles two structurally different report types within the same flow, distinguished by whether the report name is in `_PER_SEGMENT_REPORTS`.

### Per-segment reports (`LegendFinalBotMetricsUnfilteredVisitsByYear`)

For each RSID × each segment in the validated segment list × each date interval:
- `file_name_extra` is `"{job_name}_{clean_name}_{seg.suffix}"`. The suffix is the part of the segment name after `=`, stripped and with spaces replaced by hyphens.
- The segment ID is passed as `segments=[seg.id]` to `build_request`.
- `segment_id=None` is deliberately passed to `make_output_path` — the segment information is encoded in `file_name_extra` rather than as a `DIMSEG` token, so the transform can extract `rsidName` from `parts[3]` and `botRuleName` from `parts[4]`.

### Aggregate reports (all other reports in the group, e.g. `Current`/`Development Include`)

For each RSID × each date interval (no segment iteration):
- `file_name_extra` is just `"{job_name}"`.
- `segments=[]` is passed; the report definition's own baked-in segments (e.g. a segment that filters to bot traffic only) are included via `report_def.segments` in `build_request`.

Segment name loading uses `load_segment_list_with_names`, which reads the same `{"id", "name"}` JSON format as other segment list files, but additionally parses the suffix from the name string.

---

## Validation Flow (`flows/validation.py`)

Validation re-derives the set of expected output paths without consulting the state DB and then checks the filesystem.

### Expected path enumeration (`enumerate_expected_paths`)

Iterates the same four-dimensional space as `run_report_download` (RSIDs × date intervals × segments × report defs) and calls `make_output_path` with the same arguments. The result is a list of paths that should exist if the download completed without skipping anything.

### File check (`check_output_files`)

For each expected path, checks `p.exists() and p.stat().st_size > 0`. Returns `(valid, missing_or_empty)` partitions. A zero-byte file is treated the same as a missing file.

### Retry hook (in composite jobs)

When a `validate_output` step has `retry: true` and missing files are detected:
1. For each missing path, `sm.reset_completed_for_path(path)` is called. This reverts any DB row that has `status = 'completed'` and `output_path = path` back to `pending`. This handles the case where the file was deleted after the DB was written.
2. `sm.reset_incomplete_for_step(config_ref)` resets any `failed` or `in_progress` rows for the referenced step prefix back to `pending`.
3. `run_report_download` is called again with `no_resume=False`, so it will pick up the reset rows.
4. The file check is repeated. If files are still missing after the retry, the step raises `RuntimeError`.

In the standalone `run_validate_output` path (used by the `validate-output` CLI command), the equivalent behaviour uses `sm.reset_all()` to reset all non-completed requests to pending, then re-runs the download.

---

## Post-Processing (`utils/post_process.py`)

Post-processing utilities handle file lifecycle management after a download job completes. None of these operations happen automatically — they are called explicitly from CLI commands or job configs.

### JSON archiving

`move_json_to_processed(json_path)` moves the file into `{json_path.parent}/_processed/`. The filename is unchanged. This is used to keep the `JSON/` working directory clean after transform without deleting the source files.

### CSV zipping

`zip_csv_folder(csv_folder, zip_dest)` globs all `*.csv` files in the folder and writes them to `zip_dest` using `ZIP_DEFLATED` compression. Each file is stored with just its filename (no directory prefix). Returns the count of files zipped.

### Job history

`log_job_history` appends a single JSON line to `{base_folder}/{client}/.history/job_history.jsonl`. Each record includes `job_id`, `config_path`, `started_at`, `completed_at`, `duration_minutes`, `status`, and request counts. `build_history_record` constructs this dict from a `StateManager.get_summary()` output.

`read_job_history` reads the JSONL file and supports filtering by `status` (exact match) and `since` (ISO date prefix comparison against `started_at`), plus a `last: int` tail limit.

### Config archiving

`archive_config(base_folder, client, config_path, date_prefix)` copies the YAML config to `{base_folder}/{client}/.history/configs/{date_prefix}_{config_filename}`. The `date_prefix` is typically `YYYYMMDD` from the run date. This creates an immutable record of what config was used for each run.

### Cleanup

`cleanup_old_files(base_folder, client, older_than_days, file_type)` deletes files older than the threshold. `file_type` must be one of:
- `"processed-json"` — targets `JSON/_processed/*.json`
- `"logs"` — targets `.logs/*.log`
- `"state"` — targets `.state/*.db`

---

## Report Definitions Registry (`config/report_definitions.py`)

Report definitions live in `report_definitions/*.yaml` files at the repo root. Each file defines one named group of related reports.

### YAML file structure

```yaml
group: "bot_investigation"       # group name for load_report_group()
description: "..."
transform_type: "bot_investigation"  # informational only
defaults:
  segments: ["seg_id_1"]         # applied to all reports in this file
  metrics: ["metrics/visits"]
  row_limit: 500
  csv_headers: []
reports:
  botInvestigationMetricsByDomain:
    dimension: "variables/filtereddomain"
    row_limit: 1000              # overrides default
  botInvestigationMetricsByUserAgent:
    dimension: "variables/evar23"
    # inherits all defaults
```

### Pydantic models

`ReportDefinitionFile` is the top-level model for the file. It holds a `defaults: ReportDefinitionDefaults` and a `reports: dict[str, ReportEntry]` map. `ReportEntry` holds per-report overrides (any field set to `None` means "use the default").

### `resolve(report_name)`

`ReportDefinitionFile.resolve` merges a named `ReportEntry` with its group defaults and returns a `ReportDefinitionInline`. For each of `row_limit`, `segments`, `metrics`, and `csv_headers`, the entry value is used if not `None`, otherwise the default is used.

### `load_report_registry()`

Scans all `*.yaml` files in `report_definitions/` (sorted alphabetically). For each file, loads and validates the `ReportDefinitionFile`, then calls `resolve` for every report name in `rdf.reports`. Returns a flat `dict[str, ReportDefinitionInline]`. If two files define reports with the same name, the last file loaded wins (alphabetical sort order).

There is no singleton — `load_report_registry()` re-reads the YAML files on every call. Callers that need the registry multiple times should cache the result themselves.

### `load_report_group(group_name)`

Scans the same YAML files and returns the list of resolved `ReportDefinitionInline` objects for the first file whose `group` field matches `group_name`, in YAML declaration order. Raises `KeyError` if no match is found.

`report_ref` resolution in the composite job runner calls `load_report_registry()` and looks up a single key. `report_group` resolution calls `load_report_group(name)` and returns the full list.
