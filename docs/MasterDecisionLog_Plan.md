# Master Decision Log & Bot Compare Streamlining — Plan

**Status:** Draft v3 (D1–D5, D7, D8 decided) · 2026-11-03 · reconstructed from your notes and reviewed against the repo and `Bot Rule Compare V3 - Testing Version.xlsm`
**Use:** brief for Claude Code sessions in this repo. Follow the CLAUDE.md maintenance protocol (confirm → work → validate → update `IMPLEMENTATION_STATUS.md`).

---

## 0. Where things stand

| Item from your notes | Status | Evidence |
|---|---|---|
| Rule ID | ✅ Done | `SegmentCreation_Intermed2!J` → `SegmentCreationList_Final!L` |
| Round ID column (for list file name + job name) | ✅ Done | `Intermed2!K` → `Final!K` |
| Excel logic for the 3 possible parent rules | ✅ Done | `Intermed2!L:N` "Prior Rule ID 1-3" → `Final!P:R`. Tier order: Own Bot Rule - Validate > Combine - Validate > Own Bot Rule - Run Compare |
| Has Prior Step / Has Following Step | ✅ Done | `Final!N:O`, already present in `LegacyBotRule003B-RoundTwo.csv` |
| Clean template for sharing | ✅ Mostly | Raw Input is empty; 5 test rules remain in Fill In Sheet / Final |
| Highest `BotRuleCandidates` number function | ☐ Not started | `Final!B4` is still typed by hand (256) |
| Tag validate segments `BotRuleCandidates` | ☐ Not started | No tag code in `api_client.py` |
| Segment naming moved into Python | ☐ Not started | Names still come from `Final!M` |
| YAML record per segment | ☐ Not started | — |
| Generated run config from segment creation | ☐ Not started | Run configs are still hand-edited (e.g. `legend_comval_legacybotrule003-roundtwo-ALL-OTHER-STEPS.yaml`) |
| Segment details CSV → Bot Rule Compare input tab | ☐ Not started | `Final!B5:B10` typed by hand |
| Master Decision Log workbook + macros | ☐ Not started | `Validate - Decision Log` tab is a stopgap and says so in A1 |

### Guiding principle

`SegmentCreationList_Final` stays largely as it is, including the bot rule numbers it computes from `B4`. Those numbers are the **backup** if the Python numbering fails. Python treats the Excel output as a *proposal*. It overrides the 4-digit number and builds the final names. If the new columns are missing, it falls back to today's behaviour.

---

## 1. Terminology and naming convention

| Term | Meaning | Example |
|---|---|---|
| **Super-Investigation** | Every investigation that descends from one initial compare round. Shares the prefix of Round ID and Rule ID | `AH-Oddspedia` |
| **Investigation** | One compare or validate rule | `AH-Oddspedia-R1A` |
| **Round ID** | Rule ID without its trailing letter(s). Every rule in a round comes from the same parent compare and the same round number | `AH-Oddspedia-R1A2` |
| **Rule ID** | Unique key for an investigation, used throughout | `AH-Oddspedia-R1A2B` |
| **Parent Rule** | The compare whose analysis produced this rule (the `B3` prefix) | `AH-Oddspedia-R1A` |
| **Prior Rule** | An investigation whose result could make this one redundant (`Final!P:R`) | Combine - Validate is prior to Combine - Compare for the same feature |

**Rule ID grammar** (this is what the `B3` and `Intermed2!J` formulas already assume):

```
{AH|RT}-{FreeText}-IR                         initial compare (Super-Investigation root)
{AH|RT}-{FreeText}-R{round}{letter}           first generation        AH-Oddspedia-R1A
{parentRuleId}{round}{letter}                 later generations       AH-Oddspedia-R1A2B
```

- `FreeText` must be alphanumeric only. `-` would break the `TEXTSPLIT(…,"-")` in `B3`, `_` breaks filename parsing, and `~` is the description delimiter. Python should validate this.
- Sorting Round IDs alphabetically gives the right order *within a parent*, because rounds only go up to 5 (`Final!C14`).

**Segment names (built in Python, see A4):**

