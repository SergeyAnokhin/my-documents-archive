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
| `provider_type` | `anthropic` · `openai` · `gemini` · `mistral` · … · `local` · `worker` |
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
| `search.ask_documents` (Q&A) | `qa` |
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

Charts are plain CSS bars (no chart library). The pivot row/column/metric are user-selectable.

## 3. Provider config export / import

| Endpoint | Behaviour |
|----------|-----------|
| `GET /api/admin/providers/export` | `{version, providers:[…]}` — **full** rows incl. `api_key` |
| `POST /api/admin/providers/import` | `{providers, replace}` — `replace:true` wipes existing first, else appends |

UI: Export/Import buttons in the AI Settings tab header. Export downloads a JSON file;
import reads a file and asks whether to replace or append.

⚠️ The exported file contains **API keys in plain text** — treat it as a secret.

## Classification "done but still unclassified" — outcome reporting

The *Classify unclassified* job ([`indexer.reclassify_unclassified_batch`](../backend/app/services/indexer.py))
used to report only `processed`, which counted every iterated doc regardless of result —
so a doc could stay `unclassified` while the task turned green. It now reports real
outcomes: `candidates`, `classified`, `still_unclassified`, `skipped` (no OCR text),
`errors`, and `no_provider`. With **no analysis provider configured** the task finishes
with status `error` and an explicit message instead of a silent success.

A doc legitimately stays unclassified when the LLM returns `"unclassified"` again, when
it has no OCR text, or when no analysis provider exists. For cheap bulk classification of
the backlog, use the **Gemini Batch Analysis** task, whose selection now also covers
already-analyzed-but-unclassified docs.

The Admin → Indexing *Unclassified* stat counts OCR-done docs whose type is still
`unclassified`/`other`/null and that weren't classified by hand — i.e. exactly the set the
job retries (keyed on `document_type`, not `analysis_status`, so skipped/errored docs stay
visible).
