# DocIntel — Smart Document Archive

A family document archive with intelligent search. Upload, find, organize.

## Quick Start

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

Open in browser: http://localhost:5173

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/First_Specification.md`](docs/First_Specification.md) | Full project specification |
| [`docs/code-map.md`](docs/code-map.md) | Code map — where everything lives |
| [`AGENTS.md`](AGENTS.md) | Guide for AI assistants |

## Tech Stack

- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** React + Vite + TypeScript + Tailwind CSS
- **Languages:** Russian, English (i18n)
- **Design:** Anthropic-style, black & white, minimal

## Development Phases

- [x] Phase 1 — Foundation (upload, browse, basic structure)
- [x] Phase 2 — OCR + full-text search + thumbnails
- [x] Phase 3 — AI analysis (tags, summary, type)
- [x] Phase 4 — AI Vision + semantic search
- [x] Phase 5 — Folder monitoring + batch indexing
- [x] Phase 6 — Developer Mode + admin interface
- [x] Phase 7 — External OCR service