| Type | Adobe segment name | `botRuleName` (lists + filenames) | As seen in Raw Input |
|---|---|---|---|
| Compare | `BOTCOMPARE_{RuleID}~ {rsid} - {Dim=Item AND …}` | `BOTCOMPARE_{RuleID}~{compacted desc}` | `BOTCOMPARE-AH-Oddspedia-R1A~Oddspediacom…` → `B3` parses this unchanged |
| Validate | `{NNNN} BOT RULE: {rsid} - {Dim=Item AND …}` (unchanged) | unchanged (`0257BOTRULE…`) | — |

Write the Rule ID into the Adobe segment **description** field, which is empty today. That makes every segment traceable back to the Decision Log from Adobe.

---

## 2. Target end-to-end loop

```
 Bot Rule Compare V3 workbook                 Master Decision Log                 adobe-downloader (Python)
 ─────────────────────────────                ───────────────────                 ─────────────────────────
 0. Import Segment Details CSV ──┐
    (fills B3/B4/B5:B10)         │
 1. Analyse, fill Fill In Sheet  │
 2. SegmentCreationList_Final    │
 3. [ExportToDecisionLog] ──────────▶ Master: rows "Planned"
                                 │    4. [GenerateNextRound]
                                 │       - pick next eligible Round ID
                                 │       - check prior rules
                                 │       - write {RoundID}.csv  ─────────────▶ 5. segment_creation job
                                 │       - write create-config YAML              - next BotRuleCandidates number
                                 │                                                - build names, create, tag, share
                                 │                                                - write YAML record per segment
                                 │                                                - write {RoundID}_run.yaml
                                 │                                              6. run job (validate + compare)
                                 │                                                - segment_records step:
                                 │                                                  visits last 12m → YAML
                                 │    7. [ImportSegmentResults] ◀──────────────── {RoundID}_segment_records.csv
                                 │       seg IDs, final names, visits
                                 │    8. Decide on Validations / Compares tabs
                                 │       (accepted validates flow to Notion tab)
                                 └──────────────────────────────────────────────── {RuleID}_segment_details.csv
                                                                                    (for each compare → step 0)
```

---

## 3. Workstream A — Python (`adobe-downloader`)

### A1. Highest `BotRuleCandidates` number
- **New:** `adobe_downloader/segments/bot_rule_numbers.py`
  - `async def get_highest_bot_rule_candidate_number(client, tag: str = "BotRuleCandidates") -> int`
  - `BotRuleCandidates` is the tag your existing segments already carry in Adobe Analytics, so the lookup works against today's segments with no back-filling.
  - Pages through `GET segments` filtered by tag (`tagNames=`), requesting `name` only.
  - Takes the first 4 characters of each name when they match `^\d{4}`. Ignores names that don't follow the convention. Returns the max, or 0.
  - Uniqueness isn't guaranteed (no lock). That's acceptable because this is housekeeping.
- **New `AdobeClient` method:** `list_segments(tag_names, include_type, fields, page, limit)`.
  - ⚠️ Verify `includeType`. To see colleagues' segments (e.g. Lauren's) you may need `all` (admin) or `shared`.
- **New CLI:** `adobe-downloader bot-rule-number --client Legend [--next]`. Prints only the integer, so it can be piped or pasted into `B4`.
- **Tests:** mocked client with mixed names (`0256 BOT RULE…`, `BOTCOMPARE_…`, `12 BOT…`, untagged), plus pagination.

### A2. Tagging
- **New `AdobeClient` method:** `tag_segment(segment_id, tags)`.
- ⚠️ **Broker blocker:** `broker/adobe_broker.py` only implements `do_GET` and `do_POST`. Adobe's tag-assignment endpoint is (to verify) `PUT componentmetadata/tags/tagitems`. CLAUDE.md forbids Claude from editing the broker, so you'd need to add `do_PUT` yourself. Alternatively, check first whether `POST segments` accepts a `tags` array in the body. If it does, no broker change is needed.
- The tag is **`BotRuleCandidates`** (D4). Define it once as the default of `segment_creation.candidate_tag`, and have A1, A2, A3 and A7 all read that value. No other spelling should appear anywhere in code, configs, docs or the workbook Instructions tab.

