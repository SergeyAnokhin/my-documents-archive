# DocIntel — Smart Search System for Personal Document Archives

**Document version:** 2.0  
**Date:** June 2026  
**Status:** Full specification — ready for development

---

## 1. What This Project Is About

DocIntel is a personal web application for smart storage, recognition, and search across a large collection of scanned family archive documents.

The problem it solves: there is a network storage drive containing hundreds or thousands of scanned documents — invoices, contracts, certificates, letters, receipts, medical records, administrative paperwork. Files are named inconsistently, scattered across different folders, and finding the right document without knowing the exact filename is nearly impossible.

DocIntel reads the content of each document, understands what it is about, assigns tags, and allows finding any document by meaning — for example, with a query like "rental invoice 2024" or "medical documents for children." The system is designed for a personal family archive with documents in Russian, French, and English.

---

## 2. Usage Context

The archive contains family administration documents: French administrative paperwork, Russian documents, and documents related to life in both Russia and France. Documents are in three languages — Russian, French, and English. File formats vary: scanned PDFs, document photos in JPEG, PNG, TIFF, HEIC, and other modern mobile camera formats.

The system is installed on a single Linux machine on the home network and runs continuously. All devices on the network — computers, phones, tablets — access it through a browser with no installation required.

---

## 3. Data Storage

### Database

The system uses **SQLite** — a lightweight embedded database requiring no separate server installation. The database is stored **in the same directory as the documents themselves** on the network drive. This is critically important: the directory is regularly backed up, and the database is automatically included in the backup together with the files. The database and the documents always stay together and cannot be separated.

The vector database for semantic search (ChromaDB) is also stored in the same directory, in a dedicated subdirectory called `.docintell/`.

### Storage Structure

```
/path/to/documents/
├── .docintell/
│   ├── docintell.db          ← SQLite database
│   ├── chroma/               ← vector database (embeddings)
│   └── thumbnails/           ← document thumbnails
├── 2023/
│   ├── 01/
│   └── 03/
├── 2024/
│   └── ...
└── [original files]
```

### What Is Stored in the Database

For each document the following is saved:
- Path to the original file
- File hash (for detecting changes)
- Document date (extracted from content) and the date it was added
- Recognized text (OCR)
- AI Vision description (if applied)
- Short document summary (AI-generated)
- Document type (invoice, contract, certificate, letter, etc.)
- Tags
- Document language
- Status for each indexing step
- First-page thumbnail
- Embedding vector for semantic search

---

## 4. Supported File Formats

The system supports all common document and image formats:

- **PDF** — the primary format for scanned documents
- **JPEG, JPG** — document photographs
- **PNG** — screenshots and scans
- **TIFF** — high-quality scans
- **HEIC, HEIF** — modern format used by iPhones and other cameras
- **WEBP** — modern image format

All formats are handled through a unified pipeline — converted to images page by page before OCR and AI analysis.

---

## 5. Adding Documents

### Method 1 — Copying a File to the Folder Manually

The user simply copies a file into the appropriate folder on the network drive. The system periodically checks the folder and detects new files. Once detected, the file is placed in the indexing queue.

### Method 2 — Uploading via the Application Interface

The user drags and drops a file or selects it through a dialog in the web interface. The file is immediately copied to the appropriate folder and placed in the indexing queue without waiting for the next automatic check.

### The "Sync Library" Button

The interface includes a button that triggers an immediate check of the watched folders for new files — for situations where files were copied manually and the user does not want to wait for the next automatic check. The button is labeled **"Sync Library"** or **"Find New Documents"** — with no implication of a full re-index.

---

## 6. Indexing Process

### Principle: Three Independent Steps

Indexing is not a single monolithic process, but **three separate steps** that can be run and configured independently:

```
Step 1 — OCR:          extract text from the image (locally or via external service)
Step 2 — AI Vision:    describe the image using a visual AI model
Step 3 — AI Analysis:  based on text from steps 1 and/or 2 → tags + summary + type
```

Each step can be executed, skipped, or re-run independently of the others. This provides full flexibility in configuration and cost management.

### Step Statuses

| Step | Possible Statuses |
|------|-------------------|
| OCR | pending / done / error |
| AI Vision | pending / done / skipped / error |
| AI Analysis | pending / done / error |

When indexing is re-run, **already successfully completed steps are skipped**. Any individual step can be forcibly re-run — for example, re-running only AI Analysis with a new model without touching the already extracted OCR text.

---

### Step 1 — OCR (Text Recognition)

OCR extracts the textual content from an image or the pages of a PDF.

**Two engine options:**

**Local Tesseract** — runs directly on the machine hosting the application, free, no internet required. Supports Russian, French, and English. Quality is good for most clean scans, but it struggles with handwritten text and complex layouts.

**External OCR Service** — a separate Python microservice that can be run on a more powerful machine on the local network. Accepts an image over HTTP and returns the recognized text. Intended for situations where higher speed or quality is needed. If the external service is unavailable, local Tesseract is automatically used as a fallback.

The OCR engine is selected in the application settings.

