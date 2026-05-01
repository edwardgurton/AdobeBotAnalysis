# File Inventory and Disposition

Generated: 2026-05-01 · Step 0 of the `adobe-downloader` build plan.

Disposition tags: **port** · **consolidate** · **eliminate** · **data-migrate** · **archive**

- **port** — logic is significant enough to warrant its own Python module at the mapped path.
- **consolidate** — logic merges into an existing Python module alongside other JS files with the same role.
- **eliminate** — no Python equivalent needed; the pattern is superseded.
- **data-migrate** — file contains data (config, lookup tables, run inputs) that moves to a new location, not ported as code.
- **archive** — keep as historical reference; no active migration action required.

`node_modules/` is excluded from this inventory — it is eliminated wholesale.

---

## 1. Root JS files (`legacy_js/*.js`)

| File | Disposition | Python target | Notes |
|---|---|---|---|
| `downloadAdobeTable.js` | **port** | `flows/report_download.py` | Core single-report download orchestrator; rate limiter integration |
| `downloadBotInvestigationData.js` | **consolidate** | `flows/report_download.py` | Downloads 11 bot investigation report types (totals + daily); merges into report_download iteration logic |
| `downloadBotInvestigationUnfilteredData.js` | **consolidate** | `flows/report_download.py` | Mirror of above for Unfiltered variants; same target |
| `downloadBotRuleCompare.js` | **port** | `flows/bot_rule_compare.py` | AllTraffic copy-optimisation logic is significant; warrants own module |
| `downloadBotRuleValidationData.js` | **consolidate** | `flows/bot_rule_compare.py` | Shared-report copy logic duplicated here; merges into bot_rule_compare |
| `downloadFinalBotRuleMetrics.js` | **port** | `flows/final_bot_metrics.py` | Child-process spawning pattern replaced by async iteration across RSIDs × segments |
| `legendReportSuiteUpdater.js` | **port** | `flows/rsid_update.py` | Complex multi-phase orchestrator; own module |
| `buildSegmentsFromDimension.js` | **port** | `segments/dim_to_segments.py` | Dimension-value → segment creation; own module |
| `createSegmentFromList.js` | **port** | `flows/segment_creation.py` | CSV-driven segment creator with lookup normalisation and dual/single condition logic |
| `BotInvestigationGenerateCountrySegments.js` | **port** | `flows/country_investigation.py` | Multi-step country segment orchestrator (phase 1 of two-phase flow) |
| `iterateRsidCountriesBotInvestigation.js` | **consolidate** | `flows/country_investigation.py` | RSID×country iteration (phase 2); merges into country_investigation |
| `botInvestigationTransformConcat.js` | **port** | `flows/transform_concat.py` | Three-mode transform processor (RSID-only, RSID-country, ad-hoc) — most complex transform orchestrator |
| `processBotRuleComparison.js` | **consolidate** | `flows/bot_rule_compare.py` | CSV-batch + single-rule comparison runner; merges into bot_rule_compare |
| `processJSONFiles.js` | **consolidate** | `flows/transform_concat.py` | Generic JSON→CSV processor; one of seven identical-pattern processors all collapsed into `process_json_files()` |
| `processJSONFilesLegendBotInvestigation.js` | **consolidate** | `flows/transform_concat.py` | Same pattern, bot investigation transform variant |
| `processJSONFilesLegendBotValidation.js` | **consolidate** | `flows/transform_concat.py` | Same pattern, bot validation transform variant |
| `processJSONFilesLegendBotRuleCompare.js` | **consolidate** | `flows/transform_concat.py` | Same pattern, bot rule compare transform variant |
| `processJSONFilesLegendFinalBotRuleMetrics.js` | **consolidate** | `flows/transform_concat.py` | Same pattern, final bot rule metrics transform variant |
| `processJSONFilesSummaryTotalOnly.js` | **consolidate** | `flows/transform_concat.py` | Same pattern, summary-total-only transform variant |
| `botValidationTransformConcat.js` | **consolidate** | `flows/transform_concat.py` | Batch loop over processJSONFilesLegendBotValidation + concat; merges into transform_concat |
| `BotRuleCompareTransformConcat.js` | **consolidate** | `flows/transform_concat.py` | Same batch pattern for bot rule compare; merges into transform_concat |
| `finalBotRuleMetricsTransformConcat.js` | **consolidate** | `flows/transform_concat.py` | Same batch pattern for final bot rule metrics; merges into transform_concat |
| `validateBotInvestigationTypeOne.js` | **consolidate** | `flows/validation.py` | RSID investigation file validator; one of four validators all collapsed into validation.py |
| `validateBotInvestigationTypeTwo.js` | **consolidate** | `flows/validation.py` | RSID×country file validator |
| `validateBotValidationDownload.js` | **consolidate** | `flows/validation.py` | Bot validation download validator |
| `validateBotRuleComparisons.js` | **consolidate** | `flows/validation.py` | Bot rule comparison file validator |
| `callFunction.js` | **eliminate** | — | Commented-out example invocations; replaced entirely by YAML job configs + `adobe-downloader run` |
| `iterateRsidsBotInvestigation.js` | **eliminate** | — | Commented template file; same replacement |