### A3. Renumber and tag validate segments in `segment_creation`
In `flows/segment_creation.py`, when not in `test_mode_row`:
1. Call A1 once at the start → `next_num = highest + 1`.
2. For each **Validate** and **Validate - Special** row, in list order:
   - if the name starts with `\d{4}`, replace those 4 characters with `f"{next_num:04d}"`
   - otherwise prepend `f"{next_num:04d} "`
   - then `next_num += 1`

   Special rows take a number like any other validate (D5), so the sequence has no gaps and the number appears in their name and `botRuleName`.
3. **Validate rows:** create the segment, share it, tag it `BotRuleCandidates`.
4. **Validate - Special rows:** the **only** difference is that they skip the create step (and therefore share and tag). Everything else matches a normal validate:
   - they get the number and the final name
   - they get a YAML record (A5) with `segment_id: UPDATE-SEGMENT-ID`
   - they get a row in `_validate.csv` with `DimSegmentId = UPDATE-SEGMENT-ID`

   The log lists each Special row's final name so you can create it in Adobe Analytics under exactly that name. Then put the real segment ID in place of `UPDATE-SEGMENT-ID` in the `_validate.csv`, as you do today.
5. The `botRuleName` (and therefore output filenames) picks up the new number automatically, because it's derived from the name.
6. If A1 fails (broker down, API error), fall back to the Excel number and log a warning. This is the "backup" path.
- **Config:** `segment_creation.renumber_validates: true` (default true) and `segment_creation.candidate_tag: BotRuleCandidates`.
- **Compare - Special** rows behave as today: no create step, `UPDATE-SEGMENT-ID` placeholder, no number.

#### Special segments after you've created them
- **Run guard:** the generated run config (A6) refuses to start while any list it points at still contains `UPDATE-SEGMENT-ID`. It names the rows to fill in.
- **Back-fill:** the `segment_records` step (A7) copies the real segment ID from the list CSV into the YAML record.
- **Tagging (revised, D9):** the API's technical account is not an Analytics admin, and Adobe only lets non-admins tag components they own. Your manually created Special segments are owned by you, so Python **can't** tag them. **You tag each Special segment `BotRuleCandidates` yourself when you create it in Adobe.** In the same step, A7 checks every validate segment in the run and logs a warning listing any that are still untagged. It doesn't try to tag them. The check matters because A1 only sees tagged segments, so an untagged Special could otherwise have its number reused by a later round.

### A4. Move segment naming into Python
- `_read_csv` accepts the new optional columns `RuleID`, `RoundID`, `ParentRuleID`, `PriorRule1-3`, `HasPriorStep`, `HasFollowingStep`. `DictReader` already ignores unknown columns, so existing CSVs keep working.
- **New:** `build_segment_name(row, number)` and `build_bot_rule_name(row)`, using the formats in §1.
- If `RuleID` is present, Python builds the names. If it's absent, Python uses `SegmentName` exactly as today. This keeps old lists runnable.
- **Fix:** `transform_to_bot_rule_name` currently strips `-`, which flattens `LegacyBotRule003B-RoundOne` into `LegacyBotRule003BRoundOne` (see `LegacyRule003B-RoundOne_compare.csv`). With that, the next round's `B3` can't recover the Round ID. Compare names must keep the Rule ID verbatim and compact only the description after `~`.
- Validate the Rule ID grammar (§1) and fail fast with row numbers.

### A5. YAML record per created segment
- **Path:** `data/segment_records/{client}/{RuleID}.yaml` (falls back to the sanitized segment name if there is no Rule ID).
```yaml
rule_id: AH-Oddspedia-R1A2B
round_id: AH-Oddspedia-R1A2
super_investigation: AH-Oddspedia
parent_rule_id: AH-Oddspedia-R1A
compare_validate: Validate           # Compare | Validate | Compare - Special | Validate - Special
next_step: Combine - Validate
segment_name: "0257 BOT RULE: oddspediacom - OperatingSystem=Linux AND …"
bot_rule_name: 0257BOTRULEoddspediacomOperatingSystem-Linux…
bot_rule_number: 257                 # null for compares
segment_id: s3938_…                 # UPDATE-SEGMENT-ID for Special rows until back-filled (A7)
rsid: …                              # resolved RSID used at creation
rsid_clean_name: oddspediacom
conditions:                          # full values, not the abbreviated name
  - {dimension: OperatingSystem, adobe_variable: variables/operatingsystem, item: Linux, resolved_value: "…", operator: equals}
  - …
prior_rules: [AH-Oddspedia-R1A1A]
created_at: 2026-11-02T18:00:00Z
created_by_job: AH-Oddspedia-R1A2
visits_last_12_months: null          # filled by A7
visits_window: {from: null, to: null}
```
- `operator` is always `equals` for now. The field exists so that adding other operators later is additive.

