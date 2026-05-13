# Semantic Layer

Human-readable annotations for dimension and metric IDs used in this project.
These YAML files are the source of truth for `schema search` output — they add
`display_name`, `use_when`, `preferred_over`, `contexts`, and `notes` to raw
Adobe Analytics IDs.

## Files

| File | Contents |
|------|----------|
| `dimensions.yaml` | 21 dimension annotations (variables/\*, eVars, time dimensions) |
| `metrics.yaml` | 15 metric annotations (standard metrics, custom events, calculated metrics) |

## YAML format

```yaml
- id: variables/browser          # Adobe Analytics ID (required)
  display_name: Browser          # Short human name shown in search output
  description: "..."             # Documentation only — not loaded by the tool
  use_when: "..."                # Guidance on when to pick this dimension/metric
  preferred_over:                # IDs that this entry supersedes (may be empty)
    - variables/browsertype
  contexts:                      # Report groups where this ID appears
    - bot_investigation
    - bot_rule_compare
  notes: "..."                   # Any edge cases or implementation quirks
```

Valid `contexts` values match the report group names in `report_definitions/`:
`bot_investigation`, `bot_investigation_unfiltered`, `bot_validation`,
`bot_rule_compare`, `final_bot_metrics`, `segment_builder`, `lookup`,
`clickouts`.

## How to add or update an entry

1. Open `dimensions.yaml` or `metrics.yaml`.
2. Append (or edit) a block following the format above.
3. Commit with: `Semantic: add context for <id>`

**Never delete an entry without confirmation** — entries may be referenced by
downstream tooling or documentation.

## How `schema search` surfaces these annotations

Running `adobe-downloader schema search --query browser` returns matching
dimensions and metrics from the cache. If an entry exists in this semantic
layer for a matching ID, its `display_name`, `use_when`, `preferred_over`,
`contexts`, and `notes` are appended to the result.

The YAML files are read at search time — no rebuild or fetch step is needed
after editing them.

## How to ask Claude Code to update the semantic layer

> "The dimension `variables/evar5` is our clickout destination URL.
>  Add it to the semantic layer with contexts bot_investigation and bot_validation."

Claude Code will append the new entry and commit with the standard message.
