# Schema Discovery Manual

`adobe-downloader schema` lets you fetch, cache, and search Adobe Analytics
dimension and metric metadata without leaving the terminal. The cache is stored
locally under `data/schema_cache/` so searches are instant and work offline.

---

## Why use it?

When building or reviewing a job config you often need to know:

- What dimensions are available on a given report suite?
- What is the ID for "Browser Type"?
- Which metrics can I add to a ranked report?

`schema search` answers those questions in seconds. `schema fetch` populates the
cache; `schema status` tells you how fresh it is.

---

## Commands

### `schema fetch` — populate the cache

```
adobe-downloader schema fetch --config PATH
```

Reads a `schema_discovery` job config, iterates the specified RSIDs, and
downloads dimension/metric metadata from the Adobe Analytics API. Results are
written to `data/schema_cache/dimensions/{rsid}.json` and
`data/schema_cache/metrics/{rsid}.json`. A grep-friendly markdown index is
rebuilt at `data/schema_cache/index/`.

**Example config** (`jobs/templates/schema_discovery.yaml`):

```yaml
job_type: schema_discovery
client: Legend
description: "Fetch dimension and metric metadata for all Legend RSIDs"

rsids:
  source: file
  file: data/rsid_lists/botInvestigationMinThresholdVisits.txt

# What to fetch: dimensions | metrics | both
mode: both

# Re-fetch if cache entry is older than this many days (0 = always refresh)
cache_ttl_days: 30

# Set true to ignore TTL and fetch everything regardless of cache age
force_refresh: false
```

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | required | Path to a `schema_discovery` YAML |

**Notes:**

- Only stale entries (older than `cache_ttl_days`) are re-fetched. Entries that
  are still fresh are skipped, making repeated runs cheap.
- Set `force_refresh: true` to re-fetch everything regardless of age.
- Calculated metrics are company-scoped (not per-RSID) and are fetched once and
  stored in `data/schema_cache/calculated_metrics.json`.

---

### `schema search` — find dimensions and metrics

```
adobe-downloader schema search --query TEXT [--type dimension|metric]
```

Searches across all cached RSID JSON files. Results are deduplicated by ID and
include the raw Adobe fields plus any semantic annotations from
`data/semantic_layer/`.

**Examples:**

```
adobe-downloader schema search --query browser
adobe-downloader schema search --query "operating system" --type dimension
adobe-downloader schema search --query visits --type metric
```

**Output fields:**

| Field | Source |
|-------|--------|
| `id` | Adobe API |
| `name` | Adobe API |
| `description` | Adobe API |
| `type` | Adobe API |
| `rsids` | Inferred from which RSID cache files contain this ID |
| `display_name` | Semantic layer (if present) |
| `use_when` | Semantic layer (if present) |
| `preferred_over` | Semantic layer (if present) |
| `contexts` | Semantic layer (if present) |
| `notes` | Semantic layer (if present) |

Semantic fields only appear when an entry for the ID exists in
`data/semantic_layer/dimensions.yaml` or `data/semantic_layer/metrics.yaml`.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--query` | required | Search string (matched against id, name, description) |
| `--type` | both | Filter to `dimension` or `metric` |

---

### `schema status` — check cache freshness

```
adobe-downloader schema status [--ttl N]
```

Lists every RSID in the cache alongside its last-updated timestamp and a
`FRESH` / `STALE` label relative to the given TTL.

**Options:**

| Flag | Default | Description |
|------|---------|-------------|
| `--ttl` | 30 | Days threshold for FRESH vs STALE |

---

## Cache layout

```
data/schema_cache/
  dimensions/
    trillioncoverscom.json    # raw API response for one RSID
    ...
  metrics/
    trillioncoverscom.json
    ...
  calculated_metrics.json     # company-scoped calculated metrics
  index/
    dimensions_index.md       # grep-friendly markdown (all RSIDs merged)
    metrics_index.md
    last_updated.json         # per-RSID timestamps for TTL checks
```

The index files are rebuilt on every `schema fetch` run. They use a consistent
heading format (`## {id} | {name}`) so you can grep them directly:

```
grep -i "browser" data/schema_cache/index/dimensions_index.md
```

---

## Typical workflow

1. Run `schema fetch` once after a new RSID list is published.
2. Use `schema search` when writing or reviewing job configs.
3. Run `schema status` periodically to see if a refresh is due.
4. Add `force_refresh: true` to the config for a full rebuild if the API
   schema has changed.
