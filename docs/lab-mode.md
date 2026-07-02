# OCR Lab (calibration screen)

A per-document experimentation screen for comparing how different text-recognition
methods perform on the **same first-page image**, and having a "premium" AI model
judge which transcription is best. Opened from the document viewer
("OCR Lab" button) at the route **`/lab/:id`**.

Lab results are **ephemeral by default** — recognition runs do not write to the
`documents` table. However, the user can click the **save (floppy disk) button** on
any result card or the float modal, which calls `POST /api/lab/save` and writes the
chosen OCR text, extracted fields, and model attribution (`ocr_model`) to the document.

## Layout

```
┌──────────────────────────────┬─────────────────────────────┐
│  Document (full height,      │  Local OCR   [tesseract][easyocr]
│  zoom for images, native     │  AI Vision OCR  <provider> [Run]
│  PDF viewer for PDFs)        │  Recognized text  ── result cards
│                              │  Judge quality  <premium> [Compare]
└──────────────────────────────┴─────────────────────────────┘
```

Each method produces a **result card** (label, kind badge, char count, elapsed ms,
cost) with the recognized text. Re-running a method replaces its previous card
(matched by label). The judge highlights the winning card with a trophy.

## Recognition methods

| Method | Where it runs | Notes |
|--------|--------------|-------|
| `tesseract` | In-process (backend, pytesseract) | Always available |
| `easyocr` | External compute worker `/ocr?engine=easyocr` | Only if the worker is reachable (`GET /lab/methods` probes `/health`) |
| AI Vision | Any enabled vision-capable provider (`task_type` = vision/both, type in openai/gemini/openrouter/mistral) | Uses the combined `VISION_ANALYSIS_PROMPT` — returns JSON with `text` (transcription) + `fields` (summary, title, document_type(+confidence), date, names, org, amount, language, tags). Mistral OCR ignores the prompt and returns plain text; `_parse_vision_analysis()` falls back gracefully. |

All methods operate on the same first-page JPEG produced by
`ai_vision.load_first_page()`, so comparisons are fair.

## The judge (premium tier)

A new provider `task_type` **`premium`** (configured in Admin → AI Settings →
"Premium Vision (Judge)") is used only here. The judge ranks the candidate
transcriptions and returns JSON `{ rankings:[{label,score,comment}], best, summary, corrected, fields }`.

- **With image** (`use_image=true`): the document image plus all transcriptions go to
  the premium vision model, which compares them against the original. Requires a
  vision-capable provider type.
- **Text-only** (`use_image=false`): only the transcriptions are sent; the model
  judges internal readability/coherence. Works with any premium provider.
- **`fields`**: the judge also extracts structured metadata (document_type, date, names, org,
  amount, language, tags — **not** `summary`/`title`, unlike the vision/OCR-analysis paths;
  the judge only compares transcription quality, it doesn't re-summarize the document)
  from its own analysis — shown in the UI and can be saved to the document.

## Endpoints (`/api/lab`, [`backend/app/routers/lab.py`](../backend/app/routers/lab.py))

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/lab/methods` | — | `{ ocr_methods[], worker_available }` |
| POST | `/lab/ocr` | `{ doc_id, method }` | `{ method, text, ms }` |
| POST | `/lab/vision` | `{ doc_id, provider_id }` | `{ provider_id, name, model_name, text, fields, cost, ms }` |
| POST | `/lab/judge` | `{ doc_id, provider_id, use_image, candidates[] }` | `{ rankings[], best, summary, corrected, fields, cost, ms }` |
| POST | `/lab/save` | `{ doc_id, text, fields?, model_name }` | `{ ok, doc_id }` — writes OCR text + extracted fields (`summary`, `title`, `document_type`(+confidence), `tags`, etc. — each field is replaced outright, not merged, when present in the result) + attribution to the document |

## Code map

| File | Responsibility |
|------|---------------|
| [`backend/app/services/lab.py`](../backend/app/services/lab.py) | OCR/vision/judge logic; prompts `OCR_VISION_PROMPT`, `JUDGE_SYSTEM`; `_parse_json` |
| [`backend/app/routers/lab.py`](../backend/app/routers/lab.py) | `/api/lab/*` endpoints |
| [`frontend/src/pages/LabPage.tsx`](../frontend/src/pages/LabPage.tsx) | The screen orchestrator; route `/lab/:id` (zoom/pan/crop/transform + OCR/vision/judge handlers) |
| [`frontend/src/pages/lab/`](../frontend/src/pages/lab/) | Extracted pieces: `labUtils.ts`, `useLogs.ts`, `usePanelResize.ts`, `FieldChips.tsx`, `ResultsList.tsx`, `JudgePanel.tsx`, `FloatingTextModal.tsx` |

The lab reuses provider-call plumbing via two public helpers added to the pipeline
services (prompt/system are now parameters):
`ai_vision.run_vision(provider, img_bytes, prompt)` and
`ai_analysis.run_text(provider, system, user)`.

Provider usage stats (tokens/cost) **are** still accumulated on the `AIProvider` row
when the judge or a vision method runs — only the document record is left untouched.
