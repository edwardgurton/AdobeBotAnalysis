# How `_detect_transform_type` works

`_detect_transform_type` lives in `adobe_downloader/transforms/specialized.py`. It takes a JSON file path and returns a string identifying which transform function should process it. The mapping drives `transform_report_dispatch`, which is called for every JSON file during a `transform_concat` step.

---

## Why it exists

Every JSON file downloaded from Adobe Analytics must be converted to CSV before concatenation. Different report types produce different JSON shapes and require different CSV column layouts. Rather than requiring every job config to declare `type:` explicitly (though it can — see below), the tool infers the correct transform from the filename structure.

---

## The filename convention

All JSON files follow this general pattern, using `_` as the primary delimiter:

```
{client}_{reportName}[_{extra...}]_{fromDate}_{toDate}.json
```

The `extra` segments encode metadata about the report variant (RSID, bot rule name, segment ID, etc.). The exact number of `_`-delimited parts varies by report type.

---

## Detection logic, step by step

```python
parts = stem.split("_")        # split on underscores
report_part = parts[1]         # always the report/request name
```

Rules are tested in order. The first match wins.

### 1. `bot_rule_compare`

```python
if any("-Compare-" in p for p in parts):
    return "bot_rule_compare"
```

**Signal:** the literal string `-Compare-` (with hyphens on both sides) appears somewhere in the filename. This substring is injected by `bot_rule_compare.py` when it constructs the investigation name (`{rsid}-{ruleName}-Compare-V{n}-{trafficType}`).

Two filename formats exist — where `-Compare-` lands differs:

| Format | Where `-Compare-` appears | Example |
|--------|--------------------------|---------|
| **Production** (current code) | `parts[2]` | `Legend_botInvestigationMetricsByBrowser_`**`SBRcom-SG-GeoCountry-Compare-V1-AllTraffic`**`_2026-03-01_2026-05-31.json` |
| **Legacy** (historical files) | `parts[4]` | `Legend_botInvestigationMetricsByBrowserType_Casinoorg_FebMay25_`**`UserAgent-Compare-V1-AllTraffic`**`_2026-01-01_2026-01-31.json` |

`any(... for p in parts)` catches both without caring which part it lands in.

### 2. `final_bot_rule_metrics`

```python
if report_part.startswith("LegendFinalBotMetrics"):
    return "final_bot_rule_metrics"
```

**Signal:** `parts[1]` begins with `LegendFinalBotMetrics`.

Example: `Legend_`**`LegendFinalBotMetricsCurrentIncludeByYear`**`_FinalBotMetrics_rsid_rule_2025-12-01_2026-01-01.json`

### 3. `bot_validation`

```python
if report_part.startswith("botFilter"):
    return "bot_validation"
```

**Signal:** `parts[1]` begins with `botFilter`.

Example: `Legend_`**`botFilterExcludeMetricsByMonth`**`_Apr25ValidatedList_rsid_2026-01-01_2026-01-31.json`

### 4. `bot_investigation`

```python
if report_part.startswith("botInvestigation"):
    return "bot_investigation"
```

**Signal:** `parts[1]` begins with `botInvestigation`.

Example: `Legend_`**`botInvestigationMetricsByBrowser`**`_rsid_2026-01-01_2026-01-31.json`

> **Important:** `bot_rule_compare` files also have `parts[1]` starting with `botInvestigation`, but the `-Compare-` check in rule 1 fires first, so they are never mis-classified here.

### 5. Default: `summary_total_only`

```python
return "summary_total_only"
```

Anything that did not match the above. Delegates to the base `transform_report` function, which loads headers from a YAML file and appends `fileName`, `fromDate`, `toDate`.

---

## What happens when detection is wrong

If a `bot_rule_compare` file is mis-detected as `summary_total_only`, the transform falls back to `transform_report`. That function looks up a header YAML keyed on `parts[1]` — if a matching YAML exists it will produce a CSV, but only with `fileName`, `fromDate`, `toDate` appended. The rich columns (`rsidName`, `botRuleName`, `segmentId`, `trafficType`, etc.) will be absent from the concatenated output.

This was the root cause of the missing columns in `geo_singapore_sbr_mar_may26.yaml`: the production filename format puts `-Compare-` in `parts[2]`, but the old detection code only checked `parts[4]`, so every file fell through to `summary_total_only`.

---

## Overriding detection from the job config

A `transform_concat` step can set `type:` explicitly to skip auto-detection:

```yaml
- step: transform_concat
  id: transform
  transform:
    type: bot_rule_compare          # forces this transform regardless of filename
    source_pattern: ".*Compare.*\\.json$"
    concat: true
```

When `type` is set, `transform_report_dispatch` uses it directly and `_detect_transform_type` is never called. This is the safest option for composite jobs where filenames are known.

---

## Adding a new transform type

1. Write the transform function in `specialized.py` and register it in `_TRANSFORM_REGISTRY`.
2. Add a detection rule to `_detect_transform_type` **before** the `summary_total_only` fallback.
3. Add a test in `tests/test_transforms_specialized.py` covering the new detection rule and the transform output.
4. Add fixture JSON and `expected.csv` under `tests/fixtures/transforms/{new_type}/`.
