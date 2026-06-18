# DocIntel — Code Map

Quick index for AI assistants. Maps every source file to its responsibility.
Read this **first** before touching any code area.

## Project Overview

**DocIntel** — smart document archive with OCR, AI analysis, and semantic search.
- Backend: FastAPI + SQLite + ChromaDB
- Frontend: React + Vite + TypeScript + Tailwind CSS
- Languages: Russian (primary), English
- Design: black-and-white, Anthropic-inspired, minimal

## Directory Structure

```
my-documents-archive/
├── backend/                   ← FastAPI application
│   ├── main.py               ← App entry, all API routes
│   ├── config.py             ← Paths, constants, settings, AI config
│   ├── database.py           ← SQLAlchemy + SQLite FTS5 + search
│   ├── models.py             ← Document ORM model
│   ├── schemas.py            ← Pydantic request/response schemas
│   ├── ocr.py                ← OCR: Tesseract for images & PDFs
│   ├── vision.py             ← AI Vision: image description via multimodal LLM
│   ├── ai_analysis.py        ← AI analysis: tags, type, summary via LLM
│   ├── embeddings.py         ← Semantic search via sentence-transformers + ChromaDB
│   ├── external_ocr.py       ← External AI OCR via DeepSeek Vision (fallback)
│   ├── indexer.py            ← Document indexing pipeline (OCR + Vision + AI + Embed)
│   ├── thumbnails.py         ← Thumbnail generation (PDF → JPEG)
│   ├── watcher.py            ← Folder watcher: auto-detects new files
│   └── requirements.txt      ← Python dependencies
├── frontend/                  ← React application
│   ├── src/
│   │   ├── App.tsx           ← Main React component (all UI)
│   │   ├── main.tsx          ← React entry point
│   │   ├── i18n.ts           ← i18next configuration
│   │   ├── index.css         ← Tailwind + design tokens
│   │   └── locales/
│   │       ├── en.json       ← English translations
│   │       └── ru.json       ← Russian translations
│   ├── index.html            ← HTML shell with Inter font
│   └── vite.config.ts        ← Vite + Tailwind + API proxy
├── docs/
│   ├── First_Specification.md ← Full functional specification
│   └── code-map.md           ← This file — architecture index
├── data/                     ← Runtime data (gitignored)
│   └── documents/
│       └── .docintell/       ← SQLite DB + ChromaDB + thumbnails
├── AGENTS.md                 ← Entry point for AI assistants
└── README.md                 ← Setup & run instructions
```

## Backend: File → Responsibility

| File | What it does | Key exports / functions |
|------|-------------|------------------------|
| `backend/main.py` | FastAPI app, 21 API routes: upload, list, search, stats, watcher, AI config, indexing | `app` |
| `backend/config.py` | Paths (DATA_DIR, DB_DIR), constants (SUPPORTED_FORMATS), AI config persistence | `get_ai_config()`, `save_ai_config()` |
| `backend/database.py` | SQLAlchemy engine, session, Base, init_db(), FTS5 setup, search | `get_db`, `init_db`, `search_documents()`, `rebuild_fts()` |
| `backend/models.py` | Document ORM: columns, to_dict(), helper functions | `Document`, `IndexingStatus`, `generate_uuid()`, `file_hash()` |
| `backend/schemas.py` | Pydantic models for API validation | `DocumentOut`, `DocumentListOut`, `StatsOut` |
| `backend/ocr.py` | Tesseract OCR: image_to_text(), pdf_to_text() (renders pages→images→OCR) | `process_document()`, `image_to_text()`, `pdf_to_text()` |
| `backend/vision.py` | AI Vision: sends image to multimodal LLM, returns description | `analyze_image()` |
| `backend/ai_analysis.py` | AI Analysis: tags, summary, type, language, date, org, amount via LLM | `analyze_document()` |
| `backend/embeddings.py` | Semantic search: sentence-transformers (multilingual-e5-small) + ChromaDB | `semantic_search()`, `index_embedding()`, `semantic_available()` |
| `backend/external_ocr.py` | External AI OCR: fallback text extraction via multimodal LLM when Tesseract fails | `external_ocr()`, `get_external_ocr_stats()` |
| `backend/indexer.py` | Indexing pipeline: OCR → Vision → AI → Embeddings, retry logic, batch jobs | `index_document()`, `get_batch_status()` |
| `backend/thumbnails.py` | Thumbnail generation: PDF first page → JPEG, image → JPEG | `generate_thumbnail()` |
| `backend/watcher.py` | Folder monitoring: watchdog detects new files, auto-indexes them | `start_watcher()`, `stop_watcher()`, `get_watcher_stats()` |