---

### Step 2 — AI Vision (Visual Analysis)

The document image is sent to a visual AI model (multimodal / vision model). The model describes what it sees in the image — document structure, visible data, context — even when OCR struggled with the text.

This step is optional. It can be enabled or disabled in settings. It is useful for complex documents with non-standard layouts, stamps, tables, or handwritten annotations.

A **vision model** is used for this step — selected separately from the text model in settings.

---

### Step 3 — AI Analysis (Tags, Summary, Classification)

Based on the collected data — OCR text and/or Vision description — a text AI model generates:

- **Short document summary** (2–3 sentences)
- **Tags** (5–10 keywords or phrases)
- **Document type** (invoice, contract, certificate, medical document, letter, tax document, etc.)
- **Extracted data**: document date, organization name, amount (if applicable)
- **Document language**

The input data strategy for this step is configurable:
- Use only OCR text
- Use only Vision description
- Use both together (best quality, higher cost)

---

### Indexing Run Modes

#### Developer Mode (Dev Mode)

A manual, interactive mode for configuration, experimentation, and finding the optimal setup.

What can be done:
- Select specific documents manually, or take the first N unindexed ones
- Enable or disable each of the three steps individually
- Choose a specific model for each step directly in the interface
- Run and observe the result of each step in real time
- Compare results: "OCR only" vs "OCR + Vision", different models for Analysis
- Evaluate the cost of each configuration

The purpose of this mode is to understand what delivers the best quality at a reasonable cost before launching batch processing across the entire archive.

#### Batch Mode

A background task processing a specified number of documents.

What can be done:
- Launch a task: "index the next N unindexed documents"
- Or "index all unindexed documents"
- The task runs in the background without blocking the interface
- Progress is visible in the interface: how many processed, how many remaining, current speed, estimated time to completion, accumulated API cost
- Can be paused, resumed, or cancelled

**Error and API overload handling:**
If the API returns an overload error (rate limit, 429, 503) — the task automatically pauses and retries after a growing interval (1 min → 5 min → 15 min). The number of retries and intervals are configurable. The document is marked as "awaiting retry" and the task continues processing other documents where possible.

#### Automatic Mode (Auto)

Triggered when a new file is detected — either through folder monitoring or via upload through the interface.

- Uses the standard pipeline configured in global settings
- Runs quietly, no notifications if everything succeeds
- On error — the file is flagged and appears in the error log

---

### Re-classification (Re-typing)

A separate operation — **does not repeat OCR**, only re-runs AI Analysis on the already available text.

Useful when:
- A new model has been selected and you want to improve the tags
- The prompt has been changed or new document types have been added
- You want to add new fields to already indexed documents

Can be run on a single document, a filtered selection, or all documents at once.

---

## 7. AI Provider and Model Configuration

### Configuration Principle

In the application settings, multiple **AI providers** can be added, each with its own API key. For each indexing step (Vision, Analysis), a specific model is then chosen from the list of available ones.

### Supported Providers

- **Anthropic (Claude)** — high quality text analysis
- **DeepSeek** — good text analysis quality, low cost
- **Google Gemini** — excellent vision capabilities, very competitive pricing
- **OpenRouter** — model aggregator providing access to hundreds of models from different providers through a single API key
- Ability to add any OpenAI-compatible endpoint

### Model Selection in the Interface

When selecting a model, the following is displayed next to each one:

- **Cost** — price per 1 million tokens (input / output) in USD
- **Quality rating** — stars (1–5) based on well-known rating resources (LMSys Chatbot Arena, LMSYS leaderboard, and similar)
- **Type** — text-only / vision (visual)
- **Language support** — whether Russian and French are officially supported

This allows making an informed choice between quality and cost.

### Separate Model Selection per Step

A model is chosen **separately** for each indexing step:

- **Vision model** — for Step 2 (visual image analysis)
- **Analysis model** — for Step 3 (generating tags, summary, type)

This matters because vision models are more expensive and can be applied selectively, while a cheaper text model can be used for Analysis.

### Privacy Recommendation per Document Type

For sensitive documents containing personal data (passports, IDs, official identity documents), it is recommended to use only **local processing** — local Tesseract for OCR, with AI steps disabled. No data leaves the local network.

For routine documents (receipts, invoices, letters), cloud AI models such as Gemini Flash can be used — they offer very low cost with good quality for Russian and French.

---

## 8. External OCR Service

A separate standalone Python microservice designed to run on a more powerful machine on the local network (for example, a desktop with a capable processor, while the main application runs on a small always-on server).

### Capabilities

- Accepts images via HTTP request
- Returns recognized text
- Supports multiple OCR engines (Tesseract, EasyOCR, and others)
- Has its own simple status page

### Configuration in the Main Application

In settings, the address of the external service is specified (for example `http://192.168.1.100:8001`). If the service is reachable — OCR is performed on it. If the service is unavailable — the built-in local Tesseract is used automatically.

### Deployment Documentation

Separate installation instructions are provided for the external service: how to install dependencies on Linux, how to start it, and how to configure it to launch automatically on boot.