### A6. Generate the run config from segment creation
- After writing the lists, `segment_creation` writes `jobs/generated/{RoundID}_run.yaml`. It's a composite containing:
  - download_validation → validate_output → transform_validation → **segment_records (A7)**
  - download_compare → validate_output → transform_compare → **segment_records (A7)**
  - The compare or validate half is left out when that list is empty.
- It points at the concrete list files (not `step_output`), so it can run on its own after Special segments have been edited in Adobe. `job_name` = Round ID.
- Defaults (`rsids` file, report groups, `batch_size`, `date_range.from`) come from a `run_template` path in the segment-creation config. Point it at a template in `jobs/templates/`. `date_range.to` defaults to yesterday.

### A7. `segment_records` step (post-run enrichment)
- **New composite step type:** back-fills Special segment IDs and warns about any validate segment not yet tagged (see A3, D9), then reads the transform output for the job, sums **Visits for the 12 months ending `date_range.to`** per bot rule across all RSIDs in the run, and writes the total into each YAML record.
- **Outputs, in the job output folder:**
  - `{RoundID}_segment_records.csv`: one row per rule (RuleID, SegmentId, final SegmentName, BotRuleNumber, RSIDCleanName, dims, Visits12m). This is the Decision Log import.
  - `{RuleID}_segment_details.csv`, one per **compare**: key/value rows (RuleID, RoundID, SegmentId, RSIDCleanName, LastBotRuleNumber, Dimension1…Dimension4Item). This is the Bot Rule Compare input tab.
- It's also available as a CLI command: `adobe-downloader segment-records --job {RoundID}`.

---

## 4. Workstream B — Bot Rule Compare V3 workbook + `BotRuleCompareMacros.bas`

| # | Change |
|---|---|
| B1 | New tab **`Segment Details Input`** (A:B key/value). Macro **`ImportSegDetails`** opens a file picker, defaulting to the job output folder, and pastes `{RuleID}_segment_details.csv`. |
| B2 | `Final!B5:B10` (and the `C` "Other" cells) become `XLOOKUP`s into that tab. `B4` = `LastBotRuleNumber` from the tab (still overridable). `B3`: use `RuleID` from the tab when present, otherwise parse `B1` as today. |
| B3 | Add columns to `Final` for the export: `ParentRuleID` (= `$B$3`) and `SuperInvestigation`. |
| B4 | **Fix:** `Final!M` re-derives the compare letter with `COUNTIFS` by round and type, excluding Skip `x`. `Intermed2!J` (Rule ID) counts by round only and ignores Skip. They agree today because compares sort first within a round. A Skip `x` on a compare row makes them diverge. Make `M` use `L` (Rule ID) directly. |
| B5 | Macro **`ExportToDL`**. Reads the Decision Log path from a cell, then upserts every non-Skip row of `Final` (J:AA + new columns) into Master by Rule ID. On a re-export it refuses to overwrite rows already past "Planned" and lists them. Keep the name short (the existing "formula too complex" button limit). |
| B6 | `CleanFile`: clear `Segment Details Input`. Set `RAW_LAST_COL` to `"W"`: the .bas already notes that T:W (segmentId/hash/dates) survive a clean. |
| B7 | Tidy-ups: make the Instructions tab name the tag as `BotRuleCandidates`, and point step 7 at the `bot-rule-number` CLI instead of a manual Adobe lookup. `Intermed2!H6/I6` test `$F6="x"`, but in Intermed2 column F is *Has Following Step*, so this is harmless but misleading. Retire the `Validate - Compare Log` and `Validate - Decision Log` tabs once the Master exists. Update the Instructions tab title (it still says V2). |

---

