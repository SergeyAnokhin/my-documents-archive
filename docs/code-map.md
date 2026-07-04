# Code Map — DocIntel

Quick index for LLM navigation. Check this file before grepping.

## Start Here For...

Use this section to jump straight to the likely owner files for a task.

| Task | Start here |
|------|------------|
| Upload flow | `backend/app/routers/upload.py`, `backend/app/services/storage.py`, `backend/app/services/indexer.py`, `frontend/src/components/documents/UploadZone.tsx` |
| Search / Ask mode | `backend/app/routers/search.py`, `backend/app/services/search_query.py`, `backend/app/services/qa.py`, `frontend/src/components/search/`, `frontend/src/pages/home/HomePageAIMode.tsx` |
| Document viewer / metadata editing | `frontend/src/components/documents/DocumentViewer.tsx`, `MetadataTab.tsx`, `TextTab.tsx`, `DevTab.tsx`, `backend/app/routers/documents.py` |
| OCR / indexing pipeline | `backend/app/services/indexer.py`, `ocr.py`, `pdf_extract.py`, `docx_extract.py`, `text_extract.py`, `ai_vision.py`, `ai_analysis.py` |
| Batch OCR / batch analysis | `backend/app/services/batch_ocr.py`, `batch_ocr_mistral.py`, `batch_ocr_gemini.py`, `batch_analysis.py`, `frontend/src/components/tasks/` |
| Lazy indexing plan | `backend/app/services/indexing_plan.py`, `task_runners.py`, `frontend/src/components/tasks/CreateTaskModal.tsx` |
| Admin library actions | `backend/app/routers/admin.py`, `admin_library.py`, `frontend/src/components/admin/tabs/IndexingTab.tsx` |
| AI provider setup / model picking | `backend/app/routers/admin_providers.py`, `backend/app/services/provider_models.py`, `backend/app/services/arena_ratings.py`, `frontend/src/components/admin/tabs/AITab.tsx`, `frontend/src/components/admin/tabs/ai/` |
| Tasks panel / background jobs | `backend/app/routers/tasks.py`, `backend/app/services/task_runners.py`, `task_runtime.py`, `frontend/src/components/tasks/TasksPanel.tsx` |
| Folder browser | `backend/app/routers/documents.py`, `backend/app/services/folder_tree.py`, `frontend/src/components/documents/FolderTreeView.tsx`, `frontend/src/pages/home/HomePageFolderResults.tsx` |
| OCR Lab | `backend/app/routers/lab.py`, `backend/app/services/lab.py`, `frontend/src/pages/LabPage.tsx`, `frontend/src/pages/lab/` |
| Backups / restore | `backend/app/routers/admin_backups.py`, `backend/app/services/db_backup.py`, `frontend/src/components/admin/tabs/BackupTab.tsx`, `backend/backup.py` |
| Deployment / k8s | `deploy/`, `backend/Dockerfile`, `frontend/Dockerfile`, `.github/workflows/build.yml`, `docs/deployment.md` |

## Key Entry Points

These are the files most often worth opening first.

| Area | Primary entry point | Usually inspect next |
|------|---------------------|----------------------|
| Backend app startup | `backend/app/main.py` | `config.py`, `database.py`, relevant router |
| Document CRUD / tree | `backend/app/routers/documents.py` | `schemas.py`, `services/folder_tree.py` |
| Search API | `backend/app/routers/search.py` | `services/search_query.py`, `services/qa.py` |
| Admin API | `backend/app/routers/admin.py` | the relevant `admin_*.py` router |
| Indexing pipeline | `backend/app/services/indexer.py` | OCR / Vision / Analysis services |
| Task execution | `backend/app/routers/tasks.py` | `services/task_runners.py`, `task_runtime.py` |
| Frontend app shell | `frontend/src/App.tsx` | `pages/HomePage.tsx`, `pages/LabPage.tsx` |
| Home screen orchestration | `frontend/src/pages/HomePage.tsx` | `pages/home/`, `components/search/`, `components/documents/` |
| Admin UI shell | `frontend/src/components/admin/AdminPanel.tsx` | the relevant tab in `components/admin/tabs/` |
| Tasks UI | `frontend/src/components/tasks/TasksPanel.tsx` | `TaskCard.tsx`, `CreateTaskModal.tsx`, `taskConfig.ts` |

## If You Change X, Also Check Y

These are the common cross-file links that save unnecessary grep.

- Upload or library ingestion: also check `backend/app/services/storage.py`, `backend/app/services/indexer.py`, and `frontend/src/components/documents/UploadZone.tsx`.
- Search ranking or Ask retrieval: also check `backend/app/services/search_query.py`, `backend/app/services/qa.py`, and `frontend/src/components/search/AIAnswer.tsx`.
- OCR behavior: also check `backend/app/services/indexer.py`, `backend/app/services/ocr.py`, and the relevant extraction helper (`pdf_extract.py`, `docx_extract.py`, or `text_extract.py`).
- Vision or analysis fields: also check `backend/app/services/ai_common.py`, `backend/app/services/indexer.py`, and `backend/app/models.py`.
- Document type labels or icons: also check `frontend/src/components/documents/typeIcons.ts`, `backend/app/services/type_icon_suggestion.py`, and `backend/app/services/recluster.py`.
- Task types or task status handling: also check `backend/app/services/task_runners.py`, `backend/app/services/task_runtime.py`, `frontend/src/components/tasks/taskConfig.ts`, and `frontend/src/components/tasks/CreateTaskModal.tsx`.
- Folder tree behavior: also check `backend/app/services/folder_tree.py`, `frontend/src/pages/home/HomePageFolderResults.tsx`, and `frontend/src/components/documents/FolderTreeView.tsx`.
- Admin sync / cleanup semantics: also check `backend/app/services/storage.py`, `backend/app/services/embeddings.py`, and the hard-delete gotchas below.
- AI provider settings: also check `backend/app/models.py`, `backend/app/services/provider_models.py`, `backend/app/services/arena_ratings.py`, and `frontend/src/components/admin/tabs/ai/`.
- Deployment values or image tags: also check `deploy/helm/my-documents-archive/values.yaml`, `.github/workflows/build.yml`, and `docs/deployment.md`.

## Directory Tree