---

## 2. Utility files (`legacy_js/utils/*.js`)

### 2a. Core layer targets

| File | Disposition | Python target | Notes |
|---|---|---|---|
| `getAdobeAccessToken.js` | **consolidate** | `core/auth.py` | OAuth client-credentials token fetch; merges into auth module |
| `getAdobeTable.js` | **consolidate** | `core/api_client.py` | POST to reports API; becomes `AdobeClient.get_report()` |
| `getAuthenticatedUserId.js` | **consolidate** | `core/api_client.py` | Discovery API call; becomes `AdobeClient.get_authenticated_user()` |
| `getGlobalCompanyID.js` | **consolidate** | `core/api_client.py` | Discovery API call; becomes `AdobeClient.get_global_company_id()` |
| `getAdobeUsers.js` | **consolidate** | `core/api_client.py` | User list fetch; becomes `AdobeClient.get_users()` |
| `getMultipleReportSuites.js` | **consolidate** | `core/api_client.py` | Report suite list fetch; becomes `AdobeClient.get_report_suites()` |
| `RateLimitManager.js` | **port** | `core/rate_limiter.py` | Sliding-window rate limiter (12 req / 6 s) + deadlock detection; own module |
| `compileRequest.js` | **consolidate** | `core/request_builder.py` | Request body assembly from template + params; merges into request_builder |

### 2b. Flow layer targets

| File | Disposition | Python target | Notes |
|---|---|---|---|
| `iterateDateRequests.js` | **consolidate** | `flows/report_download.py` | Day/month/full date iteration; merges into report_download iterators |
| `iterateRsidRequests.js` | **consolidate** | `flows/report_download.py` | Batched RSID iteration (12 per batch); merges into report_download |
| `iterateSegmentRequests.js` | **consolidate** | `flows/report_download.py` | Batched segment iteration; merges into report_download |
| `GenerateLegendReportSuiteLists.js` | **consolidate** | `flows/rsid_update.py` | RSID list generation by visit threshold; merges into rsid_update |
| `BIGCSValidateAndRetryMissingDownloads.js` | **consolidate** | `flows/validation.py` | Validate + retry for bot investigation country segments; merges into validation |
| `LGRSUValidateAndRetryMissingDownloads.js` | **consolidate** | `flows/validation.py` | Validate + retry for Legend RSID updater; merges into validation |
| `dimToSegments.js` | **consolidate** | `segments/dim_to_segments.py` | Dimension values → Adobe segment IDs mapping; merges into dim_to_segments |

### 2c. Transform layer targets

| File | Disposition | Python target | Notes |
|---|---|---|---|
| `jsonTransform.js` | **port** | `transforms/base.py` | Generic JSON→CSV transform with per-report header loading; own module |
| `jsonTransformLegendBotInvestigation.js` | **port** | `transforms/bot_investigation.py` | Bot investigation specialised transform |
| `jsonTransformLegendBotValidation.js` | **port** | `transforms/bot_validation.py` | Bot validation specialised transform |
| `jsonTransformBotRuleCompare.js` | **port** | `transforms/bot_rule_compare.py` | Bot rule compare specialised transform |
| `jsonTransformLegendFinalBotRuleMetrics.js` | **port** | `transforms/final_bot_rule_metrics.py` | Final bot rule metrics specialised transform |
| `jsonTransformSummaryTotalOnly.js` | **port** | `transforms/summary_total_only.py` | Summary-totals-only specialised transform |

### 2d. Segment layer targets

