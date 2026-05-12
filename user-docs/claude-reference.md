# adobe-downloader — Claude Reference

Dense reference for answering operational questions. All field names, types, and behaviours are derived from `adobe_downloader/config/schema.py`, `adobe_downloader/cli.py`, the `report_definitions/` YAML files, `jobs/templates/`, and the transforms source.

---

## CLI Commands

| Command | Key Flags | Purpose |
|---|---|---|
| `adobe-downloader validate` | `-c/--config PATH` `--check-credentials/--no-check-credentials` | Parse YAML, run Pydantic validation, verify referenced files exist; warns if credentials missing |
| `adobe-downloader run` | `-c/--config PATH` `-r/--report NAME` `--no-resume` `--test` | Execute a job: report_download, segment_creation, lookup_generation, rsid_update, or composite |
| `adobe-downloader status` | `-c/--config PATH` | Print SQLite state for a report_download job (counts by status, last errors) |
| `adobe-downloader retry` | `-c/--config PATH` `--failed-only` | Re-queue failed (or all pending+failed) requests for re-download |
| `adobe-downloader reset` | `-c/--config PATH` `--confirm` | Wipe all job state (requires `--confirm`); allows clean restart |
| `adobe-downloader transform` | `-j/--json-dir PATH` `-p/--pattern GLOB` `--concat/--no-concat` `--concat-output PATH` | Transform existing JSON files to CSV; optionally concatenate |
| `adobe-downloader validate-output` | `-c/--config PATH` `--retry/--no-retry` `--dry-run/--no-dry-run` | Check all expected output files exist and are non-empty; `--retry` re-downloads missing files |
| `adobe-downloader history` | `-c/--client NAME` `-o/--output-base PATH` `--last N` `--status STR` `--since DATE` | Show recent job history from the job log |
| `adobe-downloader cleanup` | `-c/--client NAME` `-o/--output-base PATH` `--older-than Nd` `--type TYPE` `--confirm` | Remove old files by type (`processed-json`, `logs`, `state`); requires `--confirm` |
| `adobe-downloader get-segment` | `-c/--client NAME` `-s/--segment-id ID` `-o/--output PATH` | Fetch a segment definition from Adobe API and save as JSON |
| `adobe-downloader search-lookup` | `-d/--dimension NAME` `-v/--value STR` | Search a local lookup file for a dimension value's numeric ID |
| `adobe-downloader list-users` | `-c/--client NAME` | List Adobe Analytics users for a client |
| `adobe-downloader list-rsids` | `-c/--client NAME` `--include-virtual/--no-include-virtual` | Fetch and display all report suites for a client |
| `adobe-downloader update-rsids` | `-c/--client NAME` `--from DATE` `--to DATE` `--investigation-threshold N` `--validation-threshold N` `--include-virtual` `-o/--output-base PATH` `--suite-pairs-dir PATH` `--exclusion-file PATH` | Standalone RSID update: fetch suites, download topline metrics, write filtered lists |

---

## Job Types

### `report_download`

Downloads Adobe Analytics ranked or summary reports for one or more RSIDs, date intervals, and segments.

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_type` | `"report_download"` | yes | Discriminator |
| `client` | str | yes | Matches `credentials/<client>.json` |
| `description` | str | no | Free-text label |
| `report_ref` | str | one of three | Single named report key (from report_definitions registry) |
| `report_group` | str | one of three | All reports in a group YAML file |
| `report` | inline object | one of three | Inline report definition; see `ReportDefinitionInline` |
| `rsids` | `RsidSource` | yes | |
| `segments` | `SegmentSource` | no | |
| `interval` | `"full"` \| `"month"` \| `"day"` | no | Default `"full"` |
| `date_range` | `DateRange` | yes | |
| `transform` | `TransformConfig` | no | Runs after download if present |
| `test_mode` | bool | no | Default `false`; also overridable via `--test` flag |
| `test_limits` | `TestLimits` | no | Default: `max_rsids=3, max_date_intervals=2, max_segments=5` |
| `resume` | bool | no | Default `true` |
| `post_processing` | `PostProcessing` | no | Default: `delete_json_after_transform=false, zip_csvs_after_concat=true` |
| `output.base_folder` | str | yes | Root output directory |
| `file_name_extra` | str | no | Injected into output filenames for disambiguation |
| `bot_rules` | `BotRulesSource` | no | Used by bot_validation/bot_rule_compare flows |
| `optimisation` | `OptimisationConfig` | no | `shared_reports=true` shares report results across bot rules |

### `transform_concat`

Standalone transform + optional concatenation of existing JSON files. No API calls.

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_type` | `"transform_concat"` | yes | |
| `client` | str | yes | |
| `transform` | `TransformConfig` | yes | `type`, `source_pattern`, `source_folder`, `output_subfolder`, `concat` |
| `concat` | `ConcatConfig` | no | `enabled`, `file_pattern`, `custom_headers` (dict of col-index → header name) |
| `output.base_folder` | str | yes | |
| `test_mode` | bool | no | |

