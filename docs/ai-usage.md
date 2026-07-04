# AI Usage Ledger, Super-User Screen & Provider Config Export/Import

Three related super-user features, all gated by **Advanced Mode** (the ⚡ toggle in
the header — there is no separate authentication; same trust model as Backup):

1. **AI usage ledger** — every call to an AI provider or OCR engine is recorded.
2. **AI Usage screen** — Admin → *AI Usage* tab: stats, charts, and a pivot table.
3. **Provider config export/import** — download / upload the AI provider list
   (API keys included) for backup or migrating between installs.

## 1. Usage ledger (`ai_usage` table)

One row per model/OCR call, written by [`services/usage.py`](../backend/app/services/usage.py)
`record_usage(...)`. The helper opens its own short-lived session and **never raises** —
recording must not break the calling pipeline.

| Column | Meaning |
|--------|---------|
| `created_at` | timestamp (UTC), indexed |
| `usage_type` | `analysis` · `vision` · `ocr` · `qa` · `suggest_types` · `icon_suggest` · `batch_analysis` · `batch_ocr` · `embedding` |
| `provider_type` | `openai` · `gemini` · `mistral` · `deepseek` · `openrouter` · `local` · `worker` |
| `provider_name` | the `AIProvider.name` when known |
| `model` | model id used |
| `tokens_in` / `tokens_out` | token counts (0 for OCR/embedding) |
| `cost_usd` | cost when known; `0.0` for free local steps; `null` if price unknown |
| `document_id` | source document when applicable |
| `status` | `ok` · `error` |
| `detail` | optional short note (e.g. `"12 docs, 1 failed"`) |

### Call sites instrumented

| Where | usage_type |
|-------|-----------|
| `ai_analysis.analyze_document` | `analysis` |
| `ai_analysis.suggest_document_types` | `suggest_types` |
| `ai_vision.describe_document` | `vision` |
| `qa.answer_question` (Q&A, `/ask`) | `qa` |
| `type_icon_suggestion._suggest_one` | `icon_suggest` |
| `indexer._run_ocr` (local Tesseract / EasyOCR worker) | `ocr` (cost 0) |
| `indexer._run_embedding` (sentence-transformers) | `embedding` (cost 0) |
| `batch_analysis.run_batch_analysis_gemini` | `batch_analysis` |
| `batch_ocr.run_batch_ocr_mistral` / `_gemini` | `batch_ocr` |

## 2. AI Usage screen

[`UsageTab.tsx`](../frontend/src/components/admin/tabs/UsageTab.tsx) reads three endpoints
([`routers/admin_usage.py`](../backend/app/routers/admin_usage.py)):

| Endpoint | Returns |
|----------|---------|
| `GET /api/admin/usage/summary` | totals + breakdowns by type / provider / model / day (cards + bar charts) |
| `GET /api/admin/usage/pivot?row=&col=&metric=` | dense matrix; dims: `usage_type`,`provider_name`,`model`,`day`,`month`,`provider_type`,`status`; metrics: `count`,`cost`,`tokens_in`,`tokens_out`,`tokens` |
| `GET /api/admin/usage` | recent rows (filter by `usage_type`/`provider_type`, `limit`) |
| `DELETE /api/admin/usage` | clear the ledger |

Charts are plain CSS bars (no chart library). The pivot row/column/metric are user-selectable
(`day` is one of the dimensions, so the pivot can be broken down per day). A **Period** selector
(All time / Today / Yesterday) sets `since`/`until` — in UTC day boundaries, matching the `day`
grouping — and is applied to all three reads (summary, pivot, recent rows). The "By usage type"
chart excludes `embedding` (free, high-volume, would dominate the bars); it still counts toward
totals and appears in the pivot table when `usage_type` is selected as a dimension.

## 3. Provider config export / import

| Endpoint | Behaviour |
|----------|-----------|
| `GET /api/admin/providers/export` | `{version, providers:[…]}` — **full** rows incl. `api_key` |
| `POST /api/admin/providers/import` | `{providers, replace}` — `replace:true` wipes existing first, else appends |

UI: Export/Import buttons in the AI Settings tab header. Export downloads a JSON file;
import reads a file and asks whether to replace or append.

⚠️ The exported file contains **API keys in plain text** — treat it as a secret.

## Classification of unclassified documents

Two paths exist depending on whether you want synchronous or async (batch) processing:

| Path | How it works | When to use |
|------|-------------|-------------|
| `POST /api/admin/reclassify-unclassified` | Synchronous; calls `indexer.reclassify_unclassified_batch()` per doc. Returns `{processed, errors, total_candidates}`. | Small backlog, immediate feedback |
| Task `reclassify_unclassified` (Tasks panel) | Gemini Batch with `classification_only=True`; sends summary/text and changes only classification fields. | Classify unknown docs cheaply |
| Task `reclassify_all` (Tasks panel) | Same classification-only Batch path for all eligible non-manual documents. | Apply a changed taxonomy without regenerating metadata |

The Admin → Indexing *Unclassified* stat counts OCR-done docs whose type is still
`unclassified`/`other`/null and that weren't classified by hand — i.e. exactly the set the
task retries (keyed on `document_type`, not `analysis_status`, so skipped/errored docs stay
visible).
