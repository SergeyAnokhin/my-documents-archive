# API Reference — DocIntel Backend

Base URL: `http://localhost:8000`

## Documents

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents` | List documents. Params: `page`, `page_size`, `year`, `month`, `document_type`, `language`, `ocr_status` |
| GET | `/api/documents/{id}` | Get single document |
| DELETE | `/api/documents/{id}` | Soft-delete document (sets `is_deleted=true`) |
| PATCH | `/api/documents/{id}/tags` | Replace tags (body: `string[]`) |
| PATCH | `/api/documents/{id}/type` | Manually set document type (body: `{document_type: string}`). Sets `manually_classified=true` — batch jobs won't override it. |
| GET | `/api/documents/{id}/download` | Download original file (FileResponse). `?inline=1` serves it inline (used by the OCR Lab to embed PDFs/images) |

### Document response shape (`DocumentOut`)

```json
{
  "id": 1,
  "filename": "scan.pdf",
  "document_type": "passport",
  "classification_confidence": 0.92,
  "classification_source": "auto",
  "manually_classified": false,
  "tags": ["passport", "travel", "2024"],
  "summary": "Russian passport for Ivan Ivanov…",
  "language": "ru",
  "organization": null,
  "amount": null,
  "document_date": "2020-05-10T00:00:00",
  "ocr_status": "done",
  "vision_status": "skipped",
  "analysis_status": "done",
  "api_cost_analysis": 0.00004,
  "...": "other fields omitted for brevity"
}
```

`document_type`: one of 30+ taxonomy slugs (e.g. `passport`, `birth_certificate`, `contract`, `invoice`, `diploma`) or `unclassified` when the LLM cannot confidently categorise the document. `"other"` is a legacy value treated equivalently to `unclassified` by batch jobs.

`classification_confidence`: 0.0–1.0 assigned by the LLM; null for manually set types.

`classification_source`: `"auto"` (LLM) or `"manual"` (user override).

`ocr_status` / `vision_status` / `analysis_status`: `"pending" | "done" | "skipped" | "error"`

## Upload

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/upload` | Upload file. Multipart `file` field. Returns `{document_id, filename, message}`. Triggers background OCR + AI Analysis. |

## Search

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/search` | Search documents. Params: `query`, `mode`, `year`, `month`, `document_type`, `tag`, `language`, `ocr_status`, `page`, `page_size` |

`mode`: `fulltext` (SQLite LIKE over `ocr_text + filename + summary`) · `semantic` (ChromaDB, Phase 4) · `hybrid` (Phase 4)

Response: `{items: SearchResult[], total, page, page_size, mode}` where `SearchResult = {document, score, highlight?}`

## Admin

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/stats` | `{total, indexed, analyzed, embedded, pending, errors, unclassified, api_cost_total, library_path}` — `unclassified` counts analysis-done docs with type `unclassified`/`other`/null; `library_path` is the resolved library folder (shown in the Admin panel) |
| POST | `/api/admin/sync` | Scan library for new files, queue OCR+analysis for each. **Hard-deletes** docs whose file is missing or sits inside `.docintell`. Returns `{found, new_files, removed, message}`. **Returns 503** (aborts before any delete) when the library disk is unreachable — guarded by `storage.check_library_accessible()` (`.docintell` sentinel), so an offline NAS never wipes the DB |
| POST | `/api/admin/batch-index` | Queue OCR+analysis for all pending docs. Param: `limit` (default 50) |
| POST | `/api/admin/reclassify-all` | Re-run AI Analysis on all OCR-done but not-analyzed docs. Param: `limit` (default 200) |
| POST | `/api/admin/reclassify-unclassified` | Re-run AI Analysis on all `unclassified`/`other` docs where `manually_classified=false`. Param: `limit` (default 200) |
| GET | `/api/admin/folders` | List watched folders |
| POST | `/api/admin/folders` | Add folder `{path}`. Returns `WatchedFolderOut` |
| DELETE | `/api/admin/folders/{id}` | Remove folder |
| PATCH | `/api/admin/folders/{id}/toggle` | Enable/disable folder |
| GET | `/api/admin/providers` | List AI providers |
| POST | `/api/admin/providers` | Add provider `{name, provider_type, api_key, base_url?, model?}` |
| PATCH | `/api/admin/providers/{id}/toggle` | Enable/disable provider |
| DELETE | `/api/admin/providers/{id}` | Remove provider |
| GET | `/api/admin/providers/export` | Full provider config incl. **API keys**: `{version, providers:[…]}` (backup/migrate) |
| POST | `/api/admin/providers/import` | Restore providers. Body: `{providers, replace}` — `replace:true` wipes existing first, else appends |
| GET | `/api/admin/usage` | Recent usage-ledger rows. Params: `usage_type?`, `provider_type?`, `since?`, `until?`, `limit` (default 200). See [ai-usage.md](ai-usage.md) |
| GET | `/api/admin/usage/summary` | Totals + breakdowns by type/provider/model/day (super-user usage screen) |
| GET | `/api/admin/usage/pivot` | 2-D pivot. Params: `row`, `col`, `metric` (`count\|cost\|tokens_in\|tokens_out\|tokens`), `since?`, `until?` |
| DELETE | `/api/admin/usage` | Clear the usage ledger |
| GET | `/api/admin/settings` | Get all app settings `{key: value}` |
| PATCH | `/api/admin/settings` | Upsert settings. Body: `{key: value, ...}`. Key: `enable_ai_vision` (`"true"`/`"false"`) |
| GET | `/api/admin/log` | Recent log entries. Param: `limit` (default 100). Each entry has a `level` (`trace|debug|info|warning|error`); the Log tab filters client-side by minimum severity |
| GET | `/api/admin/backups` | List DB backup snapshots `[{name, size, modified}]`, newest first. Surfaced in the advanced-mode Backup tab |
| POST | `/api/admin/backups/restore` | Restore the DB from a snapshot. Body: `{name}`. Replaces the live DB (saves a `docintell.db.pre-restore` copy first); 400 on unknown/invalid name |