### `segment_creation`

Reads a bot rule CSV, creates Adobe segments via API, writes compare/validate/segment list files.

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_type` | `"segment_creation"` | yes | |
| `client` | str | yes | |
| `segment_creation.input_csv` | str | yes | Path to bot rule CSV |
| `segment_creation.share_with_users` | list[str] | no | Adobe user IDs to share created segments with |
| `segment_creation.test_mode_row` | int | no | 1-based; test a single row only |
| `segment_creation.compare_list_path` | str | no | Output path for compare list file |
| `segment_creation.validate_list_path` | str | no | Output path for validate list file |
| `segment_creation.segment_list_path` | str | no | Output path for segment list JSON |
| `output.base_folder` | str | yes | |
| `date_range` | `DateRange` | no | |

### `lookup_generation`

Downloads a dimension report with high row limit for building local lookup tables (dimension value → numeric item ID).

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_type` | `"lookup_generation"` | yes | |
| `client` | str | yes | |
| `lookup_generation.dimension` | str | yes | Adobe variable ID, e.g. `variables/browser` |
| `lookup_generation.rsid` | str | yes | Single RSID to query |
| `lookup_generation.segments` | list[str] | no | Optional segment IDs |
| `lookup_generation.output_file` | str | no | Explicit output path; auto-named in `data/lookups/` if null |
| `date_range` | `DateRange` | yes | |
| `output.base_folder` | str | yes | |

### `rsid_update`

Fetches all report suites for a client, downloads topline metrics, writes filtered investigation and validation RSID lists.

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_type` | `"rsid_update"` | yes | |
| `client` | str | yes | |
| `rsid_update.investigation_threshold` | int | no | Default 1000; minimum visits for investigation list |
| `rsid_update.validation_threshold` | int | no | Default 1000; minimum visits for validation list |
| `rsid_update.include_virtual` | bool | no | Default `false`; include `vrs_`-prefixed suites |
| `date_range` | `DateRange` | yes | |
| `output.base_folder` | str | yes | Writes RSID list files here |

### `composite`

Orchestrates multiple steps sequentially with inter-step output references. Steps execute in order; each can depend on a prior step.

| Field | Type | Required | Notes |
|---|---|---|---|
| `job_type` | `"composite"` | yes | |
| `client` | str | yes | |
| `steps` | list[`CompositeStep`] | yes | Each step has `step`, `id`, optional `depends_on` |
| `date_range` | `DateRange` | no | Inherited by steps unless overridden per-step |
| `test_mode` | bool | no | Propagated to all steps |
| `test_limits` | `TestLimits` | no | |
| `output.base_folder` | str | yes (for state DB) | |

---

## Flow Recipes

### `report_download` — bot investigation

```yaml
job_type: report_download
client: Legend
description: "Bot investigation download"

report_group: bot_investigation   # loads all 13 reports from report_definitions/bot_investigation.yaml

rsids:
  source: file
  file: data/rsid_lists/botInvestigationMinThresholdVisits.txt  # one rsid per line
  batch_size: 12                  # concurrent API requests per batch

interval: month                   # splits date_range into one request per calendar month

date_range:
  from: "2025-01-01"
  to: today                       # "today" resolves at runtime

transform:
  enabled: true
  type: bot_investigation         # maps to transform_bot_investigation
  concat: true                    # concatenate all CSVs after transform

post_processing:
  delete_json_after_transform: false
  zip_csvs_after_concat: true

resume: true                      # skip already-completed requests (uses SQLite state)

output:
  base_folder: "/path/to/output"
```

### `transform_concat` — standalone re-transform

```yaml
job_type: transform_concat
client: Legend

transform:
  enabled: true
  type: bot_investigation
  source_pattern: ".*Coverscom-FullRun.*\\.json$"  # regex filter on filenames
  source_folder: null             # null = default JSON folder for this client
  output_subfolder: "Coverscom-FullRun"
  concat: true

concat:
  enabled: true
  file_pattern: ".*\\.csv$"
  custom_headers:                 # optional: override specific column names by 1-based index
    # 1: NewHeaderName

