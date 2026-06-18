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
| `services/ai_vision.py` | AI Vision: sends first document page to vision model; returns description text; supports Anthropic/OpenAI/Gemini |
| `services/embeddings.py` | Embeddings: sentence-transformers (multilingual MiniLM) + ChromaDB; `embed_document()`, `search_similar()`, `collection_count()` |
| `services/indexer.py` | Pipeline coordinator: OCR → Thumbnail → Vision → Analysis → Embedding; batch, reclassify |
| `routers/indexing.py` | Indexing control: single doc, batch, reclassify, status — prefix `/api/indexing` |

## Compute (`compute/app/`)

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI OCR worker — `/ocr` (POST) and `/health` (GET); engines: tesseract, easyocr |

## Frontend (`frontend/src/`)

| Path | Responsibility |
|------|---------------|
| `main.tsx` | React root mount |
| `App.tsx` | Root component: language context, admin modal gate |
| `index.css` | Global CSS variables (design tokens), resets, utilities |
| `i18n/en.ts` | English strings |
| `i18n/ru.ts` | Russian strings |
| `i18n/index.ts` | `LangContext`, `useT()` hook |
| `types/index.ts` | All TypeScript interfaces (`Document`, `SearchResult`, etc.) |
| `api/client.ts` | Thin `fetch` wrapper (`api.get/post/patch/delete/upload`) |
| `api/documents.ts` | Typed API calls for documents, search, upload, admin |
| `components/layout/Header.tsx` | Top nav: logo, language switcher, admin gear icon |
| `components/ui/Button.tsx` | Button component (primary/secondary/ghost/danger, sizes) |
| `components/ui/Modal.tsx` | Accessible modal overlay |
| `components/search/SearchBar.tsx` | Search input + mode pills (fulltext/semantic/hybrid) |
| `components/documents/DocumentCard.tsx` | List row and grid tile rendering |
| `components/documents/UploadZone.tsx` | Drag-and-drop upload zone |
| `components/documents/DocumentViewer.tsx` | Document detail modal (tabs: preview/text/details) |
| `components/admin/AdminPanel.tsx` | Admin modal: indexing stats, folders, AI providers, log |
| `components/ui/IndexingBadge.tsx` | Header badge showing pending OCR count (live polls `/api/indexing/status`) |
| `components/ui/KeyboardHelp.tsx` | Keyboard shortcuts modal (triggered by `?`) |
| `hooks/useKeyboard.ts` | Keyboard shortcut binding hook (ignores input focus) |
| `pages/HomePage.tsx` | Main page: hero search, toolbar, document grid/list |

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

- Folder watcher: watchdog (Phase 5)
- Celery/Redis task queue (Phase 5)
- Developer Mode: per-step model selection, cost comparison (Phase 6)
