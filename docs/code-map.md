# Code Map — DocIntel

Quick index for LLM navigation. Check this file before grepping.

## Directory Tree

```
backend/          FastAPI Python backend (main app)
compute/          External OCR microservice (optional, runs on separate machine)
frontend/         React + Vite + TypeScript UI
docs/             Architecture docs (you are here)
```

## Backend (`backend/app/`)

| File | Responsibility |
|------|---------------|
| `run.py` | Dev entry point (`python run.py` → uvicorn on :8000) |
| `main.py` | FastAPI app factory, CORS, startup hooks, thumbnail static mount |
| `config.py` | All settings (pydantic-settings); `settings` singleton |
| `database.py` | SQLAlchemy engine, `SessionLocal`, `get_db()`, `init_db()` |
| `models.py` | ORM models: `Document`, `WatchedFolder`, `IndexingLog`, `AIProvider`, `AppSettings` |
| `schemas.py` | Pydantic request/response schemas for all endpoints |
| `routers/documents.py` | CRUD: list, get, delete, patch tags, patch type (`PATCH /{id}/type` sets type + `manually_classified=true`) — prefix `/api/documents` |
| `routers/upload.py` | File upload endpoint — prefix `/api/upload` |
| `routers/search.py` | Full-text + semantic search — prefix `/api/search`. `GET /` fulltext/semantic/hybrid; `GET /ask` AI Q&A (semantic retrieval → AI provider → answer + sources). Fulltext searches filename, ocr_text, summary, document_type, tags, person, organization. |
| `routers/admin.py` | **Aggregator** — mounts the four `admin_*` sub-routers under prefix `/api/admin`. Start here, then jump to the right sub-router below |
| `routers/admin_library.py` | Stats, sync, batch-index, reclassify-all/unclassified, log (+ `_log` helper) |
| `routers/admin_folders.py` | Watched-folder CRUD: list / add / remove / toggle |
| `routers/admin_providers.py` | AI providers CRUD, model listing (`/models`), arena ratings (`/arena-ratings`) |
| `routers/admin_settings.py` | App settings key-value get/upsert (`/settings`) |
| `services/storage.py` | File hashing, MIME detection, library scanning, saving uploads to `YYYY/MM/` |
| `services/thumbnails.py` | Generate JPEG thumbnails (Pillow + pdf2image) |
| `services/ocr.py` | OCR extraction: local Tesseract or external worker (fallback chain) |
| `services/ai_analysis.py` | AI Analysis: produces summary, document_type (+confidence), tags, language, org, amount via LLM. Type taxonomy: 30+ slugs (`passport`, `birth_certificate`, `contract`, `invoice`, `diploma`, … `unclassified`). Also exposes `suggest_document_types(summary, ocr_text, existing_types, db)` → top-3 suggestions for the UI picker. |
| `services/ai_vision.py` | AI Vision: sends first document page to vision model; returns description text; supports Anthropic/OpenAI/Gemini/OpenRouter + **Mistral OCR** (`mistral-ocr-latest`, dedicated `/v1/ocr` endpoint, per-page billing, returns verbatim transcription). Public `run_vision(provider, img_bytes, prompt)` + `load_first_page()` reused by the lab. Mistral also supports text models (OpenAI-compat) for analysis. |
| `services/lab.py` | OCR Lab logic: run local/worker OCR, vision-as-transcriber, and premium "judge" comparison on one document's first page. Ephemeral — no document writes. See [lab-mode.md](lab-mode.md) |
| `services/embeddings.py` | Embeddings: sentence-transformers (multilingual MiniLM) + ChromaDB; `embed_document()`, `search_similar()`, `collection_count()` |
| `services/provider_models.py` | `fetch_models(provider_type, api_key, base_url)` — lists available models from a provider's API (used by admin "fetch models" and inline model edit) |
| `services/arena_ratings.py` | LM Arena leaderboard star ratings: `get_cached(db)` / `refresh_ratings(db)`; cached in DB, surfaced in the AI tab model picker |
| `services/indexer.py` | Pipeline coordinator: OCR → Thumbnail → Vision → Analysis → Embedding; `reclassify_pending_batch()` (unanalyzed docs); `reclassify_unclassified_batch()` (unclassified/other, skips `manually_classified=True`); `reclassify_document()` (resets manual flag) |
| `services/watcher.py` | Folder watcher: watchdog Observer that picks up new files from enabled WatchedFolders and queues indexing |
| `routers/indexing.py` | Indexing control: single doc, batch, reclassify, status, suggest-type (`POST /suggest-type/{id}` → LLM top-3 type suggestions) — prefix `/api/indexing` |
| `routers/lab.py` | OCR Lab endpoints: methods, ocr, vision, judge — prefix `/api/lab`. See [lab-mode.md](lab-mode.md) |
| `services/ai_analysis.py` (helper) | Public `run_text(provider, system, user)` added for the lab judge (text-only mode) |
| `routers/tasks.py` | Task queue CRUD + run/stop/logs — prefix `/api/tasks`. Used by the Tasks panel (advanced mode only). |

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
| `components/search/AIAnswer.tsx` | AI Q&A result card: answer text + source document list |
| `components/documents/DocumentCard.tsx` | List row and grid tile rendering |
| `components/documents/UploadZone.tsx` | Drag-and-drop upload zone |
| `components/documents/DocumentViewer.tsx` | Document detail modal (tabs: preview/text/details/dev). Type badge renders `TypePicker` |
| `components/documents/TypePicker.tsx` | Inline type picker on the type badge: fetches LLM suggestions on click, lets user pick from top-3 or enter a free-form type (+ `formatTypeName`) |
| `components/admin/AdminPanel.tsx` | Admin modal **shell**: sidebar tabs, renders one tab component |
| `components/admin/tabs/IndexingTab.tsx` | Stats grid + Sync / Batch / Re-classify / "Classify unclassified" buttons (incl. `StatCard`). Shows `unclassified` count as a danger card. |
| `components/admin/tabs/SourcesTab.tsx` | Watched-folder list: add / remove / toggle |
| `components/admin/tabs/AITab.tsx` | **Shell** for the AI tab: Vision toggle, Update Ratings, three `ProviderSection`s (Analysis / Vision / Premium-Judge). Sub-components live in `tabs/ai/` |
| `components/admin/tabs/ai/aiUtils.ts` | Constants + formatters (`fmtTokens`, `blendedPrice`, …) + `lookupModelRating` + add-form name helpers |
| `components/admin/tabs/ai/ModelPicker.tsx` | Searchable/sortable model list with ratings & pricing |
| `components/admin/tabs/ai/RatingStars.tsx` | Star display for a model's arena rating |
| `components/admin/tabs/ai/AddProviderForm.tsx` | Add-provider form: pick type/key, fetch models, save |
| `components/admin/tabs/ai/ProviderRow.tsx` | One provider row: reorder, inline model edit, settings, toggle, delete |
| `components/admin/tabs/ai/ProviderSettingsPanel.tsx` | Per-provider fine-tuning (Mistral image policy; temperature/max_tokens for chat) |
| `components/admin/tabs/ai/ProviderSection.tsx` | Section wrapper: provider list + add form for one task type |
| `components/admin/tabs/LogTab.tsx` | Recent indexing log entries |
| `components/ui/IndexingBadge.tsx` | Header badge showing pending OCR count (live polls `/api/indexing/status`) |
| `components/ui/KeyboardHelp.tsx` | Keyboard shortcuts modal (triggered by `?`) |
| `hooks/useKeyboard.ts` | Keyboard shortcut binding hook (ignores input focus) |
| `contexts/AdvancedModeContext.tsx` | Boolean context for "advanced user mode" — persisted in localStorage; enables OCR Tuning button and Tasks panel |
| `components/tasks/TasksPanel.tsx` | Task management panel (advanced mode only): block grid, drag-reorder, run/stop, logs modal |
| `components/tasks/TasksPanel.css` | Styles for task cards, badges, progress bars, create form, logs modal |
| `pages/HomePage.tsx` | Main page: hero search, toolbar, document grid/list |
| `pages/LabPage.tsx` | OCR Lab screen (`/lab/:id`) **orchestrator**: document viewer (zoom/pan/crop/transform) + OCR/vision/judge handlers. Presentational pieces live in `pages/lab/`. See [lab-mode.md](lab-mode.md) |
| `pages/lab/labUtils.ts` | `formatMs`, `formatFileSize`, `uid`, `VISION_CAPABLE` |
| `pages/lab/useLogs.ts` | Activity-log hook (append + auto-scroll) for the panel |
| `pages/lab/usePanelResize.ts` | Draggable right-panel width hook (persists to localStorage) |
| `pages/lab/FieldChips.tsx` | Chips summarising extracted structured fields |
| `pages/lab/ResultsList.tsx` | List of OCR/vision results with save/expand/remove |
| `pages/lab/JudgePanel.tsx` | Premium "judge" section: pick providers, compare, verdicts |
| `pages/lab/FloatingTextModal.tsx` | Draggable floating modal showing one result's full text |