## 5. Workstream C — `MasterDecisionLog.xlsm`

**Build approach:** Claude Code can't reliably author a `.xlsm` with a VBA project from Python. Instead, mirror the existing `SetupTab` pattern:
- Claude writes `excel_files/MasterDecisionLogMacros.bas`, containing an idempotent **`SetupDL`** macro that builds all tabs, tables, headers, validation lists and buttons.
- You create a blank `.xlsm`, import the `.bas`, and run `SetupDL` once (decided, D8). The Bot Rule Compare changes (B1–B7) also ship as an updated `BotRuleCompareMacros.bas` for you to import.

### Tabs

| Tab | Purpose | Populated by |
|---|---|---|
| **Config** | Paths (segment creation list folder, jobs folder, segment records folder, Bot Rule Compare folder), client, share-with user IDs, `RoundOverride`, `SuperInvestigationFilter`, default `date_from` | You |
| **Master** (`tblMaster`) | One row per investigation; the single source of truth | Macros only (no typing) |
| **Validations** (`tblVal`) | Progress and decisions for validate rules | Macro appends new Rule IDs; **you** fill the Decision / Notes / Decided By / Date columns |
| **Compares** (`tblCmp`) | Progress for pending compares (analysed? children exported?) | Same pattern as Validations |
| **Notion** | Copy-paste block: Rule Name, SegmentId, SegmentURL, Source [RSIDCleanName], Visits Last 12 Months | `FILTER` formula on Accepted validates; no macro needed |
| **Lists** (hidden) | Status and decision vocabularies for data validation | `SetupDL` |

**Why inputs live on the progress tabs (decided, D1):** Master pulls Decision and Status back by Rule ID with `XLOOKUP`. Macros can then rewrite Master without ever overwriting a decision you've typed, and you can sort or filter the progress tabs freely.

**Progress tab input columns:** `Decision` · `KeepDespitePrior` · `Notes` · `DecidedBy` · `DecisionDate`. Every other column is macro-filled and locked.

### `tblMaster` columns
`RuleID` (key) · `RoundID` · `SuperInvestigation` · `ParentRuleID` · `CompareValidate` · `NextStep` · `Feature` · `Combine_Own` · `PlannedSegmentName` · `FinalSegmentName` · `BotRuleNumber` · `SegmentId` · `SegmentURL` · `RSIDCleanName` · `Dimension1…Dimension4Item` · `Operator1…4` (default `equals`) · `HasPriorStep` · `HasFollowingStep` · `PriorRule1…3` · `Status` · `Decision` (lookup) · `RedundantOverridden` (lookup) · `Visits12m` · `SourceWorkbook` · `ExportedAt` · `SegmentCreationList` · `JobName` · `LastUpdated`

### Status model
- **Validate:** Planned → Segments Requested → Segment Created → Data Ready → **Accepted / Rejected / Redundant**
- **Compare:** Planned → Segments Requested → Segment Created → Data Ready → **Analysed** (children exported) / **No Further Action** / **Redundant**
- Bold = terminal. A prior rule is *outstanding* while its status is non-terminal.
- **Redundancy (decided, D3):** when any prior rule is **Accepted**, `RefreshDL` marks the dependent rules **Redundant** automatically.
  - Only validates can be Accepted. A prior **Compare** therefore never makes its dependents redundant; it just holds them back until it reaches a terminal state.
  - **Override:** the Validations and Compares tabs each have a `KeepDespitePrior` column (Yes/blank). Setting it to Yes reverses the auto-Redundant: the row returns to *Planned*, counts as eligible for `NextRound`, and Master records `RedundantOverridden = TRUE` for the audit trail.
  - `RefreshDL` never re-applies Redundant to an overridden row.

### Macros (`MasterDecisionLogMacros.bas`)

