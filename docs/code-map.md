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
| `routers/documents.py` | CRUD: list, get, delete, patch tags — prefix `/api/documents` |
| `routers/upload.py` | File upload endpoint — prefix `/api/upload` |
| `routers/search.py` | Full-text search with SQLite LIKE — prefix `/api/search` |
| `routers/admin.py` | Stats, sync, watched folders, AI providers, log — prefix `/api/admin` |
| `services/storage.py` | File hashing, MIME detection, library scanning, saving uploads to `YYYY/MM/` |
| `services/thumbnails.py` | Generate JPEG thumbnails (Pillow + pdf2image) |
| `services/ocr.py` | OCR extraction: local Tesseract or external worker (fallback chain) |
| `services/ai_analysis.py` | AI Analysis: calls Anthropic/OpenAI/Gemini/DeepSeek/OpenRouter to produce summary, tags, document_type, language, organization, amount |
| `services/ai_vision.py` | AI Vision: sends first document page to vision model; returns description text; supports Anthropic/OpenAI/Gemini/OpenRouter + **Mistral OCR** (`mistral-ocr-latest`, dedicated `/v1/ocr` endpoint, per-page billing, returns verbatim transcription). Public `run_vision(provider, img_bytes, prompt)` + `load_first_page()` reused by the lab. Mistral also supports text models (OpenAI-compat) for analysis. |
| `services/lab.py` | OCR Lab logic: run local/worker OCR, vision-as-transcriber, and premium "judge" comparison on one document's first page. Ephemeral — no document writes. See [lab-mode.md](lab-mode.md) |
| `services/embeddings.py` | Embeddings: sentence-transformers (multilingual MiniLM) + ChromaDB; `embed_document()`, `search_similar()`, `collection_count()` |
| `services/indexer.py` | Pipeline coordinator: OCR → Thumbnail → Vision → Analysis → Embedding; batch, reclassify |
| `services/watcher.py` | Folder watcher: watchdog Observer that picks up new files from enabled WatchedFolders and queues indexing |
| `routers/indexing.py` | Indexing control: single doc, batch, reclassify, status — prefix `/api/indexing` |
| `routers/lab.py` | OCR Lab endpoints: methods, ocr, vision, judge — prefix `/api/lab`. See [lab-mode.md](lab-mode.md) |
| `services/ai_analysis.py` (helper) | Public `run_text(provider, system, user)` added for the lab judge (text-only mode) |

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
| `components/search/SearchBar.tsx` | Search input + mode pills (fulltext/semantic/hybrid) |
| `components/documents/DocumentCard.tsx` | List row and grid tile rendering |
| `components/documents/UploadZone.tsx` | Drag-and-drop upload zone |
| `components/documents/DocumentViewer.tsx` | Document detail modal (tabs: preview/text/details) |
| `components/admin/AdminPanel.tsx` | Admin modal **shell**: sidebar tabs, renders one tab component |
| `components/admin/tabs/IndexingTab.tsx` | Stats grid + Sync / Batch / Re-classify buttons (incl. `StatCard`) |
| `components/admin/tabs/SourcesTab.tsx` | Watched-folder list: add / remove / toggle |
| `components/admin/tabs/AITab.tsx` | AI providers CRUD + Vision toggle. Three sections: Analysis, Vision, Premium (Judge). Providers support inline model editing (pencil icon fetches models via stored API key). Mistral supports OCR + text models. |
| `components/admin/tabs/LogTab.tsx` | Recent indexing log entries |
| `components/ui/IndexingBadge.tsx` | Header badge showing pending OCR count (live polls `/api/indexing/status`) |
| `components/ui/KeyboardHelp.tsx` | Keyboard shortcuts modal (triggered by `?`) |
| `hooks/useKeyboard.ts` | Keyboard shortcut binding hook (ignores input focus) |
| `pages/HomePage.tsx` | Main page: hero search, toolbar, document grid/list |
| `pages/LabPage.tsx` | OCR Lab screen (`/lab/:id`): document on left, OCR/vision/judge experiments on right. See [lab-mode.md](lab-mode.md) |

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

## Planned (not yet implemented)

- Celery/Redis task queue — replaced by FastAPI BackgroundTasks (sufficient for personal app). `config.redis_url` is dead legacy config; nothing reads it.

## Gotchas (save a grep)

- **App settings**: `/api/admin/settings` accepts any key, but the only key the backend actually reads is `enable_ai_vision` (in `services/indexer.py`). `enable_ai_analysis`, `ai_analysis_model`, `ai_vision_model` in `config.py` are env fallbacks, not DB-backed settings.
- **AI providers live in the DB** (`AIProvider` rows, added via Admin UI), not in env. The `*_api_key` fields in `config.py` are only fallback overrides.
- **Tests**: `npm test` from repo root runs all three suites (backend/compute pytest, frontend vitest). See [testing.md](testing.md). Test files live in `backend/tests/`, `compute/tests/`, and `frontend/src/**/*.test.ts`.
- **Compute worker native crash (Windows+conda)**: On miniforge/miniconda, `import easyocr` → `from skimage import io` triggers an OpenBLAS vs MKL DLL conflict when torch (MKL-linked) is already loaded. Exit code `3228369023` (STATUS_ACCESS_VIOLATION), NOT catchable by `except Exception`. Fix: `pip install numpy scipy scikit-image --force-reinstall`. The worker uses `_probe()` (subprocess) at startup to survive this crash in the probe itself. See [compute-worker.md](compute-worker.md).