## Key Data Flow

```
User uploads file
  → POST /api/upload
  → storage.save_uploaded_file() → library/YYYY/MM/filename
  → Document row inserted (ocr_status=pending, analysis_status=pending)
  → thumbnails.generate_thumbnail() [synchronous, before response]
  → BackgroundTasks: indexer.index_document(doc_id)
      → services/ocr.py: Tesseract or external worker
      → services/ai_analysis.py: Anthropic/OpenAI/Gemini/... → summary, tags, type, lang, org, amount
      → Document updated (analysis_status=done or skipped if no provider)

User searches
  → GET /api/search?query=…&mode=fulltext
  → routers/search.py: SQLite LIKE over ocr_text+filename+summary
  → SearchResponse with highlight snippets

Admin sync
  → POST /api/admin/sync
  → storage.scan_library_for_new_files()
  → new Document rows inserted
  → BackgroundTasks: index_document() for each new file

Admin reclassify
  → POST /api/admin/reclassify-all
  → BackgroundTasks: indexer.reclassify_pending_batch()
      → re-runs _run_analysis() for docs with ocr_status=done, analysis_status≠done
```

## Database Location

`library/.docintell/docintell.db` — stays with documents, backed up together.

## Advanced User Mode

Enabled via the **Zap** (⚡) button in the header (persisted to localStorage). When active:
- **OCR Tuning** button appears in DocumentViewer (navigates to `/lab/:id`)
- **Tasks** button appears in the header → opens `TasksPanel`