| File | Disposition | Python target | Notes |
|---|---|---|---|
| `createSegment.js` | **consolidate** | `segments/create_segment.py` | Single Adobe segment POST; merges into create_segment |
| `shareAdobeSegment.js` | **consolidate** | `segments/share_segment.py` | Share segment with user IDs; merges into share_segment |
| `saveSegment.js` | **consolidate** | `segments/save_segment.py` | Fetch + save segment definition locally; merges into save_segment |
| `getSegment.js` | **consolidate** | `segments/save_segment.py` | Fetch segment definition from API; merges into save_segment |
| `LookupFileGenerator.js` | **port** | `segments/lookup_generator.py` | Generate dimension lookup files; own module |
| `LookupValueSearcher.js` | **port** | `segments/lookup_searcher.py` | Search lookup files for numeric dimension ID; own module |

### 2e. Utility layer targets

| File | Disposition | Python target | Notes |
|---|---|---|---|
| `concatenateCSVs.js` | **port** | `utils/csv_concat.py` | CSV merge with header preservation + custom header overrides |
| `generateFromToDates.js` | **consolidate** | `utils/dates.py` | Date range generation (day/month, relative or fixed); merges into dates |
| `subtractDays.js` | **consolidate** | `utils/dates.py` | Subtract N days from date string; merges into dates |
| `retrieveValue.js` | **consolidate** | `utils/rsid_lookup.py` | Colon-delimited file lookup (bidirectional); merges into rsid_lookup |
| `retrieveLegendRsid.js` | **consolidate** | `utils/rsid_lookup.py` | RSID clean-name → ID lookup; merges into rsid_lookup |
| `retrieveLegendCountrySegments.js` | **consolidate** | `utils/rsid_lookup.py` | Country name → segment-ID lookup (case-sensitive + insensitive variants) |
| `extractValueId.js` | **consolidate** | `utils/extract_value.py` | Extract `value`/`itemId` pairs from Adobe API response rows |
| `readBotRulesFromCSV.js` | **port** | `utils/bot_rules_csv.py` | Three-mode bot rules CSV parser (download / transform / segment_list) |
| `getJsonStorageFolderPath.js` | **consolidate** | `utils/paths.py` | JSON storage path resolver; merges into paths |
| `getCsvStorageFolderPath.js` | **consolidate** | `utils/paths.py` | CSV storage path resolver; merges into paths |
| `saveJSONData.js` | **consolidate** | `utils/file_io.py` | JSON save helper; merges into file_io |

### 2f. Eliminated utils

| File | Disposition | Notes |
|---|---|---|
| `addRequestDetails.js` | **eliminate** | Mutates YAML config to add a reportConfig entry — pattern eliminated; request builder takes a dict directly |
| `deleteRequestDetails.js` | **eliminate** | Inverse of addRequestDetails; same reason |

---

## 3. Config files (`legacy_js/config/`)

### 3a. Header files (`config/headers/*/Legend.js`) — 35 files

All 35 Legend header files define the CSV column names for a specific report type. In the Python tool, headers are embedded in each report definition (co-located with the metrics/dimensions they describe) and live in `jobs/templates/` or `core/report_definitions.py` rather than as standalone files.

