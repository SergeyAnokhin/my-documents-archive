# OCR Lab (calibration screen)

A per-document experimentation screen for comparing how different text-recognition
methods perform on the **same image or first three PDF pages**, and having a "premium" AI model
judge which transcription is best. Opened from the document viewer
("OCR Lab" button) at the route **`/lab/:id`**.

Lab results are **ephemeral by default** — recognition runs do not write to the
`documents` table. However, the user can click the **save (floppy disk) button** on
any result card or the float modal, which calls `POST /api/lab/save` and writes the
chosen OCR text, extracted fields, and model attribution (`ocr_model`) to the document.

All Lab calls are immediate, never Batch. Local OCR and OCR-only models return
text only. Vision analysis models return text plus metadata in one call; text-only
models can analyze the newest OCR result through `POST /api/lab/analyze-text`.
Eligibility is based on per-model capabilities with manual overrides. Normal Save
does not overwrite classification.

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
| `tesseract` | Backend | OCR text only; always available |
| `easyocr` | External worker | OCR text only; shown when `/health` reports EasyOCR |
| Vision OCR/analysis | Selected model with `vision` capability | OCR-only models return text; analysis-capable models use `VISION_METADATA_PROMPT` and return text + metadata, excluding classification |
| Text analysis | Selected model with `text` + `analysis` capabilities | Immediate metadata-only analysis of newest OCR result or saved text; no image |

Image-based methods use the same rendered input: one image or a vertical JPEG of
the first three PDF pages from `ai_vision.load_document_pages()`.

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
| POST | `/lab/analyze-text` | `{ doc_id, provider_id, text }` | Immediate metadata-only result; requires model text+analysis capabilities |
| POST | `/lab/judge` | `{ doc_id, provider_id, use_image, candidates[] }` | `{ rankings[], best, summary, corrected, fields, cost, ms }` |
| POST | `/lab/save` | `{ doc_id, text, fields?, model_name, save_classification? }` | Writes OCR text and fields present in the result; classification is preserved unless `save_classification=true` |

## Code map

| File | Responsibility |
|------|---------------|
| [`backend/app/services/lab.py`](../backend/app/services/lab.py) | Immediate OCR/vision/text-analysis/judge logic and result parsing |
| [`backend/app/routers/lab.py`](../backend/app/routers/lab.py) | `/api/lab/*` endpoints |
| [`frontend/src/pages/LabPage.tsx`](../frontend/src/pages/LabPage.tsx) | The screen orchestrator; route `/lab/:id` (zoom/pan/crop/transform + OCR/vision/judge handlers) |
| [`frontend/src/pages/lab/`](../frontend/src/pages/lab/) | Extracted pieces: `labUtils.ts`, `useLogs.ts`, `usePanelResize.ts`, `FieldChips.tsx`, `ResultsList.tsx`, `JudgePanel.tsx`, `FloatingTextModal.tsx` |

The lab reuses provider-call plumbing via two public helpers added to the pipeline
services (prompt/system are now parameters):
`ai_vision.run_vision(provider, img_bytes, prompt)` and
`ai_analysis.run_text(provider, system, user)`.

Provider usage stats (tokens/cost) **are** still accumulated on the `AIProvider` row
when the judge or a vision method runs — only the document record is left untouched.
