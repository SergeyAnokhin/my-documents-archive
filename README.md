# DocIntel — Smart Document Archive

Personal web app for smart search across scanned family documents (Russian, French, English).

## Prerequisites

| Tool | Notes |
|------|-------|
| Python 3.10+ | Recommended via [miniforge](https://github.com/conda-forge/miniforge) (conda) |
| Node.js 18+ | For the frontend |
| Tesseract OCR | System install — **not** via pip. [Windows installer](https://github.com/UB-Mannheim/tesseract/wiki); Linux: `sudo apt install tesseract-ocr` |

**Windows only — install chromadb via conda before `pip install -r requirements.txt`:**

```powershell
conda install -c conda-forge chromadb
```

`pip` will then skip it and install the rest normally. Skipping this step causes a build error (`chroma-hnswlib` requires C++ build tools).

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

```bash
# Tests (from repo root) — backend + compute + frontend
npm test
```

## Documentation

| Doc | What it covers |
|-----|---------------|
| [docs/code-map.md](docs/code-map.md) | **Start here** — every file and its responsibility |
| [docs/testing.md](docs/testing.md) | How to run tests, what each suite pins |
| [docs/architecture.md](docs/architecture.md) | System overview, components, data flow, phases |
| [docs/api.md](docs/api.md) | All REST endpoints with params/responses |
| [docs/lab-mode.md](docs/lab-mode.md) | OCR Lab (`/lab/:id`): compare OCR engines & vision models, premium "judge" |
| [docs/First_Specification.md](docs/First_Specification.md) | Full product specification — **large, high-level; read only when explicitly working on the spec, not for code tasks** |

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
| 5 | ✅ Done | Folder watcher (watchdog) — auto-picks new files from watched folders |
| 6 | ✅ Done | Developer Mode tab in document viewer: pipeline statuses, Re-classify, Re-index |
| 7 | ✅ Scaffolded | External OCR worker |
| 8 | ✅ Done | OCR Lab (`/lab/:id`): compare Tesseract / EasyOCR / vision models on one document; premium AI "judge" ranks the transcriptions |