output:
  base_folder: "/path/to/output"
```

### `segment_creation`

```yaml
job_type: segment_creation
client: Legend

segment_creation:
  input_csv: data/segment_creation_lists/my_rules.csv
  share_with_users:
    - "200419062"                 # Adobe user ID (not email)
  test_mode_row: null             # set to e.g. 1 to test first row only
  compare_list_path: data/bot_compare_lists/
  validate_list_path: data/bot_rule_lists/
  segment_list_path: data/segment_lists/Legend/

output:
  base_folder: "/path/to/output"
```

### `lookup_generation`

```yaml
job_type: lookup_generation
client: Legend

lookup_generation:
  dimension: variables/browsertype   # Adobe variable ID
  rsid: trillioncoverscom
  segments:
    - s3938_61bb0165a88ab931afa78e4c  # optional: filter to specific traffic
  output_file: null                   # null = auto-named under data/lookups/variablesbrowsertype/lookup.txt

date_range:
  from: "2025-01-01"
  to: "2025-03-31"

output:
  base_folder: "/path/to/output"
```

### `rsid_update`

```yaml
job_type: rsid_update
client: Legend

rsid_update:
  investigation_threshold: 1000   # min visits to include in botInvestigationMinThresholdVisits.txt
  validation_threshold: 1000      # min visits to include in botValidationRsidList.txt
  include_virtual: false

date_range:
  from: "2025-01-01"
  to: "2025-03-31"

output:
  base_folder: data/rsid_lists/
```

### `composite` — full bot investigation flow

```yaml
job_type: composite
client: Legend
description: "Segment creation → download → validate → transform"

date_range:
  from: "2025-01-01"
  to: "2025-03-31"

output:
  base_folder: "/path/to/output"

steps:
  - step: segment_creation
    id: create_segments
    segment_creation:
      input_csv: data/segment_creation_lists/my_rules.csv
      share_with_users:
        - "200419062"

  - step: report_download
    id: download_investigation
    report_group: bot_investigation
    rsids:
      source: file
      file: data/rsid_lists/botInvestigationMinThresholdVisits.txt
      batch_size: 12
    segments:
      source: step_output          # resolve segment_list_file from create_segments outputs
      step_id: create_segments
      output_key: segment_list_file
    interval: month

  - step: validate_output
    id: validate
    depends_on: download_investigation   # only runs after download_investigation completes
    config_ref: download_investigation   # enumerate expected files from this step's config
    retry: true                          # re-download any missing files

  - step: transform_concat
    id: transform
    depends_on: validate
    transform:
      type: bot_investigation
      concat: true
```

### `composite` — bot validation flow

```yaml
job_type: composite
client: Legend

date_range:
  from: "2025-01-01"
  to: "2025-03-31"

output:
  base_folder: "/path/to/output"

steps:
  - step: segment_creation
    id: create_segments
    segment_creation:
      input_csv: data/segment_creation_lists/my_rules.csv
      share_with_users:
        - "200419062"

  - step: report_download
    id: download_validation
    report_group: bot_validation
    rsids:
      source: file
      file: data/rsid_lists/botValidationRsidList.txt
      batch_size: 12
    bot_rules:
      source: step_output          # validate list CSV from segment_creation step
      step_id: create_segments
      output_key: validate_list_file
    segments:
      source: step_output
      step_id: create_segments
      output_key: segment_list_file
    interval: month
    optimisation:
      shared_reports: true         # botFilterExclude/Include run once, shared across bot rules
      shared_report_names:
        - botFilterExcludeMetricsByMonth
        - botFilterIncludeMetricsByMonth

  - step: validate_output
    id: validate
    depends_on: download_validation
    config_ref: download_validation
    retry: true

  - step: transform_concat
    id: transform
    depends_on: validate
    transform:
      type: bot_validation
      concat: true
```

### `composite` — bot rule compare flow

```yaml
job_type: composite
client: Legend

date_range:
  from: "2025-01-01"
  to: "2025-03-31"

output:
  base_folder: "/path/to/output"

steps:
  - step: report_download          # downloads AllTraffic + Segment variants per rule
    id: download_compare
    report_group: bot_rule_compare
    rsids:
      source: file
      file: data/rsid_lists/botInvestigationMinThresholdVisits.txt
      batch_size: 12
    bot_rules:
      source: file
      file: data/bot_compare_lists/my_compare_list.csv
    interval: full
    file_name_extra: "V4-Compare"  # injected into filenames; used as pattern below

  - step: validate_output
    id: validate
    depends_on: download_compare
    config_ref: download_compare

  - step: transform_concat
    id: transform
    depends_on: validate
    transform:
      type: bot_rule_compare
      source_pattern: ".*V4-Compare.*\\.json$"  # filter to this run's files only
      concat: true