```
backend/          FastAPI Python backend (main app)
compute/          External OCR microservice (optional, runs on separate machine)
frontend/         React + Vite + TypeScript UI
docs/             Architecture docs (you are here)
deploy/           Helm chart + ArgoCD Application for k3s deployment
.github/workflows/ CI: build images → GHCR → bump tags → push `deploy` branch
```

## Backend (`backend/app/`)

| File | Responsibility |
|------|---------------|
| `run.py` | Dev entry point (`python run.py` → uvicorn on :8000) |
| `main.py` | FastAPI app factory, CORS, startup hooks (incl. `recover_running_tasks()` — auto-resumes/stops orphaned `Task` rows left "running" by an unclean restart), thumbnail static mount |
| `config.py` | All settings (pydantic-settings); `settings` singleton |
| `database.py` | SQLAlchemy engine, `SessionLocal`, `get_db()`, `init_db()` |
| `models.py` | ORM models: `Document` (incl. `source` = `"upload"`/`"sync"`, `title` = short AI-generated display headline distinct from `summary`), `WatchedFolder`, `IndexingLog` (incl. `level` = `trace`/`debug`/`info`/`warning`/`error`), `AIProvider`, `AppSettings`, `Task`/`TaskLog`, `AIUsage` (per-call AI/OCR usage ledger — powers the super-user usage screen) |
| `schemas.py` | Pydantic request/response schemas for all endpoints |
| `routers/documents.py` | CRUD: list, get, patch tags, patch type (`PATCH /{id}/type` sets type + `manually_classified=true`) — prefix `/api/documents`. `DELETE /{id}` hard-deletes (file + thumbnail + embedding + row, see gotchas). `GET /tags` returns distinct tags across the library (must stay registered before `/{id}`). `GET /tree` returns the full folder tree (via `services/folder_tree.py`) for the Explorer-style folder-browse view (also registered before `/{id}`) |
| `services/folder_tree.py` | `build_folder_tree(db)` — groups all non-deleted documents by the directory components of `filepath` (relative to `library_path`) into a nested `FolderTreeNode` tree (folders + `FolderTreeDoc` leaves, sorted alphabetically, with per-folder and recursive doc counts). Powers `GET /api/documents/tree` |
| `routers/upload.py` | File upload endpoint — prefix `/api/upload` |
| `routers/search.py` | Search endpoints only — prefix `/api/search`. `GET /` fulltext/semantic/hybrid, `GET /embedded-ids`, `GET /quality-counts`, `GET /ask` (thin wrapper over `services/qa.py`). Query-building helpers live in `services/search_query.py` |
| `services/search_query.py` | Text-query helpers shared by search + `/ask`: `_parse_query` (quoted phrases), `_apply_text_filter` (LIKE over filename/ocr_text/summary/type/tags/person/org), `_highlight` snippets, `_merge_hybrid` (both→semantic→fulltext tier order), `_semantic_scored`, `_fulltext_ids`, Cyrillic↔Latin transliteration (`_expand_fulltext_query`) |
| `services/qa.py` | `/ask` AI Q&A pipeline: depth config (`_DEPTH_CFG`), hybrid retrieval, `build_context()`/`build_prompts()` (what the paid LLM receives), `answer_question()` → `AIAnswerResponse`, retrieval INFO table + `AskDebug` trace (`?debug=true`), usage recording. Split out of `routers/search.py` |
| `routers/admin.py` | **Aggregator** — mounts the five `admin_*` sub-routers under prefix `/api/admin`. Start here, then jump to the right sub-router below |
| `routers/admin_library.py` | Stats, sync, batch-index, reclassify-all/unclassified, log (+ `_log` helper) |
| `routers/admin_folders.py` | Watched-folder CRUD: list / add / remove / toggle |
| `routers/admin_providers.py` | AI providers CRUD, model listing (`/models`), arena ratings (`/arena-ratings`) |
| `routers/admin_settings.py` | App settings key-value get/upsert (`/settings`) |
| `routers/admin_backups.py` | DB backup list + create + restore (advanced users): `GET /backups`, `POST /backups`, `POST /backups/restore`; retention setting `GET/PATCH /backups/keep` |
| `routers/admin_usage.py` | AI usage ledger (super-user screen): `GET /usage` (rows), `GET /usage/summary` (cards+charts), `GET /usage/pivot` (row×col×metric matrix), `DELETE /usage`. See [ai-usage.md](ai-usage.md) |
| `routers/admin_providers.py` (export/import) | `GET /providers/export` + `POST /providers/import` — full provider config **including API keys** (backup/migrate). See [ai-usage.md](ai-usage.md) |
| `services/db_backup.py` | List/create/restore SQLite backups written by the `backup.py` sidecar; restore = atomic swap + `docintell.db.pre-restore` safety snapshot; retention count (`get_keep_count`) reads `AppSettings.backup_keep`, falling back to `BACKUP_KEEP` env var |
| `services/storage.py` | File hashing, MIME detection, library scanning (skips `.docintell`/hidden dirs), saving uploads to `YYYY/MM/`. `SUPPORTED_EXTENSIONS`/`SUPPORTED_MIME_TYPES` — the upload/sync allowlist (pdf, jpg/jpeg/png/tiff/tif/heic/heif/webp, docx, txt). `infer_document_date()`/`extract_folder_date()` guess a doc date from path (`[YYYY-MM]`, `YYYY/MM/`, `YYYY-MM/`) or file ctime. `check_library_accessible()` — sentinel check (`.docintell` dir) used to abort sync when the disk is offline |
| `services/thumbnails.py` | Generate JPEG thumbnails (Pillow + pdf2image) |
| `services/ocr.py` | OCR extraction: local Tesseract or external worker (fallback chain). `extract_text()` returns `(text, engine)`; the indexer stores `engine` (`tesseract`/`easyocr`/`native`) in `documents.ocr_model` for per-doc engine attribution. For `.pdf` files, first tries `pdf_extract.extract_pdf_text()` (embedded text layer, no OCR); only rasterizes+OCRs (all pages, no page cap) when that returns `None` (scanned/image-only PDF) or raises |
| `services/pdf_extract.py` | Native PDF text-layer extraction (`pypdf`, no OCR): `extract_pdf_text(filepath)` joins each page's `extract_text()` and returns `None` if the total is under `MIN_TEXT_LENGTH` (treated as scanned — caller falls back to OCR). Mirrors `docx_extract.py`'s native-extraction role, but as a fast-path inside `ocr.py` rather than a separate indexer branch, since PDFs still need a thumbnail/Vision |
| `services/docx_extract.py` | Native `.docx` text extraction (`python-docx`, no OCR involved): `extract_docx_text(filepath)` concatenates paragraphs + table cells (`" | "`-joined rows), `"\n\n"`-per-block, mirroring `ocr.py`'s join convention. Headers/footers/footnotes/textboxes are out of scope. Indexer stores the result with `ocr_model="native"` |
| `services/text_extract.py` | Native `.txt` text extraction (no OCR involved — the file already IS the text): `extract_text_file(filepath)` reads the file, decoding UTF-8 (BOM-tolerant) with a latin-1 fallback for legacy-encoded files, and strips surrounding whitespace. `.txt`'s equivalent of `docx_extract.py`; indexer stores the result with `ocr_model="native"` |
| `services/ai_analysis.py` | AI Analysis: produces summary, **title** (short human-readable headline, ≤10 words — distinct from `short_title`'s filename-slug format), document_type (+confidence), tags, language, org, amount via LLM. Type taxonomy comes from `ai_common.DOCUMENT_TYPES_BLOCK` (shared with vision). `coerce_analysis_fields(dict)→AnalysisResult` is the shared field-coercion used by both this module and `ai_vision`. Also exposes `suggest_document_types(...)` → top-3 suggestions for the UI picker. |
| `services/ai_common.py` | Shared AI-provider helpers, de-duplicated from analysis+vision: `strip_code_fences()`, `parse_llm_json()` (tolerates trailing commas + markdown fences — used by batch analysis), `update_provider_stats()`, `SyntheticProvider` (env-var provider stand-in), `DOCUMENT_TYPES_BLOCK` (canonical type taxonomy). |
| `services/ai_vision.py` | AI Vision: sends first document page to vision model. For capable models (OpenAI/Gemini/OpenRouter) uses `VISION_FULL_PROMPT` — returns structured JSON (text + all analysis fields) in one call, so the indexer skips Step 4 entirely. For **Mistral OCR** (`mistral-ocr-latest`, dedicated `/v1/ocr` endpoint, per-page billing) returns plain transcription — Analysis still runs. Public `run_vision(provider, img_bytes, prompt)` + `load_first_page()` reused by the lab. |
| `services/lab.py` | OCR Lab logic: run local/worker OCR, vision-as-transcriber, and premium "judge" comparison on one document's first page. Ephemeral — no document writes. See [lab-mode.md](lab-mode.md) |
| `log_filters.py` | `SuppressNoisyPaths` logging filter (drops `/api/tasks` + `/api/health` from access log); referenced by `log_config.json` |
| `services/embeddings.py` | Embeddings: sentence-transformers (multilingual MiniLM) + ChromaDB; `embed_document()`, `search_similar()`, `search_similar_scored()` (ids + cosine distance, for `/ask` debug), `collection_count()`, `embedded_ids()` (set of embedded doc ids, used by the `embed_missing` task to find gaps) |
| `services/pricing.py` | `estimate_cost(model, tokens_in, tokens_out)` — static per-token price table for all known providers (OpenAI, Gemini, DeepSeek, Mistral, OpenRouter). Returns 0.0 for unknown models. |
| `services/provider_models.py` | `fetch_models(provider_type, api_key, base_url)` — lists available models from a provider's API (used by admin "fetch models" and inline model edit) |
| `services/provider_capabilities.py` | Per-model text/vision/OCR/analysis/batch capability inference plus manual `extra_params.capabilities` overrides |
| `services/indexing_plan.py` | Read-only lazy indexing preview: skips completed analysis, counts routing buckets, freezes candidate ids, and estimates Batch cost |
| `services/arena_ratings.py` | LM Arena leaderboard star ratings: `get_cached(db)` / `refresh_ratings(db)`; cached in DB, surfaced in the AI tab model picker |
| `services/type_icon_suggestion.py` | Suggests Lucide icon names for custom document types via LLM. `suggest_icons_for_types(slugs, db)` → calls AI provider once per type, resolves conflicts (max 5 retries), saves results under AppSettings key `custom_type_icons`. `get_pending_custom_types(db)` returns types in the library that lack a custom icon. Exposed via `GET /api/admin/type-icons` and `POST /api/admin/update-type-icons`. |
| `services/indexer.py` | Pipeline coordinator: OCR → Thumbnail → Vision → Analysis → Embedding. `_is_docx(doc)`/`_run_docx_extract(doc, db)` and `_is_txt(doc)`/`_run_txt_extract(doc, db)` — `.docx`/`.txt` files skip Thumbnail/OCR/Vision entirely and go straight from native text extraction (`docx_extract.py`/`text_extract.py`) to Analysis, setting `ocr_model="native"` + `vision_status="skipped"` (no page image exists to send to Vision). `_is_native_text(doc)` = either of the two; `_extract_native_text(filepath)` dispatches to the right extractor by extension — shared by the batch OCR runners. `_apply_analysis_result(doc, AnalysisResult, db)` is the single helper that writes metadata (incl. `title`) onto a Document, shared by Step 3 (vision-as-analysis) and Step 4. Preserves old `document_type` in tags when type changes during reclassification. `_run_vision()` only lets a capable provider's combined vision+analysis JSON (derived from page 1 only, see `ai_vision.py`) drive Document metadata and skip Step 4 when `doc.ocr_text` is still under `VISION_ANALYSIS_OVERRIDE_MAX_OCR_LEN` (200 chars) — once OCR/native extraction already produced a fuller multi-page text, Step 4 analyzes that instead, so a cover/title page can't overwrite a longer document's summary/tags. Batch ops: `reclassify_pending_batch()` (docs with summary → one LLM call per doc, type-only, no summary/tag regeneration; skips docs without summary); `reclassify_unclassified_batch()` (unclassified/other, skips `manually_classified=True`); `reclassify_document()` (resets manual flag, full re-analysis) |
| `services/recluster.py` | Cluster-based recategorization: clean summaries (strip tags/names/dates) → embed (sentence-transformers) → auto-select k via silhouette score (bounded by `min_clusters`/`max_clusters`) → k-means → LLM names each cluster (type slug + icon + multilingual names, conflict-aware retry) → apply (old type preserved in tags). Entry point: `run_recluster(task_id=None, max_clusters=40, min_clusters=2, provider_id=None)`. Persists `custom_type_icons` + `custom_type_names` (en/fr/ru) to AppSettings. Endpoint: `POST /api/admin/recluster` (fixed defaults). Task type: `recluster` (configurable `min_clusters`/`max_clusters`/`provider_id` via Tasks panel). See [recluster.md](recluster.md). |
| `services/watcher.py` | Folder watcher: watchdog Observer that picks up new files from enabled WatchedFolders and queues indexing |
| `routers/indexing.py` | Indexing control: single doc, batch, reclassify, status, suggest-type (`POST /suggest-type/{id}` → LLM top-3 type suggestions) — prefix `/api/indexing` |
| `routers/lab.py` | OCR Lab endpoints: methods, ocr, vision, judge — prefix `/api/lab`. See [lab-mode.md](lab-mode.md) |
| `services/ai_analysis.py` (helper) | Public `run_text(provider, system, user)` added for the lab judge (text-only mode) |
| `routers/tasks.py` | Task queue endpoints only: CRUD, candidates counts, run/stop/resume-batch/logs/batch-result — prefix `/api/tasks`. Runners live in `services/task_runners.py`. Used by the Tasks panel (advanced mode only). |
| `services/task_runners.py` | Task dispatcher and startup recovery. `index_documents` orchestrates lazy Mistral/local/Gemini routes, reuses existing text, runs metadata-only analysis, and preserves classification. Also owns short maintenance runners. |
| `services/image_compress.py` | `compress_images` task runner: resize on-disk images (jpg/png/tiff/webp) whose long side exceeds a threshold; `count_compress_candidates()` powers the create-form counter |
| `services/task_runtime.py` | Shared helpers for background task runners (`log_task`, `is_stopped`, `set_progress`, `finish`) — each opens its own short-lived session. Imported by `task_runners.py` and the batch runner modules. |
| `services/batch_ocr.py` | Shared batch-OCR helpers: `_scope_filter()` (cumulative re-OCR scope 1-4) and `_needs_vision(doc)` (no OCR text yet → vision; existing text, any engine including local tesseract/easyocr — reused as-is → text-only, cheaper) and `GEMINI_BATCH_BASE`. No runner logic itself — see the two files below. Split out of `tasks.py`. See [batch-ocr.md](batch-ocr.md) |
| `services/batch_ocr_mistral.py` | `run_batch_ocr_mistral()`: submit remote Mistral Batch OCR job → poll → write OCR text back. Imports `_scope_filter` from `batch_ocr.py`. `.docx`/`.txt` documents have no page image — extracted natively (`indexer._extract_native_text()`, `ocr_model="native"`) and excluded from the Mistral JSONL entirely; count surfaced as `result_summary["native"]`. See [batch-ocr.md](batch-ocr.md) |
| `services/batch_ocr_gemini.py` | `run_batch_ocr_gemini()`: submit remote Gemini Batch job → poll → write OCR/analysis fields back, routing each document through `_needs_vision()` (vision vs text-only request). Imports `_needs_vision`/`_scope_filter`/`GEMINI_BATCH_BASE` from `batch_ocr.py`. `.docx`/`.txt` documents are extracted natively first (no page image exists), which makes `_needs_vision()` false so they fall into the existing text-only branch and still get analysis via the same batch job. See [batch-ocr.md](batch-ocr.md) |
| `services/batch_analysis.py` | `run_batch_analysis_gemini()` — text-only analysis via Gemini Batch API. `doc_scope` param selects: `needs_analysis` (default), `unclassified` (for `reclassify_unclassified` task), `pending` (for `reclassify_all` task). Not directly creatable from the Tasks UI — only runs as the engine behind those two reclassify tasks. Saves raw JSONL to `.docintell/batch_results/task_{id}.jsonl`. |
| `services/usage.py` | `record_usage(...)` — appends one row to the `ai_usage` ledger. Called by every model call site (analysis, vision, qa, suggest_types, icon_suggest, batch_*, ocr, embedding). Opens its own session; never raises. See [ai-usage.md](ai-usage.md) |

## Compute (`compute/app/`)

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI OCR worker — `/ocr` (POST) and `/health` (GET); engines detected at startup via `_probe()` subprocess (isolates native DLL crashes from the main process); see [compute-worker.md](compute-worker.md) |

## Frontend (`frontend/src/`)

| Path | Responsibility |
|------|---------------|
| `main.tsx` | React root mount |
| `App.tsx` | Root component: language context + `BrowserRouter` routes (`/` home, `/lab/:id` OCR Lab) |
| `index.css` | Global CSS variables (design tokens), resets, utilities |
| `i18n/en.ts` | English strings (source of `Translations` type) |
| `i18n/ru.ts` | Russian strings |
| `i18n/fr.ts` | French strings |
| `i18n/index.ts` | `Lang` type (`"en" \| "ru" \| "fr"`), `LangContext`, `useT()` hook |
| `types/index.ts` | All TypeScript interfaces (`Document`, `SearchResult`, etc.) |
| `api/client.ts` | Thin `fetch` wrapper (`api.get/post/patch/delete/upload`) |
| `api/documents.ts` | Typed API calls for documents, search, upload, admin |
| `components/layout/Header.tsx` | Top nav: logo, language switcher, dark/light theme toggle (persisted in localStorage), admin gear icon |
| `components/ui/Button.tsx` | Button component (primary/secondary/ghost/danger, sizes) |
| `components/ui/Modal.tsx` | Accessible modal overlay |
| `components/search/SearchBar.tsx` | Search input + mode pills (fulltext/semantic/hybrid/ask) + voice input (Web Speech API, language follows UI lang) + year/language quick-filter chips |
| `components/search/FilterDropdown.tsx` | Reusable filter dropdown used by the search toolbar |
| `components/search/AIAnswer.tsx` | AI Q&A result card: answer text + source document list. In debug mode shows a "Query log" button opening `AskDebugModal` |
| `components/search/AskDebugModal.tsx` | Advanced-mode modal showing the per-request `/ask` retrieval trace (embedded vs total docs, full semantic ranking with weights + sent/retrieved/dropped flags, fulltext hits, the prompt sent to the LLM, timings); copy-to-clipboard. Only the last request is held (in `aiAnswer.debug` state) |
| `components/documents/DocumentCard.tsx` | List row and grid tile rendering. Shows `doc.title \|\| doc.filename` as the document name (falls back to filename until AI analysis produces a title). Renders a per-class type icon (`typeIcons.ts`) at the far right of the list meta row and as a badge on the grid thumbnail. `ProcessingBadge` shows the highest processing tier reached: gray dot (pending) → green/teal dot (local OCR Tesseract/EasyOCR, or `.docx` native extraction, from `ocr_model`) → violet `ScanText` icon (AI text recognition) → gradient `Sparkles` badge (full AI analysis, `analysis_status==="done"`). `Thumbnail` fallback tints the `FileText` icon MS-Word-blue (`.icon-word`) for `.docx` files with no thumbnail (via `typeIcons.ts::isWordDoc`) |
| `components/documents/typeIcons.ts` | Maps each `document_type` slug (AI taxonomy) → a lucide icon; `iconForType()` with keyword + `FileText` fallbacks for free-form types. `setCustomTypeIcons()`/`setCustomTypeNames()` cache the custom-type-icon-suggestion and recluster-generated multilingual names (`custom_type_names` AppSettings key); `labelForType(type, lang)` looks up the display label for a slug, falling back to the raw slug if no name is stored for that language. Also exports `WORD_MIME`/`isWordDoc(mime)` and `TEXT_MIME`/`isTextDoc(mime)` — file-format (not content-type) helpers used by `DocumentCard.tsx`/`DocumentViewer.tsx` to visually flag `.docx`/`.txt` files (both have no visual page) |
| `components/documents/UploadZone.tsx` (+`.css`) | Drag-and-drop upload zone (accepts pdf/jpg/jpeg/png/tiff/tif/heic/heif/webp/docx/txt). Also renders a "paste text" toggle (`t.pasteTextLink`) that swaps in a small form (title + textarea); submitting wraps the text in a `File([...], "<title>.txt", {type:"text/plain"})` and reuses the same upload path — no separate backend endpoint |
| `components/documents/FolderTreeView.tsx` (+`.css`) | Explorer-style folder browser: recursive tree of `FolderTreeNode` (yellow folder icons, expand/collapse, all folders visible/collapsed on load), rendering each folder's direct documents via `DocumentCard` in the current `viewMode` (list/grid) once expanded |
| `components/documents/DocumentViewer.tsx` | Document detail modal **shell**: canvas/zoom/pan/crop, tab switcher (preview/text/dev), keyboard shortcuts. Modal title shows `doc.title \|\| doc.filename`. Main preview area: PDF → iframe; `.docx` (via `isWordDoc`) with `ocr_text` → scrollable `.viewer-text-preview` showing the extracted text (no visual page exists); image → zoom/pan canvas; otherwise → `FileText` placeholder (tinted `.icon-word` blue for `.docx`). Tab bodies live in `MetadataTab.tsx`/`TextTab.tsx`/`DevTab.tsx`. Footer `Delete` button (`handleDelete`) confirms via `window.confirm`, calls `DELETE /api/documents/{id}`, then closes the viewer and dispatches `docintell:library-changed` to refresh the list |
| `components/documents/MetadataTab.tsx` | Preview tab: type badge (renders `TypePicker`), tags (chips + `TagInput` to add one), language/org/person/date/amount, path/filename/added/size |
| `components/documents/TagInput.tsx` | Inline "add tag" control on `MetadataTab`: lazy-fetches `GET /api/documents/tags` (all distinct tags in the library) on first open, shows matching existing tags as clickable suggestions to keep the taxonomy consistent, or accepts a free-form new tag |
| `components/documents/TextTab.tsx` | Text tab: AI Vision description (if any) + OCR text |
| `components/documents/DevTab.tsx` | Dev tab: pipeline status dots (OCR/Vision/Analysis/Embedding), model attribution, costs, Reindex/Reclassify actions |
| `components/documents/TypePicker.tsx` | Inline type picker on the type badge: fetches LLM suggestions on click, lets user pick from top-3 or enter a free-form type (+ `formatTypeName`) |
| `components/admin/AdminPanel.tsx` | Admin modal **shell**: sidebar tabs, renders one tab component |
| `components/admin/tabs/IndexingTab.tsx` | Stats grid + Sync / Batch / Re-classify / "Classify unclassified" buttons (incl. `StatCard`). Shows `unclassified` count as a danger card, the resolved `library_path`, and the last sync's added/removed counts. |
| `components/admin/tabs/SourcesTab.tsx` | Watched-folder list: add / remove / toggle |
| `components/admin/tabs/AITab.tsx` | **Shell** for the AI tab: Vision toggle, Update Ratings, three `ProviderSection`s (Analysis / Vision / Premium-Judge). Sub-components live in `tabs/ai/` |
| `components/admin/tabs/ai/aiUtils.ts` | Constants + formatters (`fmtTokens`, `blendedPrice`, …) + `lookupModelRating` + add-form name helpers |
| `components/admin/tabs/ai/ModelPicker.tsx` | Searchable/sortable model list with ratings & pricing |
| `components/admin/tabs/ai/RatingStars.tsx` | Star display for a model's arena rating |
| `components/admin/tabs/ai/AddProviderForm.tsx` | Add-provider form: pick type/key, fetch models, save |
| `components/admin/tabs/ai/ProviderRow.tsx` | One provider row: reorder, inline model edit, settings, toggle, delete |
| `components/admin/tabs/ai/ProviderSettingsPanel.tsx` | Per-provider fine-tuning (Mistral image policy; temperature/max_tokens for chat) |
| `components/admin/tabs/ai/ProviderSection.tsx` | Section wrapper: provider list + add form for one task type |
| `components/admin/tabs/LogTab.tsx` | Recent indexing log entries with a minimum-severity filter (`trace`→`error`) over each row's `level` |
| `components/admin/tabs/BackupTab.tsx` | DB backups list + restore + retention count (`backup_keep`, editable). **Advanced-mode-only** tab (gated in `AdminPanel.tsx`) |
| `components/admin/tabs/UsageTab.tsx` (+`.css`) | Super-user AI usage screen (**advanced-mode-only** tab): summary cards, CSS bar charts (by type/provider/model/day), configurable row×col×metric pivot table, recent-calls list, clear. Reads `/api/admin/usage*`. See [ai-usage.md](ai-usage.md) |
| `components/admin/tabs/AITab.tsx` (export/import) | Header has Export/Import buttons → download/upload full provider config JSON (incl. API keys) via `/admin/providers/export\|import` |
| `public/icon.svg` | App icon — used as the browser favicon (`index.html`) and the header logo mark (`Header.tsx`) |
| `components/ui/IndexingBadge.tsx` | Header badge showing pending OCR count (live polls `/api/indexing/status`) |
| `components/ui/KeyboardHelp.tsx` | Keyboard shortcuts modal (triggered by `?`) |
| `hooks/useKeyboard.ts` | Keyboard shortcut binding hook (ignores input focus) |
| `hooks/useImageEdit.ts` | Image transform state for DocumentViewer: fetch image info, preview/apply rotate-crop-deskew via the lab transform endpoints |
| `hooks/useSearchHistory.ts` | Recent-queries history per mode (`search`/`ask`), persisted in localStorage (`docintell:search_history:*`, max configurable via `docintell:prefs:search_history_max`) |
| `components/documents/imgSrc.ts` | `resolveImgSrc()`: prefer a transform-preview base64 image over the raw thumbnail/file URL |
| `contexts/AdvancedModeContext.tsx` | Boolean context for "advanced user mode" — persisted in localStorage; enables OCR Tuning button and Tasks panel |
| `components/tasks/TasksPanel.tsx` | Task management panel (advanced mode only) **orchestrator**: state, polling, drag-reorder; renders `TaskCard`/`CreateTaskModal`/`TaskLogsModal`/`BatchMonitorModal`/`TasksEmpty` |
| `components/tasks/taskConfig.ts` | Task-type constants shared by the panel: labels, per-type config (limit/scope/provider/doc-URL), `formatDuration()` |
| `components/tasks/TaskCard.tsx` | One task's grid card: status/progress/result, drag handle, run/stop/delete/logs actions |
| `components/tasks/CreateTaskModal.tsx` | Create-task form: type picker, per-type config fields (limit/scope/recluster clusters/batch provider+poll interval/compress threshold) |
| `components/tasks/TaskLogsModal.tsx` | Task log viewer with live polling while running |
| `components/tasks/BatchMonitorModal.tsx` | Batch-task-specific monitor: job ID, resume, result download |
| `components/tasks/TasksEmpty.tsx` | Empty state for the tasks grid |
| `components/tasks/TasksPanel.css` | Styles for task cards, badges, progress bars, create form, logs modal |
| `pages/HomePage.tsx` | Main page **orchestrator**: search/AI-ask state, effects, keyboard shortcuts (`1`/`2`/`3` = list/grid/folders), layout; renders `home/HomePageToolbar.tsx`/`HomePageAIMode.tsx`/`HomePageResults.tsx`/`HomePageFolderResults.tsx`. Owns a separate viewer + flattened-doc-list (`flatTreeDocs`, DFS order) for prev/next navigation inside the folder browser — opening a tree doc re-fetches the full `Document` via `GET /documents/{id}` since the tree payload omits `ocr_text`/`vision_description` |
| `pages/home/HomePageToolbar.tsx` | Result count, directory/category filter chips, quality filter + dispatch, sync/upload buttons, view-mode toggle (list/grid/**folders** — the folders button sets `layoutMode="folders"` independent of the list/grid `viewMode`, which keeps driving card style inside the folder tree too) |
| `pages/home/HomePageAIMode.tsx` | AI ask mode content: progress steps, `AIAnswer`, or the ask-mode hint |
| `pages/home/HomePageResults.tsx` | Regular (flat) search results: loading skeleton, empty state, or the list/grid of `DocumentCard`s. Shown when `layoutMode === "flat"` |
| `pages/home/HomePageFolderResults.tsx` | Folder-browse results: loading skeleton / empty state / `FolderTreeView`. Shown when `layoutMode === "folders"`; tree comes from `GET /api/documents/tree`, fetched once and refetched on `docintell:library-changed` |
| `pages/LabPage.tsx` | OCR Lab screen (`/lab/:id`) **orchestrator**: document viewer (zoom/pan/crop/transform) + OCR/vision/judge handlers. Presentational pieces live in `pages/lab/`. See [lab-mode.md](lab-mode.md) |
| `pages/lab/labUtils.ts` | `formatMs`, `formatFileSize`, `uid`, `VISION_CAPABLE` |
| `pages/lab/useImageTransform.ts` | Zoom + pan for the lab image canvas: wheel-zoom at cursor, button zoom, fit-on-load, drag-to-pan. Owns its wheel/pan listeners; exposes `zoomRef` for the page's crop overlay. Extracted from `LabPage.tsx`. |
| `pages/lab/useLogs.ts` | Activity-log hook (append + auto-scroll) for the panel |
| `pages/lab/usePanelResize.ts` | Draggable right-panel width hook (persists to localStorage) |
| `pages/lab/FieldChips.tsx` | Chips summarising extracted structured fields |
| `pages/lab/ResultsList.tsx` | List of OCR/vision results with save/expand/remove |
| `pages/lab/JudgePanel.tsx` | Premium "judge" section: pick providers, compare, verdicts |
| `pages/lab/FloatingTextModal.tsx` | Draggable floating modal showing one result's full text |

## Deployment (k3s + ArgoCD + GHCR)

Platform contract lives in [excluded-from-analysis/k3s-platform-deployment.md](excluded-from-analysis/k3s-platform-deployment.md) (**read-only spec — don't read/edit during normal dev**). GitOps: push to `main` → GitHub Actions builds images → GHCR → bumps Helm tags → force-pushes `deploy` branch → ArgoCD syncs.

| File | Responsibility |
|------|---------------|
| `backend/Dockerfile` | Backend image: Python + Tesseract(rus+fra+eng) + poppler + libmagic. Context = repo root. CMD passes `--log-config /app/log_config.json` |
| `backend/log_config.json` | Uvicorn logging config for k8s: `HH:MM:SS.mmm` timestamps, `huggingface_hub` suppressed to ERROR, noisy-path filter for access log |
| `backend/backup.py` | DB-backup sidecar: every 5 min (if DB changed) writes a consistent `sqlite3.backup()` copy to the NAS root, rotating the N newest (`docintell.db.backup.1/.2/...`) — N is read live from `AppSettings.backup_keep` each run, falling back to `BACKUP_KEEP` env var |
| `frontend/Dockerfile` | Frontend image: Vite build → nginx static. Context = repo root |
| `frontend/nginx.conf` | nginx SPA history fallback (`/api`,`/thumbnails` routed by ingress, not here) |
| `.dockerignore` | Excludes node_modules, `library/`, DBs, caches from build contexts |
| `.github/workflows/build.yml` | CI: build backend+frontend → GHCR (tag=sha) → `yq` bump `values.yaml` → force-push `deploy` |
| `deploy/argocd/application.yaml` | ArgoCD Application; tracks `deploy` branch, namespace `my-documents-archive` |
| `deploy/helm/my-documents-archive/values.yaml` | Only file CI mutates (`image.*.tag`). NAS source, storage sizes, `stripApiPrefix: false`, `ingress.host` (nip.io), `ingress.tls`, `ingress.certIssuer` |
| `deploy/helm/.../templates/backend-deployment.yaml` | Backend: `Recreate`, single replica. Nested mounts: SMB NAS at `/data/library`, local-path PVC overlays `/data/library/.docintell` (keeps SQLite/Chroma off CIFS) |
| `deploy/helm/.../templates/smb-nas.yaml` | SMB CSI PV+PVC for the NAS document library (`//192.168.1.91/Data/my-documents-archive`) |
| `deploy/helm/.../templates/state-pvc.yaml` | local-path PVC for derived state (DB, Chroma, thumbnails, HF cache) |
| `deploy/helm/.../templates/ingress.yaml` | Traefik ingress: `/api`+`/thumbnails`→backend (no strip), `/`→frontend. Optional TLS via cert-manager (controlled by `ingress.tls`) |
| `deploy/helm/.../templates/{frontend-deployment,*-service,_helpers}.yaml` | Frontend Deployment, Services, name/label/image helpers |
| `deploy/k8s/cert-manager/home-ca.yaml` | One-time cluster resource: creates a local CA (10-year self-signed root) and exposes it as `ClusterIssuer: home-ca`. Apply manually before pushing TLS-enabled Helm values. Export CA cert and install on devices once. |

**Human-only steps** (cluster access; see [deployment.md](deployment.md)): first build to populate GHCR → make packages public → install SMB CSI driver → create `my-documents-archive-smb-creds` secret → `kubectl apply` the ArgoCD Application → install cert-manager + apply `home-ca.yaml` → install `home-ca.crt` on devices. Access via `my-documents-archive.192.168.1.97.nip.io` (no router/hosts config needed). Backfill existing NAS docs via **Admin → Sync**.

## Key Data Flow

```
User uploads file
  → POST /api/upload
  → storage.save_uploaded_file() → library/YYYY/MM/filename
  → Document row inserted (ocr_status=pending, analysis_status=pending)
  → thumbnails.generate_thumbnail() [synchronous, before response]
  → BackgroundTasks: indexer.index_document(doc_id)
      → .docx: services/docx_extract.py — native text (no OCR/Vision/Thumbnail) → straight to Analysis
      → .txt: services/text_extract.py — native text (no OCR/Vision/Thumbnail) → straight to Analysis
      → PDF: services/ocr.py → services/pdf_extract.py first (embedded text layer, no OCR);
        falls back to Tesseract/external worker (all pages) only if no usable text layer
      → scans/images: services/ocr.py: Tesseract or external worker
      → services/ai_vision.py (if enabled): capable model returns text + all analysis
        fields in one JSON → indexer applies them and SKIPS analysis below
      → services/ai_analysis.py: OpenAI/Gemini/DeepSeek/... → summary, title, tags, type, lang, org, amount
        (skipped when vision already produced structured fields)
      → Document updated (analysis_status=done or skipped if no provider)

User searches
  → GET /api/search?query=…&mode=fulltext
  → routers/search.py: SQLite LIKE over ocr_text+filename+summary
  → SearchResponse with highlight snippets

Admin sync
  → POST /api/admin/sync
  → storage.check_library_accessible()  ── 503 abort if disk offline (no deletes)
  → hard-delete docs whose file is missing or inside .docintell (+ their thumbnails)
  → storage.scan_library_for_new_files()  (skips .docintell + hidden dirs)
  → new Document rows inserted (source="sync", date via infer_document_date())
  → BackgroundTasks: index_document() for each new file
  → SyncResponse {found, new_files, removed}

Admin reclassify-all (type-only, cheap)
  → POST /api/admin/reclassify-all
  → BackgroundTasks: indexer.reclassify_pending_batch()
      → filter: summary IS NOT NULL (docs without summary are logged + skipped)
      → one LLM call per doc: existing summary → document_type only
      → old document_type preserved in tags if it changed
      → does NOT touch summary, tags, language, or other fields

Admin reclassify-unclassified (full re-analysis for unclassified only)
  → POST /api/admin/reclassify-unclassified
  → BackgroundTasks: indexer.reclassify_unclassified_batch()
      → filter: document_type in (unclassified, other, NULL) AND manually_classified=False
      → full _run_analysis() call per doc

Admin recluster (cluster-based taxonomy reset)
  → POST /api/admin/recluster
  → BackgroundTasks: recluster.run_recluster()
      → embed all summaries locally → auto-select k via silhouette → k-means
      → LLM names each cluster (type slug + icon)
      → old document_type preserved in tags
```

## Database Location

`library/.docintell/docintell.db` — stays with documents, backed up together.

## Advanced User Mode

Enabled via the **Zap** (⚡) button in the header (persisted to localStorage). When active:
- **OCR Tuning** button appears in DocumentViewer (navigates to `/lab/:id`)
- **Tasks** button appears in the header → opens `TasksPanel`
- **Backup** tab appears in the Admin panel → list/restore DB backups (`BackupTab`)
- **AI Usage** tab appears in the Admin panel → super-user stats/charts/pivot over the `ai_usage` ledger (`UsageTab`)

The super-user screen is gated by Advanced Mode (no separate auth) — same trust model as Backup.

`TasksPanel` shows processing jobs as draggable cards (3-column grid). Task types:
| Type | Description |
|------|-------------|
| `index_unindexed` | OCR + AI analysis for pending documents |
| `sync_library` | Scan library + index new files |
| `reclassify_unclassified` | AI classification for unclassified docs |
| `reclassify_all` | Type-only classification for docs that already have a summary (one LLM call per doc, no summary/tag regeneration) |
| `recluster` | Cluster-based recategorization of all analyzed docs (silhouette k-selection + LLM naming) |
| `embed_missing` | Backfill ChromaDB vectors for analyzed docs missing embeddings (`force=true` re-embeds all) |
| `fix_quality` | Fix one quality gap (`no_ocr`/`no_embedding`/`no_analysis`/`no_summary`/`no_tags`/`no_category`); analysis gaps are delegated to Gemini Batch Analysis |
| `batch_ocr_mistral` | Async batch OCR via Mistral Batch API (50% cheaper) — see [batch-ocr.md](batch-ocr.md) |
| `batch_ocr_gemini` | Async batch OCR + analysis via Gemini Batch Mode (50% cheaper); per-document hybrid — sends the image only if no OCR text exists yet, otherwise text-only (existing text is reused as-is, even from local tesseract/easyocr) — see [batch-ocr.md](batch-ocr.md) |
| `batch_analysis_gemini` | Text-only analysis via Gemini Batch API; also the engine behind the two reclassify tasks (see `services/batch_analysis.py`) |
| `cleanup_missing` | Soft-delete DB rows whose file no longer exists on disk |
| `compress_images` | Resize on-disk images whose long side exceeds a threshold (`services/image_compress.py`) |

Tasks run as FastAPI `BackgroundTasks`, write logs to `task_logs` table, and support soft-stop via a `status="stopped"` flag. The two `batch_ocr_*` tasks are long-running pollers: they submit a remote batch job, then poll every `poll_interval` seconds until the provider finishes (up to 24–48 h).

## Planned (not yet implemented)

- Celery/Redis task queue — replaced by FastAPI BackgroundTasks (sufficient for personal app). `config.redis_url` is dead legacy config; nothing reads it.

## Gotchas (save a grep)

- **App settings**: `/api/admin/settings` accepts any key, but the only key the backend actually reads is `enable_ai_vision` (in `services/indexer.py`). `enable_ai_analysis`, `ai_analysis_model`, `ai_vision_model` in `config.py` are env fallbacks, not DB-backed settings.
- **AI providers live in the DB** (`AIProvider` rows, added via Admin UI), not in env. The `*_api_key` fields in `config.py` are only fallback overrides.
- **Tests**: `npm test` from repo root runs all three suites (backend/compute pytest, frontend vitest). See [testing.md](testing.md). Test files live in `backend/tests/`, `compute/tests/`, and `frontend/src/**/*.test.ts`.
- **Compute worker native crash (Windows+conda)**: On miniforge/miniconda, `import easyocr` → `from skimage import io` triggers an OpenBLAS vs MKL DLL conflict when torch (MKL-linked) is already loaded. Exit code `3228369023` (STATUS_ACCESS_VIOLATION), NOT catchable by `except Exception`. Fix: `pip install numpy scipy scikit-image --force-reinstall`. The worker uses `_probe()` (subprocess) at startup to survive this crash in the probe itself. See [compute-worker.md](compute-worker.md).
- **Classification fields**: `Document` has three classification-tracking columns: `classification_confidence` (float, LLM self-reported), `classification_source` (`"auto"`/`"manual"`), `manually_classified` (bool). `reclassify_unclassified_batch()` skips `manually_classified=True` docs. `reclassify_pending_batch()` (Re-classify All) and `reclassify_document()` do not — they always override. Old type is preserved in tags when type changes.
- **Three reclassification modes differ in scope and cost**: `reclassify_pending_batch` (Re-classify All) = one cheap type-only LLM call per doc with summary; `reclassify_unclassified_batch` = full analysis only for unclassified docs; `run_recluster` = local clustering + one LLM call per cluster to name it.
- **`unclassified` vs `other`**: the LLM prompt no longer outputs `"other"` — it outputs `"unclassified"`. Old documents may still have `"other"`; all batch jobs and stats queries treat them identically.
- **Vision can replace Analysis**: for capable providers (OpenAI/Gemini/OpenRouter) Step 3 uses `VISION_FULL_PROMPT` and returns the transcription **plus** every analysis field as one JSON. `indexer._apply_vision_fields()` writes them and sets `analysis_status="done"`, so Step 4 never runs — one API call instead of two. Only **Mistral OCR** (plain transcription) still triggers a separate Analysis step. This short-circuit only fires when `doc.ocr_text` is still short (see the `VISION_ANALYSIS_OVERRIDE_MAX_OCR_LEN` gotcha below).
- **Vision — and both async batch-OCR paths — only ever see page 1**: `ai_vision.py::load_first_page()`/`_pdf_first_page()` hardcode `first_page=1, last_page=1`, and `batch_ocr_mistral.py`/`batch_ocr_gemini.py` reuse the same `load_first_page()`. If a multi-page PDF's first page is a cover/title, any vision-derived transcription or analysis reflects only that page — the local OCR/native-extraction path (`ocr.py`) is the one that covers the full document. `indexer._run_vision()` accounts for this (see `VISION_ANALYSIS_OVERRIDE_MAX_OCR_LEN`), but the two batch-OCR runners do not.
- **Sync is now hard-delete**: `/api/admin/sync` `db.delete()`s missing/phantom docs (the old `is_deleted` soft-delete is migrated away — sync also purges any leftover `is_deleted=True` rows). It refuses to run (HTTP 503) if `check_library_accessible()` fails, so an unmounted NAS can't empty the library.
- **User-initiated document delete is also hard-delete**: `DELETE /api/documents/{id}` removes the file on disk, `thumbnail_path`, the ChromaDB vector (`services/embeddings.py::delete_document`), and the row — not just `is_deleted=true`. Sync's own hard-delete path (missing/phantom files) does **not** clean up the embedding, so a doc removed by deleting its file outside the app (then swept by sync) can leave an orphan vector in Chroma; not an issue for the in-app Delete button.
- **Log levels**: every `IndexingLog` row has `level` (`trace|debug|info|warning|error`). The `_log()` helpers default to `info`; pass `level=` to override. The Admin Log tab filters by minimum severity client-side.
