# Code Map — DocIntel

Quick index for LLM navigation. Check this file before grepping.

## Directory Tree

```
backend/          FastAPI Python backend (main app)
compute/          External OCR microservice (optional, runs on separate machine)
frontend/         React + Vite + TypeScript UI
docs/             Architecture docs (you are here)
deploy/           Helm chart + ArgoCD Application for k3s deployment
.github/workflows/ CI: build images → GHCR → bump tags → push `deploy` branch
```

## Backend (`backend/app/`)

| File | Responsibility |
|------|---------------|
| `run.py` | Dev entry point (`python run.py` → uvicorn on :8000) |
| `main.py` | FastAPI app factory, CORS, startup hooks, thumbnail static mount |
| `config.py` | All settings (pydantic-settings); `settings` singleton |
| `database.py` | SQLAlchemy engine, `SessionLocal`, `get_db()`, `init_db()` |
| `models.py` | ORM models: `Document` (incl. `source` = `"upload"`/`"sync"`), `WatchedFolder`, `IndexingLog` (incl. `level` = `trace`/`debug`/`info`/`warning`/`error`), `AIProvider`, `AppSettings`, `Task`/`TaskLog`, `AIUsage` (per-call AI/OCR usage ledger — powers the super-user usage screen) |
| `schemas.py` | Pydantic request/response schemas for all endpoints |
| `routers/documents.py` | CRUD: list, get, delete, patch tags, patch type (`PATCH /{id}/type` sets type + `manually_classified=true`) — prefix `/api/documents` |
| `routers/upload.py` | File upload endpoint — prefix `/api/upload` |
| `routers/search.py` | Full-text + semantic search — prefix `/api/search`. `GET /` fulltext/semantic/hybrid; `GET /ask` AI Q&A (semantic retrieval → AI provider → answer + sources). Fulltext searches filename, ocr_text, summary, document_type, tags, person, organization. |
| `routers/admin.py` | **Aggregator** — mounts the five `admin_*` sub-routers under prefix `/api/admin`. Start here, then jump to the right sub-router below |
| `routers/admin_library.py` | Stats, sync, batch-index, reclassify-all/unclassified, log (+ `_log` helper) |
| `routers/admin_folders.py` | Watched-folder CRUD: list / add / remove / toggle |
| `routers/admin_providers.py` | AI providers CRUD, model listing (`/models`), arena ratings (`/arena-ratings`) |
| `routers/admin_settings.py` | App settings key-value get/upsert (`/settings`) |
| `routers/admin_backups.py` | DB backup list + restore (advanced users): `GET /backups`, `POST /backups/restore` |
| `routers/admin_usage.py` | AI usage ledger (super-user screen): `GET /usage` (rows), `GET /usage/summary` (cards+charts), `GET /usage/pivot` (row×col×metric matrix), `DELETE /usage`. See [ai-usage.md](ai-usage.md) |
| `routers/admin_providers.py` (export/import) | `GET /providers/export` + `POST /providers/import` — full provider config **including API keys** (backup/migrate). See [ai-usage.md](ai-usage.md) |
| `services/db_backup.py` | List/restore SQLite backups written by the `backup.py` sidecar; restore = atomic swap + `docintell.db.pre-restore` safety snapshot |
| `services/storage.py` | File hashing, MIME detection, library scanning (skips `.docintell`/hidden dirs), saving uploads to `YYYY/MM/`. `infer_document_date()`/`extract_folder_date()` guess a doc date from path (`[YYYY-MM]`, `YYYY/MM/`, `YYYY-MM/`) or file ctime. `check_library_accessible()` — sentinel check (`.docintell` dir) used to abort sync when the disk is offline |
| `services/thumbnails.py` | Generate JPEG thumbnails (Pillow + pdf2image) |
| `services/ocr.py` | OCR extraction: local Tesseract or external worker (fallback chain). `extract_text()` returns `(text, engine)`; the indexer stores `engine` (`tesseract`/`easyocr`) in `documents.ocr_model` for per-doc engine attribution |
| `services/ai_analysis.py` | AI Analysis: produces summary, document_type (+confidence), tags, language, org, amount via LLM. Type taxonomy comes from `ai_common.DOCUMENT_TYPES_BLOCK` (shared with vision). `coerce_analysis_fields(dict)→AnalysisResult` is the shared field-coercion used by both this module and `ai_vision`. Also exposes `suggest_document_types(...)` → top-3 suggestions for the UI picker. |
| `services/ai_common.py` | Shared AI-provider helpers, de-duplicated from analysis+vision: `strip_code_fences()`, `parse_llm_json()` (tolerates trailing commas + markdown fences — used by batch analysis), `update_provider_stats()`, `SyntheticProvider` (env-var provider stand-in), `DOCUMENT_TYPES_BLOCK` (canonical type taxonomy). |
| `services/ai_vision.py` | AI Vision: sends first document page to vision model. For capable models (OpenAI/Gemini/OpenRouter) uses `VISION_FULL_PROMPT` — returns structured JSON (text + all analysis fields) in one call, so the indexer skips Step 4 entirely. For **Mistral OCR** (`mistral-ocr-latest`, dedicated `/v1/ocr` endpoint, per-page billing) returns plain transcription — Analysis still runs. Public `run_vision(provider, img_bytes, prompt)` + `load_first_page()` reused by the lab. |
| `services/lab.py` | OCR Lab logic: run local/worker OCR, vision-as-transcriber, and premium "judge" comparison on one document's first page. Ephemeral — no document writes. See [lab-mode.md](lab-mode.md) |
| `services/embeddings.py` | Embeddings: sentence-transformers (multilingual MiniLM) + ChromaDB; `embed_document()`, `search_similar()`, `collection_count()` |
| `services/pricing.py` | `estimate_cost(model, tokens_in, tokens_out)` — static per-token price table for all known providers (OpenAI, Gemini, DeepSeek, Mistral, OpenRouter). Returns 0.0 for unknown models. |
| `services/provider_models.py` | `fetch_models(provider_type, api_key, base_url)` — lists available models from a provider's API (used by admin "fetch models" and inline model edit) |
| `services/arena_ratings.py` | LM Arena leaderboard star ratings: `get_cached(db)` / `refresh_ratings(db)`; cached in DB, surfaced in the AI tab model picker |
| `services/type_icon_suggestion.py` | Suggests Lucide icon names for custom document types via LLM. `suggest_icons_for_types(slugs, db)` → calls AI provider once per type, resolves conflicts (max 5 retries), saves results under AppSettings key `custom_type_icons`. `get_pending_custom_types(db)` returns types in the library that lack a custom icon. Exposed via `GET /api/admin/type-icons` and `POST /api/admin/update-type-icons`. |
| `services/indexer.py` | Pipeline coordinator: OCR → Thumbnail → Vision → Analysis → Embedding. `_apply_analysis_result(doc, AnalysisResult, db)` is the single helper that writes metadata onto a Document, shared by Step 3 (vision-as-analysis) and Step 4. Preserves old `document_type` in tags when type changes during reclassification. Batch ops: `reclassify_pending_batch()` (unanalyzed docs); `reclassify_unclassified_batch()` (unclassified/other, skips `manually_classified=True`); `reclassify_document()` (resets manual flag) |
| `services/recluster.py` | Cluster-based recategorization: clean summaries (strip tags/names/dates) → embed (sentence-transformers) → auto-select k via silhouette score → k-means → LLM names each cluster (type slug + icon) → apply (old type preserved in tags). Entry point: `run_recluster(task_id=None)`. Endpoint: `POST /api/admin/recluster`. Task type: `recluster`. |
| `services/watcher.py` | Folder watcher: watchdog Observer that picks up new files from enabled WatchedFolders and queues indexing |
| `routers/indexing.py` | Indexing control: single doc, batch, reclassify, status, suggest-type (`POST /suggest-type/{id}` → LLM top-3 type suggestions) — prefix `/api/indexing` |
| `routers/lab.py` | OCR Lab endpoints: methods, ocr, vision, judge — prefix `/api/lab`. See [lab-mode.md](lab-mode.md) |
| `services/ai_analysis.py` (helper) | Public `run_text(provider, system, user)` added for the lab judge (text-only mode) |
| `routers/tasks.py` | Task queue CRUD + run/stop/logs + the `_run_task_bg` dispatcher and the short in-process runners (index/sync/reclassify/cleanup) — prefix `/api/tasks`. Used by the Tasks panel (advanced mode only). |
| `services/task_runtime.py` | Shared helpers for background task runners (`log_task`, `is_stopped`, `set_progress`, `finish`) — each opens its own short-lived session. Imported by `tasks.py` and `batch_ocr.py`. |
| `services/batch_ocr.py` | Long-running batch-OCR task runners `run_batch_ocr_mistral()` / `run_batch_ocr_gemini()` (submit remote batch job → poll → write OCR back). Split out of `tasks.py`. See [batch-ocr.md](batch-ocr.md) |
| `services/batch_analysis.py` | `run_batch_analysis_gemini()` — text-only analysis via Gemini Batch API. `doc_scope` param selects: `needs_analysis` (default), `unclassified` (for `reclassify_unclassified` task), `pending` (for `reclassify_all` task). Saves raw JSONL to `.docintell/batch_results/task_{id}.jsonl`. |
| `services/usage.py` | `record_usage(...)` — appends one row to the `ai_usage` ledger. Called by every model call site (analysis, vision, qa, suggest_types, icon_suggest, batch_*, ocr, embedding). Opens its own session; never raises. See [ai-usage.md](ai-usage.md) |