```

### `composite` — final bot metrics flow

```yaml
job_type: composite
client: Legend

date_range:
  from: "2025-01-01"
  to: "2025-12-31"

output:
  base_folder: "/path/to/output"

steps:
  - step: report_download
    id: download_final
    report_group: final_bot_metrics
    rsids:
      source: file
      file: data/rsid_lists/rsidList.txt
      batch_size: 12
    segments:
      source: segment_list_file    # pre-existing validated segment list
      file: data/segment_lists/Legend/validated_segments.json
    interval: full

  - step: transform_concat
    id: transform
    depends_on: download_final
    transform:
      type: final_bot_metrics      # appends botRuleName, rsidCleanName to each row
      concat: true
```

---

## Transform Types

| Type | Output columns added | When to use |
|---|---|---|
| `standard` | `fileName`, `fromDate`, `toDate` (dimensional) or just these for summary | Generic reports with no special filename-derived metadata |
| `bot_investigation` | Same as `standard`; delegates to `transform_report` | `bot_investigation` and `bot_investigation_unfiltered` group reports |
| `bot_validation` | `fileName`, `requestName`, `botRuleName`, `rsidName` | `bot_validation` group reports; extracts `requestName`, `botRuleName`, `rsidName` from filename parts |
| `bot_rule_compare` | `fileName`, `clientName`, `reportType`, `dimension`, `rsidName`, `botRuleName`, `compareVersion`, `trafficType`, `isCompare`, `isSegment`, `segmentId`, `segmentHash`, `startDate`, `endDate` | `bot_rule_compare` group; hardcoded headers; fully parses complex filename encoding |
| `final_bot_metrics` | `fileName`, `botRuleName`, `rsidCleanName`, `fromDate`, `toDate` | `final_bot_metrics` group; extracts `botRuleName` from `parts[4]`, `rsidName` from `parts[3]` |
| `summary_total` | `fileName`, `fromDate`, `toDate` (from `summaryData.totals`) | No-dimension/totals-only reports; reads `summaryData.totals` instead of `rows` |

**Auto-detection** (used when `transform_type` is not specified): `_detect_transform_type` infers from filename stem:
- `parts[4]` contains `-Compare-` → `bot_rule_compare`
- `parts[1]` starts with `LegendFinalBotMetrics` → `final_bot_rule_metrics`
- `parts[1]` starts with `botFilter` → `bot_validation`
- `parts[1]` starts with `botInvestigation` → `bot_investigation`
- otherwise → `summary_total_only`

---

## Report Definitions

All reports are in `report_definitions/`. Each file defines a `group`, `description`, `transform_type`, shared `defaults` (metrics, segments, row_limit), and per-report overrides.

### Group: `bot_investigation` (transform: `bot_investigation`)

Default segments: Master Bot Filter (Exclude). Default row_limit: 500.
Default metrics: event3, Clickouts CM, Engaged Visits CM, itemtimespent, pageviews.

| Report name | Dimension | Row limit |
|---|---|---|
| `botInvestigationMetricsByDay` | `variables/daterangeday` | 500 |
| `botInvestigationMetricsByMarketingChannel` | `variables/marketingchannel` | 50 |
| `botInvestigationMetricsByDevice` | `variables/mobiledevicetype` | 500 |
| `botInvestigationMetricsByDomain` | `variables/filtereddomain` | 500 |
| `botInvestigationMetricsByMonitorResolution` | `variables/monitorresolution` | 500 |
| `botInvestigationMetricsByHourOfDay` | `variables/timeparthourofday` | 25 |
| `botInvestigationMetricsByOperatingSystem` | `variables/operatingsystem` | 500 |
| `botInvestigationMetricsByPageURL` | `variables/evar2` | 500 |
| `botInvestigationMetricsByRegion` | `variables/georegion` | 500 |
| `botInvestigationMetricsByUserAgent` | `variables/evar23` | 500 |
| `botInvestigationMetricsByBrowser` | `variables/browser` | 500 |
| `botInvestigationMetricsByBrowserType` | `variables/browsertype` | 100 |
| `botInvestigationMetricsByMobileManufacturer` | `variables/mobilemanufacturer` | 500 |

### Group: `bot_investigation_unfiltered` (transform: `bot_investigation`)

Same 13 report shapes as above, no default segments (all traffic).

| Report name | Dimension | Row limit |
|---|---|---|
| `botInvestigationUnfilteredMetricsByDay` | `variables/daterangeday` | 500 |
| `botInvestigationUnfilteredMetricsByMarketingChannel` | `variables/marketingchannel` | 50 |
| `botInvestigationUnfilteredMetricsByDevice` | `variables/mobiledevicetype` | 500 |
| `botInvestigationUnfilteredMetricsByDomain` | `variables/filtereddomain` | 500 |
| `botInvestigationUnfilteredMetricsByMonitorResolution` | `variables/monitorresolution` | 500 |
| `botInvestigationUnfilteredMetricsByHourOfDay` | `variables/timeparthourofday` | 25 |
| `botInvestigationUnfilteredMetricsByOperatingSystem` | `variables/operatingsystem` | 500 |
| `botInvestigationUnfilteredMetricsByPageURL` | `variables/evar2` | 500 |
| `botInvestigationUnfilteredMetricsByRegion` | `variables/georegion` | 500 |
| `botInvestigationUnfilteredMetricsByUserAgent` | `variables/evar23` | 500 |
| `botInvestigationUnfilteredMetricsByBrowser` | `variables/browser` | 500 |
| `botInvestigationUnfilteredMetricsByBrowserType` | `variables/browsertype` | 100 |
| `botInvestigationUnfilteredMetricsByMobileManufacturer` | `variables/mobilemanufacturer` | 500 |

### Group: `bot_validation` (transform: `bot_validation`)

Default segments: Master Bot Filter (Exclude). Default row_limit: 5000.
Default metrics: event3, Clickouts CM, Engagement Rate CM, Engaged Visits CM, itemtimespent, pageviews.

| Report name | Dimension | Segments (override) | Row limit |
|---|---|---|---|
| `botFilterExcludeMetricsByMonth` | `variables/daterangemonth` | Exclude filter (default) | 5000 |
| `botFilterExcludexBotRuleMetricsByMonth` | `variables/daterangemonth` | Exclude filter (default) | 5000 |
| `botFilterIncludeMetricsByMonth` | `variables/daterangemonth` | Include filter override | 5000 |
| `botFilterIncludexBotRuleMetricsByMonth` | `variables/daterangemonth` | Include filter override | 5000 |
| `botFilterExcludexBotRuleXSuspiciousMarketingChannelsMetricsByMonth` | `variables/daterangemonth` | Exclude + Suspicious MC | 5000 |
| `botFilterExcludexBotRuleXDesktopMetricsByMonth` | `variables/daterangemonth` | Exclude + Desktop | 5000 |
| `botFilterExcludexBotRuleMetricsByPageUrl` | `variables/evar2` | Exclude filter (default) | 10 |
| `JustSegmentMetricsByMonth` | `variables/daterangemonth` | None (empty override) | 5000 |

### Group: `bot_rule_compare` (transform: `bot_rule_compare`)

No default segments (supplied per-rule at runtime). Default row_limit: 500.
Same metrics as bot_investigation.

| Report name | Dimension | Row limit |
|---|---|---|
| `botInvestigationMetricsByMarketingChannel` | `variables/marketingchannel` | 50 |
| `botInvestigationMetricsByMobileManufacturer` | `variables/mobilemanufacturer` | 500 |
| `botInvestigationMetricsByDomain` | `variables/filtereddomain` | 500 |
| `botInvestigationMetricsByMonitorResolution` | `variables/monitorresolution` | 500 |
| `botInvestigationMetricsByHourOfDay` | `variables/timeparthourofday` | 25 |
| `botInvestigationMetricsByOperatingSystem` | `variables/operatingsystem` | 500 |
| `botInvestigationMetricsByPageURL` | `variables/evar2` | 500 |
| `botInvestigationMetricsByRegion` | `variables/georegion` | 500 |
| `botInvestigationMetricsByUserAgent` | `variables/evar23` | 500 |
| `botInvestigationMetricsByBrowserType` | `variables/browsertype` | 100 |

### Group: `final_bot_metrics` (transform: `final_bot_metrics`)

No default segments. Default row_limit: 500. Metrics supplied per-report from segment list.

| Report name | Dimension | Segments | Row limit |
|---|---|---|---|
| `LegendFinalBotMetricsUnfilteredVisitsByYear` | `variables/daterangeyear` | None | 500 |
| `LegendFinalBotMetricsCurrentIncludeByYear` | `variables/daterangeyear` | Current approved bot rules (Include) | 500 |
| `LegendFinalBotMetricsDevelopmentIncludeByYear` | `variables/daterangeyear` | Development bot rules (Include) | 500 |

### Group: `lookup` (transform: `lookup`)

No segments. Row limit: 50000 (bulk lookup).

| Report name | Dimension |
|---|---|
| `Lookupvariablesbrowsertype` | `variables/browsertype` |
| `Lookupvariablesoperatingsystem` | `variables/operatingsystem` |
| `Lookupvariablesmobilemanufacturer` | `variables/mobilemanufacturer` |
| `Lookupvariablesmonitorresolution` | `variables/monitorresolution` |
| `Lookupvariablesmarketingchannel` | `variables/marketingchannel` |
| `Lookupvariablesgeoregion` | `variables/georegion` |

### Group: `topline` (transform: `summary_total`)

Topline no-dimension totals for RSID visit validation.

| Report name | Dimension | Segments |
|---|---|---|
| `toplineMetricsForRsidValidation` | null | All-traffic base segment |

### Group: `segment_builder` (transform: `segment_builder`)

Dimension-only inputs for segment condition building.

| Report name | Dimension | Segments | Row limit |
|---|---|---|---|
| `SegmentsBuildervariablesgeocountry` | `variables/geocountry` | Master Bot Filter | 12 |
| `SegmentsBuilderCountry50` | `variables/geocountry` | Master Bot Filter | 500 |
| `SegmentsBuildervariablesgeoregion` | `variables/georegion` | All-traffic segment | 100 |
| `SegmentsBuildervariablesmarketingchannelmarketing-channel-attribution` | `variables/marketingchannel.marketing-channel-attribution` | All-traffic segment | 100 |

### Group: `clickouts` (transform: `clickouts`)

Clickout metrics with geographic and AdCloud attribution breakdowns.
Default metrics: 4 clickout custom metrics.

| Report name | Dimension | Segments | Additional metrics |
|---|---|---|---|
| `LegendClickoutsByGeoregionNAOnly` | `variables/georegion` | All-traffic + NA-only filter | — |
| `LegendClickoutsAdCloudMetrics` | `variables/marketingchannel.marketing-channel-attribution` | AdCloud traffic segment | amo_cost, amo_clicks, amo_impressions |

---

## Composite Step Types

| Step type | `id` (output key) | Outputs produced | Can `depends_on` |
|---|---|---|---|
| `report_download` | any string | `job_id`, `json_folder`, `downloaded`, `skipped`, `copied` | any prior step |
| `transform_concat` | any string | `csv_folder`, `concatenated_file`, `ok`, `failed` | typically `validate_output` or `report_download` |
| `segment_creation` | any string | `segment_list_file`, `compare_list_file`, `validate_list_file`, `created_count` | any prior step |
| `validate_output` | any string | `missing_count` | `report_download` step |
| `lookup_generation` | any string | `lookup_file` | any |
| `dim_to_segments` | any string | `segment_list_file` | any |
| `bot_rule_compare` | any string | `job_id`, `json_folder`, `downloaded`, `skipped`, `copied` | any prior step |
| `final_bot_metrics` | any string | `job_id`, `json_folder`, `downloaded`, `skipped` | any prior step |
| `rsid_update` | any string | `investigation_list`, `validation_list` | any |
| `generate_country_matrix` | — | Not implemented; raises `NotImplementedError` | — |

**`validate_output` step fields:**
- `config_ref` (required): id of the `report_download` step whose expected outputs to check
- `retry` (bool, default `false`): if `true`, resets missing rows in DB and re-downloads

**`dim_to_segments` step fields** (under `dim_to_segments:` key):
- `dimension` (required): Adobe variable ID
- `rsid` (required): RSID to query
- `additional_segments`: list of segment IDs to intersect
- `num_pairs`: int (default 1)

**`bot_rule_compare` step fields:**
- `rsids`: `RsidSource`
- `bot_rules`: `BotRulesSource` (source: `file` | `step_output` | `inline`)
- `comparison_round`: float (default 1.0), injected into filename
- `rsid_lookup_file`: optional explicit path; falls back to latest file in `data/report_suite_lists/`

**`final_bot_metrics` step fields:**
- `rsids`: `RsidSource`
- `segment_list_file`: path string, OR `segment_list.source: step_output` with `step_id` + `output_key`
- `rsid_lookup_file`: optional explicit path
- `job_name`: string (default: step id)
- `interval`: `"full"` | `"month"` | `"day"` (default `"full"`)

---

## RSID Source Options

| `source` value | Required fields | Description |
|---|---|---|
| `file` | `file` (str path) | Reads one RSID (or `cleanName`) per line from a text file |
| `list` | `list` (list of str) | Inline list of RSIDs in the YAML |
| `single` | `single` (str) | Exactly one RSID specified directly |

All sources also accept `batch_size` (int, default 12): maximum concurrent API requests.

In composite jobs, `rsids.source: step_output` with `step_id` and `output_key` (e.g. `investigation_list`) resolves the file path from a prior step's outputs.

---

## Segment Source Options

| `source` value | Required fields | Description |
|---|---|---|
| `inline` | `ids` (list[str]) | Segment IDs given directly in YAML; each download gets all segments |
| `segment_list_file` | `file` (str path) | JSON file listing segment IDs; loaded at run time |
| `step_output` | `step_id`, `output_key` | Resolves a file path from a prior composite step's outputs; at runtime converts to `segment_list_file` |
| `latest_segment_list` | _(none)_ | Picks the most recently modified segment list file from the configured directory |

---

## Data Files Reference

| File / Directory | Produced by | Consumed by | Format |
|---|---|---|---|
| `data/rsid_lists/botInvestigationMinThresholdVisits.txt` | `rsid_update` job / `update-rsids` CLI | `report_download` / `bot_rule_compare` steps as `rsids.file` | One RSID or clean name per line |
| `data/rsid_lists/botValidationRsidList.txt` | `rsid_update` job / `update-rsids` CLI | `report_download` bot_validation steps | One RSID or clean name per line |
| `data/rsid_lists/excludedRsidCleanNames.txt` | Manual maintenance | `rsid_update` flow | One clean name per line; these RSIDs are excluded from generated lists |
| `data/rsid_lists/rsidList.txt` | Manual / legacy migration | Various report_download jobs | One RSID per line |
| `data/rsid_lists/archive/` | `rsid_update` (dated rotation) | — | Archived prior RSID list files |
| `data/report_suite_lists/legendReportSuites<YYYYMMDD>.txt` | `rsid_update` / `update-rsids` CLI | `segment_creation` (rsid_lookup_file), `bot_rule_compare`, `final_bot_metrics` | Tab-separated `rsid\tcleanName` pairs; latest file auto-discovered |
| `data/report_headers/<reportName>.yaml` | Checked into repo | `transforms/base.py` `load_column_headers()` | `columns: [list of CSV header strings]` |
| `data/lookups/<variableName>/lookup.txt` | `lookup_generation` job | `segment_creation` (dimension ID resolution) | Two-column `value\tnumericId` |
| `data/segment_lists/Legend/<name>.json` | `segment_creation` job | `report_download` / `final_bot_metrics` as `segments.file` | JSON list of segment IDs |
| `data/saved_segments/<segmentId>.json` | `get-segment` CLI | Reference / debugging | Adobe API segment definition JSON |
| `data/country_segment_lookup.json` | Migrated from legacy JS | `generate_country_matrix` step (not yet implemented) | Country → segment ID mapping |
| `data/rsid_country_thresholds/` | Manual | Country investigation flows | Per-RSID country visit thresholds |
| `data/user_lists/` | Manual | `segment_creation` (`share_with_users`) | Adobe user ID lists |

---

## Date Range Config

```yaml
date_range:
  from: "2025-01-01"   # YYYY-MM-DD or "today" (resolved at runtime)
  to: today
  lookback_days: 90    # optional: if set, from = to - lookback_days (overrides from)