---

## 9. Interface — Document Browsing

### Display Modes

The interface offers two main viewing modes, switchable with a single button:

**List mode (detailed):**
Each document is a row containing:
- First-page thumbnail (small, but always present)
- Filename
- Document date
- Document type and tags
- Short description with **highlighted words** matching the search query — so it is immediately clear why the system returned that particular document

**Grid mode (thumbnails):**
Documents are displayed as preview images. **4 grid sizes** are available:
- Small — many documents on screen, only thumbnail and filename
- Medium — thumbnail with brief metadata
- Large — first page clearly visible
- Extra large — 2 documents per row, nearly full screen, for visual browsing of the archive

### Date-Based Organization

Documents are grouped by **year and month**. In both display modes, group headers act as dividers — for example "March 2024", "January 2023". This makes it easy to navigate the archive chronologically.

### Document Viewer

Clicking a thumbnail or title opens a **modal window** with a full-size view:

- All pages of the document can be browsed
- Navigation between **documents** (not just pages) using left/right arrow keys — to move through search results without closing the modal window
- Recognized text, tags, summary, and metadata are displayed alongside the document
- Button to download the original file
- Button to manually edit tags

### Keyboard Shortcuts

Keyboard shortcuts are available throughout the entire application. At any point, pressing `?` shows the full list of available shortcuts. Main ones:

| Key | Action |
|-----|--------|
| `/` | Jump to search bar |
| `←` / `→` | Previous / next document in modal window |
| `Esc` | Close modal window |
| `↑` / `↓` | Scroll through document pages |
| `1` / `2` | Switch display mode (list / grid) |
| `+` / `-` | Change grid size |
| `?` | Show all keyboard shortcuts |

---

## 10. Interface — Search

### Two Search Modes

**Full-text search** — classic keyword search. Fast, requires no AI. Searches across recognized text, filename, tags, and summary.

**Semantic search** — intelligent search by meaning. Finds documents even when the query uses different words than those in the document itself. For example, the query "apartment rental documents" will find documents containing "bail", "loyer", or "договор найма". Runs locally via an embeddings model.

**Hybrid mode** — combines both approaches and returns the best result.

The search mode is toggled directly in the search bar.

### Filters

Filters are available next to the search bar:
- By year and month
- By document type
- By tag
- By document language
- By indexing status

### Highlighting in Results

In list mode, words and phrases in each result's description that match the query are highlighted. This explains to the user why the system selected that particular document.

---

## 11. Interface — Administration

The section for managing the system. Consists of several tabs:

### Sources

A list of folders on the network drive that the system monitors. Folders can be added, removed, or individually enabled and disabled.

### Indexing

All indexing management tools are here:

- Statistics: total documents / indexed / pending / with errors
- "Sync Library" button — check folders for new files
- "Batch Indexing" button — launch a background task
- "Re-classify" button — re-run AI Analysis for selected documents
- Real-time progress of the current task
- Accumulated API cost for the current session and all time

**Developer Mode** is also accessible here — a button switches the interface to an expanded mode with detailed per-step controls.

### AI Settings

- Adding and managing provider API keys
- Selecting models for Vision and for Analysis
- Configuring the strategy (which steps are enabled, what data is fed into Analysis)
- Configuring retry parameters for API errors

### Log

Full event log for indexing: which files were processed, with what result, what errors occurred, and how they were handled.

---

## 12. Installation and Running on Linux

The application is installed on a Linux machine without Docker. The project documentation includes a detailed installation guide covering:

- Installing system dependencies (Python, Tesseract, Redis)
- Mounting the SMB share
- Setting up autostart via systemd (so the application starts when the machine boots)
- Instructions for installing and running the external OCR service on a second machine

---

## 13. Project Structure (Components)

The project consists of two independent components:

### Component 1 — Main Application (DocIntel)

A web application that runs continuously on the primary Linux machine. Includes backend (FastAPI + Python), frontend (React), database (SQLite + ChromaDB), task queue (Celery + Redis), folder monitoring (watchdog).

### Component 2 — External OCR Service (DocIntel OCR Worker)

A separate Python service for running on a second, more powerful machine. Accepts images over HTTP and returns recognized text. Has its own installation and deployment guide.

---

## 14. Development Phases

| Phase | Contents | Outcome |
|-------|----------|---------|
| 1 | Foundation: FastAPI, SQLite, file upload, basic React UI | Documents can be added and viewed |
| 2 | OCR (Tesseract), full-text search, thumbnails | Documents can be searched by content |
| 3 | AI Analysis (tags, summary, type), provider settings | Smart classification |
| 4 | AI Vision, semantic search (embeddings) | Full AI pipeline |
| 5 | Folder monitoring, batch mode, retry logic | Automatic indexing |
| 6 | Developer Mode, re-classification, Admin UI | Full system control |
| 7 | External OCR Service | Distributed processing |

Each phase is a complete working version that can already be used on its own.

---

*This document contains the full project specification and serves as the foundation for development.*