### Indexing Pipeline (indexer.py)

```
index_document(doc_id):
  Step 1 — OCR         → ocr.process_document()        → status: pending/done/error
  Step 2 — AI Vision   → vision.analyze_image()         → status: pending/done/skipped/error
  Step 3 — AI Analysis  → ai_analysis.analyze_document() → status: pending/done/error
  Step 4 — Embeddings   → embeddings.index_embedding()   → status: pending/done/error

Each step is independent — can be skipped if already done, re-run individually.
Retry: up to DEFAULT_MAX_RETRIES (3), with RETRY_DELAY_SECONDS (5s) between.
Batch: batch indexing with progress tracking via _batch_jobs dict.
```

### API Routes

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/documents/upload` | Upload new document (auto-indexes: thumbnail + OCR) |
| `GET` | `/api/documents` | List documents (?skip, ?limit) |
| `GET` | `/api/documents/{id}` | Get single document |
| `PUT` | `/api/documents/{id}` | Update metadata (Dev Mode) — tags, type, summary, date |
| `GET` | `/api/documents/{id}/download` | Download original file |
| `GET` | `/api/documents/{id}/thumbnail` | Get thumbnail image |
| `GET` | `/api/search` | Full-text + semantic + hybrid search (?q=, ?limit=, ?mode=) |
| `POST` | `/api/documents/{id}/reindex` | Re-run full indexing on a document |
| `POST` | `/api/documents/{id}/reanalyze` | Re-run AI Analysis only (re-classification) |
| `POST` | `/api/documents/{id}/external-ocr` | Run external AI OCR on document |
| `GET` | `/api/stats` | Document statistics: total, indexed, pending, errors |
| `POST` | `/api/index/next` | Process next N pending documents |
| `POST` | `/api/index/batch` | Batch indexing with progress (?limit=, ?retries=) |
| `GET` | `/api/index/batch/{job_id}` | Get batch job status |
| `POST` | `/api/index/analyze` | Re-analyze already-indexed documents with new AI config |
| `POST` | `/api/watcher/start` | Start folder monitoring |
| `POST` | `/api/watcher/stop` | Stop folder monitoring |
| `GET` | `/api/watcher/status` | Watcher status & stats |
| `GET` | `/api/ai-config` | Get current AI provider configuration |
| `PUT` | `/api/ai-config` | Update AI provider configuration |
| `GET` | `/api/external-ocr/stats` | External OCR usage statistics |

### Database Schema

Table `documents`:
- `id` (PK, UUID), `filename`, `original_filename`, `file_path` (unique), `file_hash`, `file_size`, `mime_type`
- `doc_date`, `doc_language`, `doc_type`
- `ocr_text`, `vision_description`, `summary`, `tags` (JSON list)
- `ocr_status`, `vision_status`, `analysis_status` (enum: pending/done/skipped/error)
- `thumbnail_path`, `page_count`
- `created_at`, `updated_at`

FTS5 virtual table `documents_fts` — full-text index on `original_filename`, `ocr_text`, `summary`, `tags`.
Triggers `docs_ai`, `docs_ad`, `docs_au` keep FTS5 in sync with documents table.

## Frontend: File → Responsibility

| File | What it does |
|------|-------------|
| `src/App.tsx` | Main React component — header, upload, search, grid/list, document cards/modal, admin panel |
| `src/main.tsx` | React root mount (`createRoot`) |
| `src/i18n.ts` | i18next init, loads EN/RU translations, detects browser language |
| `src/index.css` | Tailwind imports, custom theme tokens (--doc-black, --doc-white, etc.) |
| `src/locales/en.json` | English UI strings (44 lines) |
| `src/locales/ru.json` | Russian UI strings (44 lines) |
| `index.html` | HTML shell, Inter font from Google Fonts, app mount point |
| `vite.config.ts` | Vite plugins (React + Tailwind v4), API proxy → `localhost:8000` |

### Design System

- **Colors**: `#0a0a0a` (bg), `#fafafa` (text), `#111` (cards), `#1a1a1a` (borders), `#2a2a2a` (secondary borders)
- **Font**: Inter (Google Fonts), loaded via index.html
- **Layout**: max-w-7xl centered, generous padding, sticky header
- **View modes**: Grid (default, responsive columns) + List (compact rows)
- **Tailwind**: v4 (via `@tailwindcss/vite` plugin)

