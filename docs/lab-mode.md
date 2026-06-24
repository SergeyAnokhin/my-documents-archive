# OCR Lab (calibration screen)

A per-document experimentation screen for comparing how different text-recognition
methods perform on the **same first-page image**, and having a "premium" AI model
judge which transcription is best. Opened from the document viewer
("OCR Lab" button) at the route **`/lab/:id`**.

Everything in the lab is **ephemeral** — no writes to the `documents` table. It is a
tool for deciding which engines/models work best, not part of the indexing pipeline.

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
| AI Vision | Any enabled vision-capable provider (`task_type` = vision/both, type in anthropic/openai/gemini/openrouter/mistral) | Uses the provider as a **verbatim transcriber** (prompt `OCR_VISION_PROMPT`), not the pipeline's "describe" prompt. Mistral OCR ignores the prompt and transcribes natively |

All methods operate on the same first-page JPEG produced by
`ai_vision.load_first_page()`, so comparisons are fair.

## The judge (premium tier)

A new provider `task_type` **`premium`** (configured in Admin → AI Settings →
"Premium Vision (Judge)") is used only here. The judge ranks the candidate
transcriptions and returns JSON `{ rankings:[{label,score,comment}], best, summary }`.

- **With image** (`use_image=true`): the document image plus all transcriptions go to
  the premium vision model, which compares them against the original. Requires a
  vision-capable provider type.
- **Text-only** (`use_image=false`): only the transcriptions are sent; the model
  judges internal readability/coherence. Works with any premium provider.

## Endpoints (`/api/lab`, [`backend/app/routers/lab.py`](../backend/app/routers/lab.py))

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/lab/methods` | — | `{ ocr_methods[], worker_available }` |
| POST | `/lab/ocr` | `{ doc_id, method }` | `{ method, text, ms }` |
| POST | `/lab/vision` | `{ doc_id, provider_id }` | `{ provider_id, name, text, cost, ms }` |
| POST | `/lab/judge` | `{ doc_id, provider_id, use_image, candidates[] }` | `{ rankings[], best, summary, cost, ms }` |

## Code map

| File | Responsibility |
|------|---------------|
| [`backend/app/services/lab.py`](../backend/app/services/lab.py) | OCR/vision/judge logic; prompts `OCR_VISION_PROMPT`, `JUDGE_SYSTEM`; `_parse_json` |
| [`backend/app/routers/lab.py`](../backend/app/routers/lab.py) | `/api/lab/*` endpoints |
| [`frontend/src/pages/LabPage.tsx`](../frontend/src/pages/LabPage.tsx) | The screen; route `/lab/:id` |

The lab reuses provider-call plumbing via two public helpers added to the pipeline
services (prompt/system are now parameters):
`ai_vision.run_vision(provider, img_bytes, prompt)` and
`ai_analysis.run_text(provider, system, user)`.

Provider usage stats (tokens/cost) **are** still accumulated on the `AIProvider` row
when the judge or a vision method runs — only the document record is left untouched.