```

`interval` controls how the date range is split into individual API requests:

| `interval` value | Behaviour |
|---|---|
| `"full"` | One request covering the entire date range |
| `"month"` | One request per calendar month within the range |
| `"day"` | One request per calendar day within the range |

---

## Test Mode

Set `test_mode: true` in the config or pass `--test` to `adobe-downloader run`.

When active, the job caps its iteration before making API calls:
- RSIDs: first `max_rsids` entries (default 3)
- Date intervals: first `max_date_intervals` intervals (default 2)
- Segments: first `max_segments` segments (default 5)

```yaml
test_mode: true
test_limits:
  max_rsids: 2
  max_date_intervals: 1
  max_segments: 3
```

CLI `--test` flag is merged into the job at runtime; it takes effect even if `test_mode: false` in the config.

---

## Resume Behaviour

Each `report_download` job (including steps within composite) creates or opens a SQLite database at:

```
<output.base_folder>/<client>/state/<job_id>.db
```

`job_id` is derived from the config file path + a hash of its content.

Before executing each API request, the request is registered with status `pending`. On success it is marked `completed`. On failure it is marked `failed` with the error message.

**On re-run (resume=true / no `--no-resume`):**
- Requests already in state `completed` are skipped without an API call.
- If the config YAML has changed since the last run, a warning is printed but execution continues (using the new config's request set).

**Forcing a fresh run:**
- Pass `--no-resume` to ignore all prior state.
- Or use `adobe-downloader reset --config <path> --confirm` to wipe state entirely.
- Or use `adobe-downloader retry --config <path> [--failed-only]` to re-queue specific requests.

Composite jobs additionally persist per-step state (`mark_step_started`, `mark_step_complete`). Completed steps are skipped on resume, with their outputs reloaded from the DB.

---

## Common Patterns

### Segments from a prior `segment_creation` step

```yaml
segments:
  source: step_output
  step_id: create_segments      # must match the id of the segment_creation step
  output_key: segment_list_file # key in that step's outputs dict