## Data Flow

```
┌─ Upload ────────────────────────────────────────────────┐
│ User drops file → POST /api/documents/upload            │
│   → saved to data/documents/{id}.ext                    │
│   → Document row in SQLite (.docintell/docintell.db)    │
│   → Thumbnail generated                                 │
│   → index_document() triggered:                         │
│       Step 1 — OCR (Tesseract)                          │
│       Step 2 — AI Vision (multimodal LLM, if enabled)   │
│       Step 3 — AI Analysis (LLM: tags, summary, type)   │
│       Step 4 — Embedding (ChromaDB, if model loaded)    │
│   → returns Document JSON                               │
└─────────────────────────────────────────────────────────┘

┌─ Browse ────────────────────────────────────────────────┐
│ App loads → GET /api/documents → list of all documents  │
│          → GET /api/stats → counts                      │
│ User clicks → modal with metadata + download link       │
└─────────────────────────────────────────────────────────┘

┌─ Search ────────────────────────────────────────────────┐
│ User types query → GET /api/search?q=...&mode=...       │
│   fulltext → SQLite FTS5 (keyword)                      │
│   semantic → ChromaDB (embeddings)                      │
│   hybrid → both combined, deduped                       │
│ Results returned with snippet highlighting              │
└─────────────────────────────────────────────────────────┘

┌─ Auto-Import (Folder Watcher) ──────────────────────────┐
│ Watcher detects new file in data/documents/             │
│   → auto-uploads → auto-indexes (same pipeline)         │
│ POST /api/watcher/start → start monitoring              │
│ POST /api/watcher/stop → stop                           │
│ GET /api/watcher/status → stats                         │
└─────────────────────────────────────────────────────────┘

┌─ Re-analysis / Re-indexing ─────────────────────────────┐
│ POST /api/documents/{id}/reindex → full re-run          │
│ POST /api/documents/{id}/reanalyze → AI-only re-run     │
│ POST /api/index/analyze → batch re-analysis             │
│ Skips already-done steps (status=done)                  │
└─────────────────────────────────────────────────────────┘
```

## AI Configuration Flow

```
GET /api/ai-config → returns {provider, analysis_model, analysis_enabled, vision_model, vision_enabled}
PUT /api/ai-config → updates ai_config.json in .docintell/
                    → used by: vision.py, ai_analysis.py, external_ocr.py
                    → get_ai_config() reads this file, falls back to defaults
```

## Development Phases — All Complete ✅

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Foundation: FastAPI, SQLite, upload, React UI | ✅ Done |
| 2 | OCR (Tesseract), full-text search (FTS5), thumbnails | ✅ Done |
| 3 | AI Analysis (tags, summary, type), provider settings | ✅ Done |
| 4 | AI Vision, semantic search (embeddings + ChromaDB) | ✅ Done |
| 5 | Folder monitoring (watchdog), batch mode, retry logic | ✅ Done |
| 6 | Developer Mode, re-classification, Admin UI | ✅ Done |
| 7 | External AI OCR Service | ✅ Done |

## Conventions

- **Python**: `backend/` package, imports use `from backend.xxx import ...`
- **React**: single file component in `App.tsx` (UI is complex but still monolithic)
- **i18n**: keys in `t('documents.xxx')` format, add to both `en.json` and `ru.json`
- **API**: all routes under `/api/`, JSON responses, FastAPI auto-docs at `/docs`
- **DB**: SQLite in `data/documents/.docintell/`, auto-created on first run via `init_db()`
- **FTS5**: virtual table `documents_fts` with triggers for INSERT/UPDATE/DELETE sync
- **Embeddings**: ChromaDB stored in `.docintell/chroma/`, model: `intfloat/multilingual-e5-small`
- **OCR**: Tesseract with lang `rus+fra+eng`, PSM 3, always renders PDF pages as images (no embedded text extraction — Cyrillic font mappings are broken)
- **AI Config**: persisted in `.docintell/ai_config.json`, editable via API
- **Thumbnails**: 300×400 JPEG, stored in `.docintell/thumbnails/`
- **Watcher**: uses `watchfiles`, runs in background thread, auto-indexes new files
