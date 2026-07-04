# Document Processing Map

Normal indexing is lazy: it reuses existing text, skips documents whose metadata
analysis is complete, and never changes classification. Before starting, the
Tasks panel shows route counts, estimated pages, and approximate provider cost.

## Indexing routes

| Route | Missing text | Existing text | Metadata | Classification |
|---|---|---|---|---|
| Mistral Batch + Gemini text | Mistral OCR Batch | Reused | Gemini text Batch | Unchanged |
| Local OCR + Gemini text | Native extraction/Tesseract/worker | Reused | Gemini text Batch | Unchanged |
| Gemini complete | Gemini vision Batch | Image omitted | Same Gemini Batch request | Unchanged |

TXT and DOCX are read locally. Existing PDF/image text is never replaced during
normal indexing. AI image requests include up to the first three PDF pages.
Embeddings are rebuilt locally after metadata is saved.

## File handling

| File | Free path | Visual path |
|---|---|---|
| TXT | Read file | Not applicable |
| DOCX | Extract paragraphs and tables | Not applicable |
| PDF with stored text | Reuse text | No image sent |
| Scanned PDF | Local OCR, Mistral Batch, or Gemini Batch | First 3 pages for AI requests |
| Image | Local OCR, Mistral Batch, or Gemini Batch | Single image |

## Classification

Classification is independent. `reclassify_unclassified` and `reclassify_all`
use Gemini Batch with a classification-only response and do not regenerate
metadata. Manual types are excluded. `recluster` remains taxonomy maintenance.

## OCR Lab and model capabilities

Lab calls are immediate, never Batch. Local OCR and Mistral return text only.
Vision analysis models return text plus metadata; text-only models can analyze
the newest OCR result or saved text. Normal Save does not overwrite classification.

Capabilities are inferred per model and manual overrides are stored under
`AIProvider.extra_params.capabilities`: `text`, `vision`, `ocr`, `analysis`, and
`batch`.