```

At runtime `_resolve_segments` converts this to `source: segment_list_file` with the resolved path.

### `depends_on` chaining

```yaml
- step: validate_output
  id: validate
  depends_on: download_investigation   # blocks until download_investigation is in step_outputs
  config_ref: download_investigation
```

If the dependency step is not in `step_outputs` at the start of a step, the runner tries to reload it from the DB (prior run). If still absent, it raises `RuntimeError`.

### `file_name_extra`

Appended to the middle of output filenames to distinguish runs with different parameters (e.g. different bot rule versions):

```yaml
file_name_extra: "V4-Compare"
# results in filenames like: Legend_botInvestigationMetricsByDomain_<rsid>_V4-Compare_<from>_<to>.json
```

Used by `source_pattern` in `transform_concat` to filter only that run's files:

```yaml
transform:
  source_pattern: ".*V4-Compare.*\\.json$"
```

### `delete_json_after_transform`

```yaml
post_processing:
  delete_json_after_transform: true   # removes .json files after CSV transform completes
  zip_csvs_after_concat: true
```

Only available on standalone `report_download` jobs (not composite steps).

### `zip_csvs_after_concat`

```yaml
post_processing:
  zip_csvs_after_concat: true   # zips the CSV output folder after concatenation
```

### Custom headers on concat

```yaml
concat:
  custom_headers:
    3: "BotRuleName"   # override column index 3 (1-based) with this header string