| Path | Disposition | Python target |
|---|---|---|
| `config/headers/botInvestigationMetricsByBrowser/Legend.js` | **data-migrate** | Report definition in `core/report_definitions.py` |
| `config/headers/botInvestigationUnfilteredMetricsByBrowser/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByBrowserType/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByBrowserType/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByDay/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByDay/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByDevice/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByDevice/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByDomain/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByDomain/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByHourOfDay/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByHourOfDay/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByMarketingChannel/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByMarketingChannel/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByMobileManufacturer/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByMobileManufacturer/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByMonitorResolution/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByMonitorResolution/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByOperatingSystem/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByOperatingSystem/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByPageURL/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByPageURL/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByRegion/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationUnfilteredMetricsByRegion/Legend.js` | **data-migrate** | Same |
| `config/headers/botInvestigationMetricsByUserAgent/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterExcludeMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterExcludexBotRuleMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterExcludexBotRuleMetricsByPageUrl/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterExcludexBotRuleXDesktopMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterExcludexBotRuleXSuspiciousMarketingChannelsMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterIncludeMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/botFilterIncludexBotRuleMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/JustSegmentMetricsByMonth/Legend.js` | **data-migrate** | Same |
| `config/headers/LegendFinalBotMetricsCurrentIncludeByYear/Legend.js` | **data-migrate** | Same |
| `config/headers/LegendFinalBotMetricsDevelopmentIncludeByYear/Legend.js` | **data-migrate** | Same |
| `config/headers/LegendFinalBotMetricsUnfilteredVisitsByYear/Legend.js` | **data-migrate** | Same |
| `config/headers/LegendClickoutsByGeoregionNAOnly/Legend.js` | **data-migrate** | Same |
| `config/headers/LegendClickoutsAdCloudMetrics/Legend.js` | **data-migrate** | Same |
| `config/headers/LegendTestBrowserTypes/Legend.js` | **data-migrate** | Same |
| `config/headers/toplineMetricsForRsidValidation/Legend.js` | **data-migrate** | Same |
| `config/headers/SegmentsBuilderCountry50/Legend.js` | **data-migrate** | Same |
| `config/headers/SegmentsBuildervariablesmarketingchannelmarketing-channel-attribution/Legend.js` | **data-migrate** | Same |
| `config/headers/SegmentsBuildervariablesgeoregion/Legend.js` | **data-migrate** | Same |
| `config/headers/Lookupvariablesbrowsertype/Legend.js` | **data-migrate** | Same |
| `config/headers/Lookupvariablesmarketingchannel/Legend.js` | **data-migrate** | Same |
| `config/headers/Lookupvariablesmonitorresolution/Legend.js` | **data-migrate** | Same |
| `config/headers/Lookupvariablesgeoregion/Legend.js` | **data-migrate** | Same |
| `config/headers/VisitsConversionsByGeoRegion/Capita.js` | **archive** | Capita-specific; not part of Legend build |

### 3b. Client configs and request templates

| File | Disposition | Target / Notes |
|---|---|---|
| `config/client_configs/clientLegend.yaml` | **data-migrate** | `credentials/clientLegend.yaml` — OAuth credentials; never commit |
| `config/client_configs/clientTemplate.yaml` | **data-migrate** | `jobs/templates/client_config_template.yaml` — becomes the new client config template |
| `config/client_configs/clientCapita.yaml` | **archive** | Capita client; out of scope for initial build |
| `config/read_write_settings/readWriteSettings.yaml` | **eliminate** | Read/write path config; replaced by output path fields in YAML job configs |
| `config/requests/templateRequest.js` | **data-migrate** | Request body structure moves into `core/request_builder.py` (build_request function) |
| `config/requests/templateSegment.js` | **data-migrate** | Segment definition structure moves into `segments/create_segment.py` |

### 3c. Segment lists (`config/segmentLists/Legend/`)

All segment list JSONs are live operational data.

| Path pattern | Disposition | Target |
|---|---|---|
| `config/segmentLists/Legend/Legend_*_variablesgeocountry_segments_*.json` (12 files) | **data-migrate** | `data/segment_lists/Legend/` |
| `config/segmentLists/Legend/Apr25ValidatedList.json` | **data-migrate** | `data/segment_lists/Legend/` |
| `config/segmentLists/Legend/Apr25ValidatedList-Aug25Additions.json` | **data-migrate** | `data/segment_lists/Legend/` |
| `config/segmentLists/Legend/Legend_*_variablesmarketingchannel_*.json` (1 file) | **data-migrate** | `data/segment_lists/Legend/` |

---

## 4. Useful info (`legacy_js/usefulInfo/`)

### 4a. Lookup data

| File | Disposition | Target |
|---|---|---|
| `usefulInfo/Legend/variablesbrowsertype/lookup.txt` | **data-migrate** | `data/lookups/variablesbrowsertype/lookup.txt` |
| `usefulInfo/Legend/variablesmarketingchannel/lookup.txt` | **data-migrate** | `data/lookups/variablesmarketingchannel/lookup.txt` |
| `usefulInfo/Legend/variablesmonitorresolution/lookup.txt` | **data-migrate** | `data/lookups/variablesmonitorresolution/lookup.txt` |
| `usefulInfo/Legend/variablesgeoregion/lookup.txt` | **data-migrate** | `data/lookups/variablesgeoregion/lookup.txt` |
| `usefulInfo/Legend/countrySegmentLookup.js` | **data-migrate** | `data/country_segment_lookup.yaml` (JS constant → YAML) |
| `usefulInfo/Legend/Segments/DualConditionSegment.json` | **data-migrate** | `data/saved_segments/` |
| `usefulInfo/Legend/Segments/SingleConditionSegment.json` | **data-migrate** | `data/saved_segments/` |
| `usefulInfo/Legend/Segments/s3938_*.json` (2 files) | **data-migrate** | `data/saved_segments/` |
| `usefulInfo/Legend/userLists/userList-2026-01-02.json` | **data-migrate** | `data/user_lists/` |
| `usefulInfo/Legend/LegendUsefulIds.txt` | **data-migrate** | `data/Legend_useful_ids.txt` |
| `usefulInfo/General/CommonMetrics` | **data-migrate** | `docs/reference/common_metrics.md` |
| `usefulInfo/General/CommonDimensions` | **data-migrate** | `docs/reference/common_dimensions.md` |

