# Semantic Layer Manual

The semantic layer adds human-curated context to raw Adobe Analytics dimension
and metric IDs. It lives in `data/semantic_layer/` and is the source of the
extra fields (`display_name`, `use_when`, etc.) shown by `schema search`.

---

## Why it exists

Adobe Analytics IDs like `variables/evar5` or `metrics/event12` are opaque.
The semantic layer is where the project records what those IDs actually mean,
when to use them, and which ones to prefer over others. This knowledge is:

- Surfaced automatically by `adobe-downloader schema search`
- Preserved in version control alongside the code
- Editable by hand or by asking Claude Code

---

## Files

| File | Contents |
|------|----------|
| `data/semantic_layer/dimensions.yaml` | Dimension annotations |
| `data/semantic_layer/metrics.yaml` | Metric annotations |
| `data/semantic_layer/README.md` | Format reference (short version) |

---

## YAML format

Each entry is a YAML list item. All fields except `id` are optional, but the
more you fill in the more useful `schema search` becomes.

```yaml
- id: variables/browser          # Adobe Analytics ID (required)
  display_name: Browser          # Short human name shown in search output
  description: "..."             # Documentation only — not loaded by the tool
  use_when: "..."                # When to pick this dimension/metric
  preferred_over:                # IDs this entry supersedes (list or empty)
    - variables/browsertype
  contexts:                      # Report groups where this ID appears
    - bot_investigation
    - bot_rule_compare
  notes: "..."                   # Edge cases or implementation quirks
```

**Valid `contexts` values** (match `report_definitions/` group names):

`bot_investigation` · `bot_investigation_unfiltered` · `bot_validation` ·
`bot_rule_compare` · `final_bot_metrics` · `segment_builder` · `lookup` ·
`clickouts`

---

## Worked example

Suppose `variables/evar5` is the clickout destination URL used in bot
investigation reports. A complete entry would look like:

```yaml
- id: variables/evar5
  display_name: Clickout Destination URL
  description: Records the destination URL at the moment a clickout event fires.
  use_when: >
    Investigating which destination URLs are hit by bot traffic; always pair
    with the Clickout metric (metrics/event12) to avoid counting page views.
  preferred_over: []
  contexts:
    - bot_investigation
    - clickouts
  notes: >
    Populated only when the clickout beacon fires. Will be empty for standard
    page-view hits.
```

---

## How to edit manually

1. Open `data/semantic_layer/dimensions.yaml` or `data/semantic_layer/metrics.yaml`.
2. Append a new block (or edit an existing one) following the format above.
3. Save the file — no rebuild or restart needed. Changes are picked up at
   search time.
4. Commit with: `Semantic: add context for <id>`

**Never delete an entry without confirming with the team.** Entries may be
referenced by downstream documentation or tooling.

---

## How to ask Claude Code to update the semantic layer

Describe what you know about a dimension or metric in plain English. Claude Code
will find or create the right entry and commit it.

**Examples:**

> "The dimension `variables/evar10` is the bot rule name matched by our segment
> builder. Add it to the semantic layer with contexts `bot_investigation` and
> `bot_validation`."

> "Add a note to `variables/browser` that it includes bot user-agent strings
> which look like real browsers — use `variables/browsertype` instead for
> high-level grouping."

> "Mark `metrics/event12` as our Clickout metric, preferred over
> `metrics/visits` when analysing clickout reports."

Claude Code will append or update the relevant YAML entry and commit with the
standard message `Semantic: add context for <id>`.

---

## How `schema search` surfaces annotations

When you run:

```
adobe-downloader schema search --query browser
```

the tool:

1. Searches across all cached RSID JSON files for IDs, names, or descriptions
   matching `browser`.
2. For each match, looks up the ID in `data/semantic_layer/dimensions.yaml` (or
   `metrics.yaml`).
3. Merges any present fields (`display_name`, `use_when`, `preferred_over`,
   `contexts`, `notes`) into the result.

Semantic fields appear inline beneath the raw Adobe fields. If no annotation
exists for an ID, the raw result is shown unchanged.

The YAML files are read at search time — editing them takes effect immediately
without running `schema fetch` again.

---

## Adding an entirely new ID

If a dimension or metric doesn't appear in the cache yet (perhaps it's a
calculated metric or a new eVar), you can still add a semantic layer entry for
it. The `id` field is just a string; `schema search` will include the annotation
as soon as the cache is populated via `schema fetch`.
