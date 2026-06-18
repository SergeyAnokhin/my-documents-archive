# DocIntel — AI Assistant Guide

> **⚠️ READ THIS FIRST before any code changes.**

## Project Identity

DocIntel is a **personal web application** for smart storage, recognition, and search
across a large collection of scanned family archive documents (PDF, JPEG, PNG, TIFF, HEIC, WEBP).

- **User language:** Russian (primary)
- **Interface languages:** Russian + English (i18n)
- **UI philosophy:** Anthropic-style — black background, white text, minimal, welcoming
- **User profile:** Non-technical family archivist — everything must be simple and obvious

## Quick Start for Any LLM

1. **`docs/code-map.md`** → Architecture index (read first!)
2. **`docs/First_Specification.md`** → Full functional spec
3. **`README.md`** → How to install and run

## Key Rules

### UX Priority #1 — Simplicity
- **Complex features go into Admin mode**, hidden from regular users
- Main interface: upload → browse → search. That's it.
- No technical jargon in user-facing text
- Warm, human, approachable tone in all UI copy

### Design
- **Black & white only** — no colors except for functional indicators
- Background: `#0a0a0a`, text: `#fafafa`, cards: `#111`, borders: `#1a1a1a` / `#2a2a2a`
- Font: Inter (Google Fonts)
- Generous whitespace, rounded corners (2xl)
- Anthropic-inspired: clean, modern, warm

### i18n
- Every user-facing string goes into **both** `frontend/src/locales/en.json` and `ru.json`
- Use `t('path.to.key')` in components
- Default language: Russian

### Documentation
- **`docs/code-map.md` is the source of truth** — update it whenever you add/rename/move files
- Keep docs factual, concise, with tables and file paths
- No prose paragraphs — use tables, lists, ASCII diagrams
- Update `docs/First_Specification.md` only for significant architectural decisions

### Code
- Backend: FastAPI + SQLAlchemy + SQLite in `backend/`
- Frontend: React + Vite + TypeScript + Tailwind in `frontend/`
- API: all routes under `/api/`
- Simplicity first — no abstractions without clear need

## Development Phases

| Phase | What | Status |
|-------|------|--------|
| 1 | Foundation: FastAPI, SQLite, upload, React UI | ✅ Done |
| 2 | OCR (Tesseract), full-text search, thumbnails | ✅ Done |
| 3 | AI Analysis (tags, summary, type), provider settings | ✅ Done |
| 4 | AI Vision, semantic search (embeddings) | ✅ Done |
| 5 | Folder monitoring, batch mode, retry logic | ✅ Done |
| 6 | Developer Mode, re-classification, Admin UI | ✅ Done |
| 7 | External OCR Service | ✅ Done |