### 4b. RSID lists and thresholds

| File | Disposition | Target |
|---|---|---|
| `usefulInfo/Legend/rsidList.js` | **data-migrate** | `data/rsid_lists/rsidList.txt` (JS constant → plain text) |
| `usefulInfo/Legend/rsidListIterateCountries.js` | **data-migrate** | `data/rsid_lists/rsidListIterateCountries.txt` |
| `usefulInfo/Legend/rsidListOneReportOnly.js` | **data-migrate** | `data/rsid_lists/rsidListOneReportOnly.txt` |
| `usefulInfo/Legend/rsidListTesting.js` | **data-migrate** | `data/rsid_lists/rsidListTesting.txt` |
| `usefulInfo/Legend/botValidationRsidList.js` | **data-migrate** | `data/rsid_lists/botValidationRsidList.txt` |
| `usefulInfo/Legend/botInvestigationRsidCountriesMinThreshold.js` | **data-migrate** | Threshold value embedded in job YAML config |
| `usefulInfo/Legend/botInvestigationMinThresholdVisits.js` | **data-migrate** | Threshold value embedded in job YAML config |
| `usefulInfo/Legend/ReportSuiteLists/*.txt` (7 files) | **data-migrate** | `data/report_suite_lists/` |
| `usefulInfo/Legend/legendReportSuites.txt` | **archive** | Old snapshot; superseded by dated files in `ReportSuiteLists/` |
| `usefulInfo/Legend/excludedRsidCleanNames.js` | **data-migrate** | `data/rsid_lists/excludedRsidCleanNames.txt` |

### 4c. Run input CSVs

These are job input files, not code.

| Path pattern | Disposition | Target |
|---|---|---|
| `usefulInfo/Legend/segmentCreationLists/*.csv` | **data-migrate** | `jobs/inputs/segment_creation_lists/` |
| `usefulInfo/Legend/BotRuleLists/*.csv` | **data-migrate** | `jobs/inputs/bot_rule_lists/` |
| `usefulInfo/Legend/BotCompareLists/*.csv` | **data-migrate** | `jobs/inputs/bot_compare_lists/` |

### 4d. Archived / reference JS

| File | Disposition | Notes |
|---|---|---|
| `usefulInfo/Legend/StringsForCountries.js` | **data-migrate** | Country dimension value strings → `data/dimension_mappings.yaml` |
| `usefulInfo/Legend/botInvestigationAdHocList.js` | **archive** | Ad-hoc run data; historical reference only |
| `usefulInfo/Legend/botInvestigationRsidCountriesMinThresholdTesting.js` | **archive** | Testing variant; historical |
| `usefulInfo/Legend/createSegmentFromList.js` | **archive** | Duplicate of root `createSegmentFromList.js`; older version |
| `usefulInfo/Capita/CapitaUsefulIds.txt` | **archive** | Capita-specific; out of scope |

---

## 5. Transient / output files

| Path | Disposition | Notes |
|---|---|---|
| `temp/*.csv` (6 files) | **archive** | Temporary validation files from past runs; no migration action |
| `reportSuiteChecks/*.csv` (4 files) | **archive** | Historical validation output; no migration action |

---

## Summary counts

| Disposition | Count |
|---|---|
| port | 20 |
| consolidate | 36 |
| eliminate | 4 |
| data-migrate | ~80 |
| archive | ~15 |

**Total JS files inventoried:** 68 (28 root + 40 utils)
**Total non-JS files inventoried:** ~115 (headers, configs, data, run inputs, temp)