`provider_type`: `"openai" | "gemini" | "deepseek" | "openrouter" | "mistral"`

Default models per provider: OpenAI → `gpt-4o-mini`, Gemini → `gemini-2.5-flash`, DeepSeek → `deepseek-chat`, OpenRouter → `openai/gpt-4o-mini`, Mistral → `mistral-ocr-latest`

`supports_batch` is `true` for `gemini` and `mistral` — they offer a batch API at ~50% discount. Provider objects include this field so the UI can filter to batch-capable providers when creating batch tasks.

`mistral` is vision-only (dedicated OCR endpoint, per-page billing); use it in the Vision section. It transcribes the page verbatim into `vision_description`.

## Indexing

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/indexing/document/{id}` | Queue OCR+analysis for a single document (background) |
| POST | `/api/indexing/batch` | Queue OCR+analysis for pending docs. Param: `limit` (default 50) |
| POST | `/api/indexing/reclassify/{id}` | Re-run AI Analysis only on one document (background); resets `manually_classified=false` |
| POST | `/api/indexing/suggest-type/{id}` | Ask LLM to suggest top-3 types for this document. Returns `{suggestions: [{type, confidence, reason}], existing_types: string[]}`. Uses existing DB types as hints. |
| GET | `/api/indexing/status` | `{total, pending, done, error}` — used by IndexingBadge |

## Lab (OCR calibration — ephemeral, see [lab-mode.md](lab-mode.md))

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/lab/methods` | `{ocr_methods[], worker_available}` — local engines + easyocr-worker reachability |
| POST | `/api/lab/ocr` | `{doc_id, method}` (`tesseract`\|`easyocr`) → `{method, text, ms}` |
| POST | `/api/lab/vision` | `{doc_id, provider_id}` → `{provider_id, name, text, cost, ms}` (vision model as verbatim transcriber) |
| POST | `/api/lab/judge` | `{doc_id, provider_id, use_image, candidates[]}` → `{rankings[], best, summary, cost, ms}` (premium provider ranks transcriptions) |

## Health

`GET /api/health` → `{status: "ok", version: "0.1.0"}`

## Static Files

`/thumbnails/{document_id}.jpg` — document thumbnail (served by FastAPI StaticFiles)

## OCR Worker (`compute/`, port 8001)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Lists available engines |
| POST | `/ocr` | OCR file. Params: `engine` (`auto`/`tesseract`/`easyocr`), `languages` (e.g. `rus+fra+eng`). Returns `{text, pages, engine}` |
