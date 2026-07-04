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
│  Indexing runs in FastAPI BackgroundTasks    │
│  Folder watcher (watchdog) for auto-pickup   │
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
│  OpenAI · Gemini · DeepSeek · Mistral ·      │
│  OpenRouter                                  │
└──────────────────────────────────────────────┘
```

## Indexing Pipeline (per-document, runs in BackgroundTasks after upload)

```
Step 1 — OCR         extract text (local Tesseract or external compute worker)
Step 2 — Thumbnail   generate JPEG preview (Pillow / pdf2image)
Step 3 — AI Vision   send one image or first 3 PDF pages (optional, toggle in Admin)
           └─ picks first vision-capable provider; skips if disabled or none
           └─ capable models (OpenAI/Gemini/OpenRouter) use VISION_FULL_PROMPT
              and return text + ALL analysis fields as one JSON → Step 4 is skipped
           └─ Mistral OCR returns plain transcription only → Step 4 still runs
Step 4 — AI Analysis summary + tags + type + language + org + amount
           └─ uses OCR text + vision description (if available)
           └─ picks first enabled AIProvider from DB; skips if none configured
           └─ skipped entirely when Step 3 already produced structured fields
Step 5 — Embedding   generate multilingual vector → ChromaDB (sentence-transformers)
           └─ enables semantic and hybrid search modes
```

Each step stores its status (`pending/done/skipped/error`) in `Document`.
Steps 1, 3, 4 can be re-run independently via `/api/indexing/` endpoints.
Cost tracked in `api_cost_vision` and `api_cost_analysis` (USD).
Each log row carries a `level` (`trace|debug|info|warning|error`); the Admin Log tab
filters by minimum severity. Step boundaries are `trace`, skips are `debug`, the
combined vision-analysis result is `info`, failures are `error`.
Embeddings model: `paraphrase-multilingual-MiniLM-L12-v2` (local, ~420 MB).

Bulk work should normally use the lazy `index_documents` task documented in
[processing-map.md](processing-map.md). It reuses existing text, skips completed
analysis, uses metadata-only prompts, and leaves classification to separate
Gemini Batch tasks. The pipeline above remains the per-document/upload path.

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
| 8 | OCR Lab (`/lab/:id`): compare Tesseract / EasyOCR / vision models; premium AI judge ranks transcriptions | ✅ Done |
| 9 | Smart classification: expanded 30-type taxonomy, `unclassified` state, confidence tracking, per-doc LLM type picker, batch "classify unclassified" button | ✅ Done |