## Compute (`compute/app/`)

| File | Responsibility |
|------|---------------|
| `main.py` | FastAPI OCR worker — `/ocr` (POST) and `/health` (GET); engines detected at startup via `_probe()` subprocess (isolates native DLL crashes from the main process); see [compute-worker.md](compute-worker.md) |

## Frontend (`frontend/src/`)

| Path | Responsibility |
|------|---------------|
| `main.tsx` | React root mount |
| `App.tsx` | Root component: language context + `BrowserRouter` routes (`/` home, `/lab/:id` OCR Lab) |
| `index.css` | Global CSS variables (design tokens), resets, utilities |
| `i18n/en.ts` | English strings (source of `Translations` type) |
| `i18n/ru.ts` | Russian strings |
| `i18n/fr.ts` | French strings |
| `i18n/index.ts` | `Lang` type (`"en" \| "ru" \| "fr"`), `LangContext`, `useT()` hook |
| `types/index.ts` | All TypeScript interfaces (`Document`, `SearchResult`, etc.) |
| `api/client.ts` | Thin `fetch` wrapper (`api.get/post/patch/delete/upload`) |
| `api/documents.ts` | Typed API calls for documents, search, upload, admin |
| `components/layout/Header.tsx` | Top nav: logo, language switcher, dark/light theme toggle (persisted in localStorage), admin gear icon |
| `components/ui/Button.tsx` | Button component (primary/secondary/ghost/danger, sizes) |
| `components/ui/Modal.tsx` | Accessible modal overlay |
| `components/search/SearchBar.tsx` | Search input + mode pills (fulltext/semantic/hybrid/ask) + voice input (Web Speech API, language follows UI lang) + year/language quick-filter chips |
| `components/search/FilterDropdown.tsx` | Reusable filter dropdown used by the search toolbar |
| `components/search/AIAnswer.tsx` | AI Q&A result card: answer text + source document list |
| `components/documents/DocumentCard.tsx` | List row and grid tile rendering. Renders a per-class type icon (`typeIcons.ts`) at the far right of the list meta row and as a badge on the grid thumbnail. `ProcessingBadge` shows the highest processing tier reached: gray dot (pending) → green/teal dot (local OCR Tesseract/EasyOCR, from `ocr_model`) → violet `ScanText` icon (AI text recognition) → gradient `Sparkles` badge (full AI analysis, `analysis_status==="done"`) |
| `components/documents/typeIcons.ts` | Maps each `document_type` slug (AI taxonomy) → a lucide icon; `iconForType()` with keyword + `FileText` fallbacks for free-form types |
| `components/documents/UploadZone.tsx` | Drag-and-drop upload zone |
| `components/documents/DocumentViewer.tsx` | Document detail modal (tabs: preview/text/details/dev). Type badge renders `TypePicker` |
| `components/documents/TypePicker.tsx` | Inline type picker on the type badge: fetches LLM suggestions on click, lets user pick from top-3 or enter a free-form type (+ `formatTypeName`) |
| `components/admin/AdminPanel.tsx` | Admin modal **shell**: sidebar tabs, renders one tab component |
| `components/admin/tabs/IndexingTab.tsx` | Stats grid + Sync / Batch / Re-classify / "Classify unclassified" buttons (incl. `StatCard`). Shows `unclassified` count as a danger card, the resolved `library_path`, and the last sync's added/removed counts. |
| `components/admin/tabs/SourcesTab.tsx` | Watched-folder list: add / remove / toggle |
| `components/admin/tabs/AITab.tsx` | **Shell** for the AI tab: Vision toggle, Update Ratings, three `ProviderSection`s (Analysis / Vision / Premium-Judge). Sub-components live in `tabs/ai/` |
| `components/admin/tabs/ai/aiUtils.ts` | Constants + formatters (`fmtTokens`, `blendedPrice`, …) + `lookupModelRating` + add-form name helpers |
| `components/admin/tabs/ai/ModelPicker.tsx` | Searchable/sortable model list with ratings & pricing |
| `components/admin/tabs/ai/RatingStars.tsx` | Star display for a model's arena rating |
| `components/admin/tabs/ai/AddProviderForm.tsx` | Add-provider form: pick type/key, fetch models, save |
| `components/admin/tabs/ai/ProviderRow.tsx` | One provider row: reorder, inline model edit, settings, toggle, delete |
| `components/admin/tabs/ai/ProviderSettingsPanel.tsx` | Per-provider fine-tuning (Mistral image policy; temperature/max_tokens for chat) |
| `components/admin/tabs/ai/ProviderSection.tsx` | Section wrapper: provider list + add form for one task type |
| `components/admin/tabs/LogTab.tsx` | Recent indexing log entries with a minimum-severity filter (`trace`→`error`) over each row's `level` |
| `components/admin/tabs/BackupTab.tsx` | DB backups list + restore. **Advanced-mode-only** tab (gated in `AdminPanel.tsx`) |
| `components/admin/tabs/UsageTab.tsx` (+`.css`) | Super-user AI usage screen (**advanced-mode-only** tab): summary cards, CSS bar charts (by type/provider/model/day), configurable row×col×metric pivot table, recent-calls list, clear. Reads `/api/admin/usage*`. See [ai-usage.md](ai-usage.md) |
| `components/admin/tabs/AITab.tsx` (export/import) | Header has Export/Import buttons → download/upload full provider config JSON (incl. API keys) via `/admin/providers/export\|import` |
| `public/icon.svg` | App icon — used as the browser favicon (`index.html`) and the header logo mark (`Header.tsx`) |
| `components/ui/IndexingBadge.tsx` | Header badge showing pending OCR count (live polls `/api/indexing/status`) |
| `components/ui/KeyboardHelp.tsx` | Keyboard shortcuts modal (triggered by `?`) |
| `hooks/useKeyboard.ts` | Keyboard shortcut binding hook (ignores input focus) |
| `contexts/AdvancedModeContext.tsx` | Boolean context for "advanced user mode" — persisted in localStorage; enables OCR Tuning button and Tasks panel |
| `components/tasks/TasksPanel.tsx` | Task management panel (advanced mode only): block grid, drag-reorder, run/stop, logs modal |
| `components/tasks/TasksPanel.css` | Styles for task cards, badges, progress bars, create form, logs modal |
| `pages/HomePage.tsx` | Main page: hero search, toolbar, document grid/list |
| `pages/LabPage.tsx` | OCR Lab screen (`/lab/:id`) **orchestrator**: document viewer (zoom/pan/crop/transform) + OCR/vision/judge handlers. Presentational pieces live in `pages/lab/`. See [lab-mode.md](lab-mode.md) |
| `pages/lab/labUtils.ts` | `formatMs`, `formatFileSize`, `uid`, `VISION_CAPABLE` |
| `pages/lab/useImageTransform.ts` | Zoom + pan for the lab image canvas: wheel-zoom at cursor, button zoom, fit-on-load, drag-to-pan. Owns its wheel/pan listeners; exposes `zoomRef` for the page's crop overlay. Extracted from `LabPage.tsx`. |
| `pages/lab/useLogs.ts` | Activity-log hook (append + auto-scroll) for the panel |
| `pages/lab/usePanelResize.ts` | Draggable right-panel width hook (persists to localStorage) |
| `pages/lab/FieldChips.tsx` | Chips summarising extracted structured fields |
| `pages/lab/ResultsList.tsx` | List of OCR/vision results with save/expand/remove |
| `pages/lab/JudgePanel.tsx` | Premium "judge" section: pick providers, compare, verdicts |
| `pages/lab/FloatingTextModal.tsx` | Draggable floating modal showing one result's full text |

