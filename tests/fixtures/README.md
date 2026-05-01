# Test Fixtures

Step 0.75 deliverable. Fixtures for all six transform types and three representative request bodies.

## Status: synthetic

These fixtures were created from the transform source code analysis (JS), not from real API calls. The JSON structure and CSV mapping are correct, but the metric values are invented.

After **Step 5** (first live download) these should be replaced or supplemented with real API response files. Real fixtures will catch edge cases (null values, empty rows, non-ASCII dimension values, very large numbers) that synthetic ones may miss.

## Transform fixtures (`transforms/`)

Each directory contains:
- `{filename}.json` — input file, named using the exact naming convention the transform expects
- `expected.csv` — expected CSV output

The filename is not incidental — transforms parse metadata (report type, RSID, dates, bot rule name) from the filename.

| Directory | Transform | Report type | JS source |
|---|---|---|---|
| `base/` | Generic | `botInvestigationMetricsByBrowser` | `jsonTransform.js` |
| `bot_investigation/` | Bot investigation | `botInvestigationMetricsByBrowser` | `jsonTransformLegendBotInvestigation.js` |
| `bot_validation/` | Bot validation | `botFilterExcludeMetricsByMonth` | `jsonTransformLegendBotValidation.js` |
| `bot_rule_compare/` | Bot rule compare | `botInvestigationMetricsByBrowserType` | `jsonTransformBotRuleCompare.js` |
| `final_bot_rule_metrics/` | Final bot metrics | `LegendFinalBotMetricsCurrentIncludeByYear` | `jsonTransformLegendFinalBotRuleMetrics.js` |
| `summary_total_only/` | Summary totals | `toplineMetricsForRsidValidation` | `jsonTransformSummaryTotalOnly.js` |

### Notable differences between transforms

- **base** and **bot_investigation** are structurally identical (same mapping, same output). The only difference is `bot_investigation` hardcodes `clientName="Legend"` rather than parsing from filename.
- **bot_validation** appends `requestName`, `botRuleName`, `rsidName` instead of `fromDate`/`toDate`.
- **bot_rule_compare** has hardcoded headers and parses the filename into many metadata columns. The `AllTraffic` vs `Segment` distinction affects the filename parse path and which columns are populated.
- **final_bot_rule_metrics** appends both `botRuleName`+`rsidName` AND `fromDate`+`toDate`. The header file has only 7 columns; the extra 2 columns (`botRuleName`, `rsidName`) are produced but unlabelled in the header.
- **summary_total_only** reads `summaryData.totals` and `columns.columnIds` instead of `rows`. Produces a single-row CSV.

## Request body fixtures (`request_bodies/`)

Representative compiled request bodies showing what `core/request_builder.py` should produce for:

| File | Report | Notes |
|---|---|---|
| `botInvestigationMetricsByBrowser.json` | Bot investigation by browser | 7 metrics, segment filter, dimension |
| `botFilterExcludeMetricsByMonth.json` | Bot validation monthly | 8 metrics, 2 segment filters (global + bot rule), dimension |
| `toplineMetricsForRsidValidation.json` | Topline validation | 2 metrics only, no dimension, segment-only filter |

These will be used in Step 4 tests to verify that `build_request()` produces the correct JSON for each report type.