| Macro | What it does |
|---|---|
| `SetupDL` | Builds or repairs the workbook structure (idempotent) |
| `RefreshDL` | Recomputes Redundant and eligibility flags, then appends any new Rule IDs to the Validations and Compares tabs |
| `NextRound` | **Determine:** (a) take `RoundOverride` if set; otherwise (b) gather Round IDs whose rows are all `Planned` (minus Redundant), filtered to `SuperInvestigationFilter` if set, sort them alphabetically, and take the first one where *no row has an outstanding prior rule*. **Validate:** if the chosen round has outstanding prior rules, stop and list them (this applies to the override too). **Write:** `{RoundID}.csv` in today's segment-creation-list format plus the new columns, to the Config folder. Also write `jobs/{client}_segcreate_{RoundID}.yaml` from a template string in Config (`job_name` = Round ID). Set the rows to *Segments Requested*. |
| `ImportResults` | Reads every `*_segment_records.csv` in the configured folder and upserts SegmentId, final name, number, Visits12m, and *Segment Created* or *Data Ready* into Master by Rule ID |
| (B5) `ExportToDL` | Lives in the Bot Rule Compare workbook and pushes into the Decision Log (decided, D7). To keep the two workbooks in step, it writes only to `tblMaster` columns found by **header name**, never by position, and stamps `SourceWorkbook` and `ExportedAt`. |

---

## 6. Build order (suggested Claude Code sessions)

1. **A1 + A2 (+ broker check):** number function, CLI and tagging. You verify against live Adobe and add `do_PUT` to the broker if needed.
2. **A3:** renumber and tag in `segment_creation`, with tests. *Usable on its own straight away:* it removes the manual `B4` lookup.
3. **A4 + A5:** Python naming, Rule ID columns, YAML records, backwards-compatibility tests using `LegacyRule003B-RoundOne.csv`.
4. **A6 + A7:** generated run config and the `segment_records` step with both CSV outputs.
5. **B1–B7:** Bot Rule Compare workbook changes plus a `.bas` update (you import it and re-test with the 5 test rules).
6. **C:** `MasterDecisionLogMacros.bas` + `SetupDL`, then a dry run end-to-end with `test_mode_row`.
7. **Docs:** Instructions tab, `user-docs/`, `jobs/templates/`, `IMPLEMENTATION_STATUS.md`.

---

## 7. Decisions

**Decided**

| # | Decision | Outcome |
|---|---|---|
| D1 | Where decisions are typed | On the Validations and Compares progress tabs; Master looks them up by Rule ID |
| D2 | "Visits last 12 months from all …" | Summed across all RSIDs in the run (`botValidationRsidList.txt`) for the 12 months ending `date_range.to`, from the transform output |
| D3 | Dependents of a decided prior rule | Auto-Redundant when a prior rule is Accepted, reversible with `KeepDespitePrior` = Yes (see §5 Status model) |
| D4 | Tag string | `BotRuleCandidates`: already applied in Adobe Analytics; used everywhere, defined once in config |
| D5 | Special validate rows | They take a number like any validate; the only difference is that they skip the create step. You create them in Adobe and fill in the segment ID; tagging happens in A7 |
| D7 | Which workbook owns the copy into the Decision Log | Bot Rule Compare pushes (`ExportToDL`) |
| D8 | How the macros reach Excel | Delivered as `.bas` files; you import them into the workbooks afterwards |
| D9 | Tagging segments the API doesn't own | The technical account stays non-admin (2026-11-03). Python tags only the segments it creates (A3). You tag Special segments in Adobe; A7 warns about any untagged validate segment |

**Still open (default in brackets; confirm at the start of the relevant session)**

| # | Decision | Default |
|---|---|---|
| D6 | `NextRound`: generate one round per click, or all eligible rounds? | [One per click; add batching later] |

## 8. Out of scope
- Operators other than `equals`. The `Operator` fields exist in the YAML and in Master but always hold `equals` for now.
- Guaranteeing unique bot rule numbers. The numbers are housekeeping, so A1's max+1 is good enough.

## 9. Gaps in the original notes (filled by inference; check these)
- "Copying the segment dimensions and items into the …" → read as *the Bot Rule Compare `Segment Details Input` tab* (B1).
- "New Compare segments need to …" → read as *keep the hyphenated Rule ID and use `~` as the delimiter* (A4).
- "Total Visits in the last 12 months from all …" → resolved as all RSIDs in the run (D2).
- "Note that the output …" (Decision Log requirements) → not recoverable.
- "Create a config file which could be used to create the segments for the …" → read as *the chosen round* (`NextRound` writes the create config; A6 writes the run config).