```

---

## Troubleshooting Quick Reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `Failed to load config: Schema validation failed` | Missing required field, wrong type, or mutually exclusive fields | Run `adobe-downloader validate -c <config>` for detailed field-level errors |
| `No credentials file found for client 'X'` | `credentials/X.json` is missing or misnamed | Create or rename the credentials file to match `client:` in the config |
| `401 Unauthorized` on API calls | Adobe access token expired or credentials wrong | Re-authenticate; check `credentials/<client>.json` has valid `client_id`, `client_secret`, `org_id` |
| `429 Too Many Requests` / rate limit errors | Too many concurrent requests | Reduce `batch_size` (e.g. from 12 to 6) |
| `report_ref 'X' not found in report_definitions/` | Report name misspelled or not in any YAML in `report_definitions/` | Check `report_definitions/*.yaml` for correct name; use `report_group` if you want all reports in a group |
| Missing output JSON files after download | Some requests failed; state shows them as `failed` | Run `adobe-downloader status -c <config>` to see failures; run `adobe-downloader retry -c <config> --failed-only` to re-queue |
| Transform fails with `No header definition found` | `data/report_headers/<reportName>.yaml` is missing | Add the header YAML for the new report; columns must match exactly what the API returns |
| `Row N has X values but header has Y columns` | CSV header count doesn't match API response data count | Check the report definition's `csv_headers` list and the corresponding `data/report_headers/` YAML |
| Resume skips a step unexpectedly | Step is marked complete in SQLite from a prior run | Use `--no-resume` to re-run everything, or reset the specific step via `StateManager` |
| `Step X depends_on Y which has not completed successfully` | Prior step failed or was never run, and its state is not in DB | Fix the dependency step's failure first; or use `--no-resume` |
| `No RSID lookup file found in data/report_suite_lists` | No `legendReportSuites*.txt` file in that directory | Run `adobe-downloader update-rsids` or `rsid_update` job to generate one |
| `segments.step_output references X which has not yet produced outputs` | The referenced step hasn't run yet (wrong step order in composite) | Ensure the `segment_creation` step appears before the `report_download` step in `steps:` list |
| `validate-output` reports missing files after download appears to complete | Some downloads silently failed; JSON files absent or empty | Run `adobe-downloader validate-output -c <config> --retry` to re-download specific missing files |