## Deployment (k3s + ArgoCD + GHCR)

Platform contract lives in [k3s-platform-deployment.md](k3s-platform-deployment.md) (**read-only spec — don't read/edit during normal dev**). GitOps: push to `main` → GitHub Actions builds images → GHCR → bumps Helm tags → force-pushes `deploy` branch → ArgoCD syncs.

| File | Responsibility |
|------|---------------|
| `backend/Dockerfile` | Backend image: Python + Tesseract(rus+fra+eng) + poppler + libmagic. Context = repo root |
| `backend/backup.py` | DB-backup sidecar: every 5 min (if DB changed) writes a consistent `sqlite3.backup()` copy to the NAS root, rotating the 2 newest (`docintell.db.backup.1/.2`) |
| `frontend/Dockerfile` | Frontend image: Vite build → nginx static. Context = repo root |
| `frontend/nginx.conf` | nginx SPA history fallback (`/api`,`/thumbnails` routed by ingress, not here) |
| `.dockerignore` | Excludes node_modules, `library/`, DBs, caches from build contexts |
| `.github/workflows/build.yml` | CI: build backend+frontend → GHCR (tag=sha) → `yq` bump `values.yaml` → force-push `deploy` |
| `deploy/argocd/application.yaml` | ArgoCD Application; tracks `deploy` branch, namespace `my-documents-archive` |
| `deploy/helm/my-documents-archive/values.yaml` | Only file CI mutates (`image.*.tag`). NAS source, storage sizes, `stripApiPrefix: false` |
| `deploy/helm/.../templates/backend-deployment.yaml` | Backend: `Recreate`, single replica. Nested mounts: SMB NAS at `/data/library`, local-path PVC overlays `/data/library/.docintell` (keeps SQLite/Chroma off CIFS) |
| `deploy/helm/.../templates/smb-nas.yaml` | SMB CSI PV+PVC for the NAS document library (`//192.168.1.91/Data/my-documents-archive`) |
| `deploy/helm/.../templates/state-pvc.yaml` | local-path PVC for derived state (DB, Chroma, thumbnails, HF cache) |
| `deploy/helm/.../templates/ingress.yaml` | Traefik ingress: `/api`+`/thumbnails`→backend (no strip), `/`→frontend |
| `deploy/helm/.../templates/{frontend-deployment,*-service,_helpers}.yaml` | Frontend Deployment, Services, name/label/image helpers |

**Human-only steps** (cluster access; see spec §6): first build to populate GHCR → make packages public → install SMB CSI driver → create `my-documents-archive-smb-creds` secret (keys `username`/`password`) → `kubectl apply` the ArgoCD Application → add `my-documents-archive.lan` to hosts/DNS. Backfill existing NAS docs via **Admin → Sync** (the watcher is non-recursive + new-files-only).

## Key Data Flow

```
User uploads file
  → POST /api/upload
  → storage.save_uploaded_file() → library/YYYY/MM/filename
  → Document row inserted (ocr_status=pending, analysis_status=pending)
  → thumbnails.generate_thumbnail() [synchronous, before response]
  → BackgroundTasks: indexer.index_document(doc_id)
      → services/ocr.py: Tesseract or external worker
      → services/ai_vision.py (if enabled): capable model returns text + all analysis
        fields in one JSON → indexer applies them and SKIPS analysis below
      → services/ai_analysis.py: OpenAI/Gemini/DeepSeek/... → summary, tags, type, lang, org, amount
        (skipped when vision already produced structured fields)
      → Document updated (analysis_status=done or skipped if no provider)

User searches
  → GET /api/search?query=…&mode=fulltext
  → routers/search.py: SQLite LIKE over ocr_text+filename+summary
  → SearchResponse with highlight snippets

Admin sync
  → POST /api/admin/sync
  → storage.check_library_accessible()  ── 503 abort if disk offline (no deletes)
  → hard-delete docs whose file is missing or inside .docintell (+ their thumbnails)
  → storage.scan_library_for_new_files()  (skips .docintell + hidden dirs)
  → new Document rows inserted (source="sync", date via infer_document_date())
  → BackgroundTasks: index_document() for each new file
  → SyncResponse {found, new_files, removed}

Admin reclassify
  → POST /api/admin/reclassify-all
  → BackgroundTasks: indexer.reclassify_pending_batch()
      → re-runs _run_analysis() for docs with ocr_status=done, analysis_status≠done
```

## Database Location

`library/.docintell/docintell.db` — stays with documents, backed up together.

## Advanced User Mode

Enabled via the **Zap** (⚡) button in the header (persisted to localStorage). When active:
- **OCR Tuning** button appears in DocumentViewer (navigates to `/lab/:id`)
- **Tasks** button appears in the header → opens `TasksPanel`
- **Backup** tab appears in the Admin panel → list/restore DB backups (`BackupTab`)
- **AI Usage** tab appears in the Admin panel → super-user stats/charts/pivot over the `ai_usage` ledger (`UsageTab`)

The super-user screen is gated by Advanced Mode (no separate auth) — same trust model as Backup.

`TasksPanel` shows processing jobs as draggable cards (3-column grid). Task types:
| Type | Description |
|------|-------------|
| `index_unindexed` | OCR + AI analysis for pending documents |
| `sync_library` | Scan library + index new files |
| `reclassify_unclassified` | AI classification for unclassified docs |
| `reclassify_all` | Re-run AI analysis on all docs |
| `recluster` | Cluster-based recategorization of all analyzed docs (silhouette k-selection + LLM naming) |
| `batch_ocr_mistral` | Async batch OCR via Mistral Batch API (50% cheaper) — see [batch-ocr.md](batch-ocr.md) |
| `batch_ocr_gemini` | Async batch OCR via Gemini Batch Mode (50% cheaper) — see [batch-ocr.md](batch-ocr.md) |

Tasks run as FastAPI `BackgroundTasks`, write logs to `task_logs` table, and support soft-stop via a `status="stopped"` flag. The two `batch_ocr_*` tasks are long-running pollers: they submit a remote batch job, then poll every `poll_interval` seconds until the provider finishes (up to 24–48 h).

## Planned (not yet implemented)

- Celery/Redis task queue — replaced by FastAPI BackgroundTasks (sufficient for personal app). `config.redis_url` is dead legacy config; nothing reads it.

## Gotchas (save a grep)

- **App settings**: `/api/admin/settings` accepts any key, but the only key the backend actually reads is `enable_ai_vision` (in `services/indexer.py`). `enable_ai_analysis`, `ai_analysis_model`, `ai_vision_model` in `config.py` are env fallbacks, not DB-backed settings.
- **AI providers live in the DB** (`AIProvider` rows, added via Admin UI), not in env. The `*_api_key` fields in `config.py` are only fallback overrides.
- **Tests**: `npm test` from repo root runs all three suites (backend/compute pytest, frontend vitest). See [testing.md](testing.md). Test files live in `backend/tests/`, `compute/tests/`, and `frontend/src/**/*.test.ts`.
- **Compute worker native crash (Windows+conda)**: On miniforge/miniconda, `import easyocr` → `from skimage import io` triggers an OpenBLAS vs MKL DLL conflict when torch (MKL-linked) is already loaded. Exit code `3228369023` (STATUS_ACCESS_VIOLATION), NOT catchable by `except Exception`. Fix: `pip install numpy scipy scikit-image --force-reinstall`. The worker uses `_probe()` (subprocess) at startup to survive this crash in the probe itself. See [compute-worker.md](compute-worker.md).
- **Classification fields**: `Document` has three classification-tracking columns: `classification_confidence` (float, LLM self-reported), `classification_source` (`"auto"`/`"manual"`), `manually_classified` (bool). Docs with `manually_classified=True` are skipped by the batch reclassify tasks but are re-classified if the user explicitly clicks "Re-classify" in dev mode (`reclassify_document()` resets the flag).
- **`unclassified` vs `other`**: the LLM prompt no longer outputs `"other"` — it outputs `"unclassified"`. Old documents may still have `"other"`; all batch jobs and stats queries treat them identically.
- **Vision can replace Analysis**: for capable providers (OpenAI/Gemini/OpenRouter) Step 3 uses `VISION_FULL_PROMPT` and returns the transcription **plus** every analysis field as one JSON. `indexer._apply_vision_fields()` writes them and sets `analysis_status="done"`, so Step 4 never runs — one API call instead of two. Only **Mistral OCR** (plain transcription) still triggers a separate Analysis step.
- **Batch tasks use Gemini**: `reclassify_unclassified` and `reclassify_all` tasks now submit docs to the Gemini Batch API (same as `batch_analysis_gemini`), using `doc_scope` to select the right document set. The `AIProvider.supports_batch` property is `True` for `gemini` and `mistral`; the Tasks form filters providers by this flag.
- **Sync is now hard-delete**: `/api/admin/sync` `db.delete()`s missing/phantom docs (the old `is_deleted` soft-delete is migrated away — sync also purges any leftover `is_deleted=True` rows). It refuses to run (HTTP 503) if `check_library_accessible()` fails, so an unmounted NAS can't empty the library.
- **Log levels**: every `IndexingLog` row has `level` (`trace|debug|info|warning|error`). The `_log()` helpers default to `info`; pass `level=` to override. The Admin Log tab filters by minimum severity client-side.