`TasksPanel` shows processing jobs as draggable cards (3-column grid). Task types:
| Type | Description |
|------|-------------|
| `index_unindexed` | OCR + AI analysis for pending documents |
| `sync_library` | Scan library + index new files |
| `reclassify_unclassified` | AI classification for unclassified docs |
| `reclassify_all` | Re-run AI analysis on all docs |
| `batch_ocr_mistral` | Placeholder — Mistral batch OCR (coming) |

Tasks run as FastAPI `BackgroundTasks`, write logs to `task_logs` table, and support soft-stop via a `status="stopped"` flag.

## Planned (not yet implemented)

- Celery/Redis task queue — replaced by FastAPI BackgroundTasks (sufficient for personal app). `config.redis_url` is dead legacy config; nothing reads it.

## Gotchas (save a grep)

- **App settings**: `/api/admin/settings` accepts any key, but the only key the backend actually reads is `enable_ai_vision` (in `services/indexer.py`). `enable_ai_analysis`, `ai_analysis_model`, `ai_vision_model` in `config.py` are env fallbacks, not DB-backed settings.
- **AI providers live in the DB** (`AIProvider` rows, added via Admin UI), not in env. The `*_api_key` fields in `config.py` are only fallback overrides.
- **Tests**: `npm test` from repo root runs all three suites (backend/compute pytest, frontend vitest). See [testing.md](testing.md). Test files live in `backend/tests/`, `compute/tests/`, and `frontend/src/**/*.test.ts`.
- **Compute worker native crash (Windows+conda)**: On miniforge/miniconda, `import easyocr` → `from skimage import io` triggers an OpenBLAS vs MKL DLL conflict when torch (MKL-linked) is already loaded. Exit code `3228369023` (STATUS_ACCESS_VIOLATION), NOT catchable by `except Exception`. Fix: `pip install numpy scipy scikit-image --force-reinstall`. The worker uses `_probe()` (subprocess) at startup to survive this crash in the probe itself. See [compute-worker.md](compute-worker.md).
- **Classification fields**: `Document` has three classification-tracking columns added in Phase 9: `classification_confidence` (float, LLM self-reported), `classification_source` (`"auto"`/`"manual"`), `manually_classified` (bool). Docs with `manually_classified=True` are skipped by `reclassify_unclassified_batch()` but are re-classified if the user explicitly clicks "Re-classify" in dev mode (`reclassify_document()` resets the flag).
- **`unclassified` vs `other`**: the LLM prompt no longer outputs `"other"` — it outputs `"unclassified"`. Old documents may still have `"other"`; all batch jobs and stats queries treat them identically.
