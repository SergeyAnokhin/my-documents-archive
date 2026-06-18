# Architecture — DocIntel

## Overview

Two-component system: a main web app and an optional external OCR worker.
Both run on the local home network; all access is via browser.

## Components

```
┌──────────────────────────────────────────────┐
│  Main App (Linux server, always-on)           │
│                                               │
│  frontend/  ←── React, Vite, port 3000       │
│       ↕  /api proxy                          │
│  backend/   ←── FastAPI, port 8000           │
│       ↕                                      │
│  SQLite + ChromaDB (inside library dir)      │
│  Celery + Redis (Phase 5)                    │
└──────────────────────────────────────────────┘
         ↕ HTTP (optional)
┌──────────────────────────────────────────────┐
│  OCR Worker (any machine on LAN)             │
│  compute/  ←── FastAPI, port 8001            │
│  Tesseract / EasyOCR                         │
└──────────────────────────────────────────────┘
         ↕ HTTP (optional)
┌──────────────────────────────────────────────┐
│  AI Providers (cloud, per-document cost)     │
│  Anthropic · Gemini · DeepSeek · OpenRouter  │
└──────────────────────────────────────────────┘
```

## Indexing Pipeline (per-document, runs in BackgroundTasks after upload)

```
Step 1 — OCR         extract text (local Tesseract or external compute worker)
Step 2 — Thumbnail   generate JPEG preview (Pillow / pdf2image)
Step 3 — AI Vision   describe image with vision model (optional, toggle in Admin)
           └─ picks first vision-capable provider; skips if disabled or none
Step 4 — AI Analysis summary + tags + type + language + org + amount
           └─ uses OCR text + vision description (if available)
           └─ picks first enabled AIProvider from DB; skips if none configured
Step 5 — Embedding   generate multilingual vector → ChromaDB (sentence-transformers)
           └─ enables semantic and hybrid search modes
```

Each step stores its status (`pending/done/skipped/error`) in `Document`.
Steps 1, 3, 4 can be re-run independently via `/api/indexing/` endpoints.
Cost tracked in `api_cost_vision` and `api_cost_analysis` (USD).
Embeddings model: `paraphrase-multilingual-MiniLM-L12-v2` (local, ~420 MB).

## Storage Layout

```
library/
├── .docintell/
│   ├── docintell.db     ← SQLite
│   ├── chroma/          ← ChromaDB vectors (Phase 4)
│   └── thumbnails/      ← JPEG thumbnails
└── YYYY/MM/             ← uploaded documents
```

Database travels with the documents — both are in the same backed-up directory.

## Frontend Design

- **Public view**: search hero + document grid/list + upload zone. Zero complexity.
- **Admin panel**: settings gear icon → modal. All complexity isolated here.
- **Language**: EN/RU toggle in header; no page reload, context-based.
- **Style**: Anthropic-inspired black & white — CSS custom properties in `index.css`.

## Development Phases

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | FastAPI + SQLite + upload + React UI | ✅ Done |
| 2 | OCR (Tesseract), thumbnails, background indexing, download | ✅ Done |
| 3 | AI Analysis (summary, tags, type, language, org, amount) | ✅ Done |
| 4 | AI Vision (optional toggle), semantic + hybrid search (ChromaDB) | ✅ Done |
| 5 | Folder watcher (watchdog): auto-indexes files dropped into watched folders | ✅ Done |
| 6 | Developer Mode tab: pipeline step statuses, per-document Re-classify / Re-index | ✅ Done |
| 7 | External OCR worker (compute/) | ✅ Scaffolded |
