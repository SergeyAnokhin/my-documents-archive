# DocIntel — Code Map

Quick index for AI assistants. Maps every source file to its responsibility.
Read this **first** before touching any code area.

## Project Overview

**DocIntel** — smart document archive with OCR, AI analysis, and semantic search.
- Backend: FastAPI + SQLite + ChromaDB (future)
- Frontend: React + Vite + TypeScript + Tailwind CSS
- Languages: Russian (primary), English
- Design: black-and-white, Anthropic-inspired, minimal

## Directory Structure

```
my-documents-archive/
├── backend/                   ← FastAPI application
│   ├── main.py               ← App entry, all API routes
│   ├── config.py             ← Paths, constants, settings
│   ├── database.py           ← SQLAlchemy + SQLite FTS5 + search
│   ├── models.py             ← Document ORM model
│   ├── schemas.py            ← Pydantic request/response schemas
│   ├── ocr.py                ← OCR: Tesseract for images & PDFs
│   ├── indexer.py            ← Document indexing pipeline
│   ├── thumbnails.py         ← Thumbnail generation (PDF → JPEG)
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
│       └── .docintell/       ← SQLite DB + ChromaDB (future)
├── CLAUDE.md                 ← LLM behavioral guidelines (generic)
├── AGENTS.md                 ← Entry point for AI assistants
└── README.md                 ← Setup & run instructions
```

## Backend: File → Responsibility

| File | What it does | Key exports |
|------|-------------|-------------|
| `backend/main.py` | FastAPI app, all routes: upload, list, download, stats | `app` |
| `backend/config.py` | Paths (DATA_DIR, DB_DIR), constants (SUPPORTED_FORMATS) | All config vars |
| `backend/database.py` | SQLAlchemy engine, session, Base, init_db() | `get_db`, `init_db` |
| `backend/models.py` | Document table: id, filename, ocr_text, tags, statuses, etc. | `Document`, `IndexingStatus` |
| `backend/schemas.py` | Pydantic models for API validation | `DocumentOut`, `StatsOut` |

### API Routes

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/documents/upload` | Upload new document (auto-indexes: thumbnail + OCR) |
| `GET` | `/api/documents` | List documents (?skip, ?limit) |
| `GET` | `/api/documents/{id}` | Get single document |
| `GET` | `/api/documents/{id}/download` | Download original file |
| `GET` | `/api/documents/{id}/thumbnail` | Get thumbnail image |
| `GET` | `/api/search` | Full-text search (?q=, ?limit=) — FTS5 |
| `POST` | `/api/documents/{id}/reindex` | Re-run OCR on a document |
| `POST` | `/api/index/next` | Process next N pending documents |
| `GET` | `/api/stats` | Counts: total, indexed, pending, errors |

### Database Schema

Table `documents`:
- `id`, `filename`, `original_filename`, `file_path`, `file_hash`, `file_size`, `mime_type`
- `doc_date`, `doc_language`, `doc_type`
- `ocr_text`, `vision_description`, `summary`, `tags` (JSON)
- `ocr_status`, `vision_status`, `analysis_status` (enum: pending/done/skipped/error)
- `thumbnail_path`, `page_count`
- `created_at`, `updated_at`

## Frontend: File → Responsibility

| File | What it does |
|------|-------------|
| `src/App.tsx` | All UI: header, sidebar, search, grid/list toggle, upload, document modal, filtering |
| `src/main.tsx` | React root mount |
| `src/i18n.ts` | i18next init, loads EN/RU translations |
| `src/index.css` | Tailwind imports, custom theme tokens (--doc-black, --doc-white, etc.) |
| `src/locales/en.json` | English UI strings |
| `src/locales/ru.json` | Russian UI strings |
| `vite.config.ts` | Vite plugins (React + Tailwind), API proxy → localhost:8000 |

### Design System

- **Colors**: `#0a0a0a` (bg), `#fafafa` (text), `#111` (cards), `#1a1a1a` (borders), `#2a2a2a` (secondary borders)
- **Font**: Inter (Google Fonts), loaded via index.html
- **Layout**: max-w-7xl centered, generous padding, sticky header
- **View modes**: Grid (default, responsive columns) + List (compact rows)

## Data Flow

```
User drops file → POST /api/documents/upload
                     → saved to data/documents/{id}.ext
                     → Document row created in SQLite (.docintell/docintell.db)
                     → returns Document JSON

App loads → GET /api/documents → list of all documents
         → GET /api/stats → counts

User clicks document → modal with metadata + download link
```

## Future Phases (not yet implemented)

- OCR (Tesseract) — Phase 2
- Full-text search — Phase 2
- AI Analysis (tags/summary) — Phase 3
- AI Vision — Phase 4
- Semantic search (embeddings) — Phase 4
- Folder monitoring (watchdog) — Phase 5
- Batch indexing — Phase 5
- Developer Mode — Phase 6
- External OCR Service — Phase 7

## Conventions

- Python: `backend/` package, imports use `from backend.xxx import ...`
- React: single-file component pattern (full App in App.tsx for Phase 1)
- i18n: keys in `t('documents.xxx')` format, add to both en.json and ru.json
- API: all routes under `/api/`, JSON responses, FastAPI auto-docs at `/docs`
- DB: SQLite in `data/documents/.docintell/`, auto-created on first run
