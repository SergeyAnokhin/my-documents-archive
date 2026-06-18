# DocIntel — Smart Document Archive

Personal web app for smart search across scanned family documents (Russian, French, English).

## Quick Start

```bash
# Backend
cd backend
pip install -r requirements.txt
python run.py          # → http://localhost:8000

# Frontend (dev)
cd frontend
npm install
npm run dev            # → http://localhost:3000

# OCR Worker (optional, separate machine)
cd compute
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Set `LIBRARY_PATH` env var (default: `./library`) to point at your document folder.

## Documentation

| Doc | What it covers |
|-----|---------------|
| [docs/code-map.md](docs/code-map.md) | **Start here** — every file and its responsibility |
| [docs/architecture.md](docs/architecture.md) | System overview, components, data flow, phases |
| [docs/api.md](docs/api.md) | All REST endpoints with params/responses |
| [docs/First_Specification.md](docs/First_Specification.md) | Full product specification |

## Project Structure

```
backend/     FastAPI + SQLite + Pillow (main app)
compute/     FastAPI OCR worker (Tesseract / EasyOCR)
frontend/    React + Vite + TypeScript
docs/        Architecture docs + AI navigation index
```

## Development Phases

| Phase | Status | Feature |
|-------|--------|---------|
| 1 | ✅ Done | Foundation: upload, DB, React UI |
| 2 | ✅ Done | OCR (Tesseract), thumbnails, background indexing, download, keyboard shortcuts |
| 3 | ✅ Done | AI Analysis (summary, tags, type, language, org, amount) via Anthropic/OpenAI/Gemini/DeepSeek |
| 4 | ✅ Done | AI Vision (optional), semantic + hybrid search (ChromaDB + sentence-transformers) |
| 5 | 🔲 | Folder watcher, Celery task queue |
| 6 | 🔲 | Developer Mode, per-document re-classification UI |
| 7 | ✅ Scaffolded | External OCR worker |
