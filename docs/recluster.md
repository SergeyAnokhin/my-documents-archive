# Cluster-Based Recategorization (Recluster)

Recluster resets document types from scratch by clustering all analyzed documents
by summary content (local, free embeddings + k-means), then asking an LLM to name
each cluster once (paid — one call per cluster, not per document). It lives in
[`backend/app/services/recluster.py`](../backend/app/services/recluster.py), with
entry points in [`admin_library.py`](../backend/app/routers/admin_library.py)
(simple button, `POST /api/admin/recluster`, fixed defaults) and
[`routers/tasks.py`](../backend/app/routers/tasks.py) (`recluster` task type,
configurable — see below).

## Pipeline

```
1. Load documents          Document.analysis_status=="done" AND summary not empty
2. Clean summaries         _strip_for_clustering(): strip dates, person/org names,
                            existing tags → topic-only text (falls back to the
                            original summary if stripping leaves <20 chars)
3. Embed                   sentence-transformers model reused from embeddings.py
                            (local, free — no external call)
4. Select k                _k_range() bounds + _best_k() tries ~8 candidate k
                            values, picks the one with highest silhouette score
5. K-means                 sklearn KMeans(k)
6. Pick representatives    3-5 docs nearest each cluster centroid
7. Name each cluster       _name_cluster(): one LLM call per cluster (paid) —
                            conflict-aware icon retry, see below
8. Apply                   old document_type → tags (if meaningful), new type set;
                            icons + multilingual names persisted
```

Entry point: `run_recluster(task_id=None, max_clusters=40, min_clusters=2, provider_id=None)`.

## min_clusters / max_clusters

`_k_range(n, max_clusters, min_clusters)` returns `[k_min, k_max]` passed to
`_best_k()`:

- `k_min = max(min_clusters, sqrt(n / 20))` — scales up with document count, but
  never below the configured floor.
- `k_max = min(max_clusters, max(k_min + 2, n // 5))` — capped at `max_clusters`,
  and guarantees at least ~5 docs per cluster.

Both are configurable per-run from the Tasks panel's recluster card (`min_clusters`/
`max_clusters` in the task `config`); the plain admin-panel button always uses the
defaults (2/40). `_best_k()` samples ~8 k values in that range and picks the
highest silhouette score (`sklearn.metrics.silhouette_score`).

## Provider selection

`run_recluster(..., provider_id=...)` resolves a specific `AIProvider` row once
upfront (avoiding a DB query per cluster) and reuses it for every `_name_cluster()`
call. Without a `provider_id`, it falls back to the first enabled analysis
provider (`ai_analysis._get_providers()`). Only creatable via the Tasks panel —
the simple admin-panel button has no provider picker.

## Icon-conflict retry loop (`_name_cluster`)

Each cluster's naming prompt lists two icon sets built from `type_icon_suggestion.
ALLOWED_ICONS`:

- **AVAILABLE** — `ALLOWED_ICONS` minus everything already taken.
- **EXCLUDED** — icons taken by earlier clusters in *this run*, seeded with
  `STATIC_ICON_VALUES` (icons already used by the built-in taxonomy).

The LLM must return `{slug, icon, name_en, name_fr, name_ru}`. If the icon is
unknown (not in `ALLOWED_ICONS`) or conflicts with `EXCLUDED`, it's added to the
exclusion set and the prompt retries (up to `max_retries=3`). If every attempt
conflicts, or no icons remain at all, `_name_cluster` returns the fallback
`("unclassified", "FileText", "Unclassified", "Non classifié", "Без категории")`
without erroring the whole run. If **every** cluster in a run falls back (e.g. the
provider is misconfigured), `run_recluster` aborts before touching any document —
see the "ALL cluster naming calls failed" guard.

## Multilingual name persistence

`_save_cluster_data()` writes two `AppSettings` keys (upsert — merges with any
prior run, never overwrites unrelated slugs), skipping built-in taxonomy slugs
and `"unclassified"`:

| Key | Shape | Read by |
|-----|-------|---------|
| `custom_type_icons` | `{slug: icon_name}` | `typeIcons.ts` → `iconForType()` |
| `custom_type_names` | `{slug: {en, fr, ru}}` | `typeIcons.ts` → `labelForType(type, lang)` — falls back to the raw slug if no name is stored for that language |

## Applying results

`_apply_new_type(doc, new_type)`: if the document's old type was meaningful
(not `"unclassified"`/`"other"`) and actually changed, it's preserved as a tag
before the new type is set; `classification_source` becomes `"auto"` and
`manually_classified` is reset to `False` (a recluster run always overrides a
prior manual classification).

## Testing

[`test_recluster.py`](../backend/tests/test_recluster.py) pins the pure-logic
helpers (`_strip_for_clustering`, `_k_range`, `_apply_new_type`,
`_save_cluster_data`) directly, and mocks `run_text` (no real LLM call) to pin
`_name_cluster`'s prompt construction and retry loop. `_best_k`/`_representative_indices`
(real k-means/silhouette numerics) are intentionally not pinned — they're
standard sklearn algorithms, not app-specific business rules.
