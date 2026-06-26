# Batch OCR (Mistral & Gemini)

Two task types run OCR over many pending documents **asynchronously** through a
provider's batch API, which is billed at ~50 % of the interactive price. Both
live in [`backend/app/routers/tasks.py`](../backend/app/routers/tasks.py) and are
driven from the **Tasks** panel (advanced mode only). They share the same shape:
submit a remote batch job, then poll until the provider finishes (hours, not
seconds), and finally write the transcribed text into `Document.ocr_text`.

| Task type | Function | Provider API | Default model |
|-----------|----------|--------------|---------------|
| `batch_ocr_mistral` | `_batch_ocr_mistral` | Mistral Batch API, `/v1/ocr` endpoint | `mistral-ocr-latest` |
| `batch_ocr_gemini`  | `_batch_ocr_gemini`  | Gemini Batch Mode, `:batchGenerateContent` | `gemini-2.5-flash` |

> Mistral has a dedicated OCR endpoint, so the batch runs true OCR. Gemini has
> **no** OCR endpoint — the batch sends each page to a vision model with a
> verbatim-transcription prompt (`GEMINI_OCR_PROMPT`) and treats the returned
> text as OCR. Both write to the same `ocr_text` / `ocr_status` / `ocr_model`
> columns, so downstream indexing is identical.

## Config (task `config` JSON)

| Key | Default | Meaning |
|-----|---------|---------|
| `limit` | 50 | Max pending documents to include in one batch |
| `provider_id` | (first enabled) | Which `AIProvider` row to use; must match the provider type |
| `poll_interval` | 300 | Seconds between status checks while the job runs |

The Tasks panel loads only enabled providers whose `provider_type` matches the
task (`mistral` for `batch_ocr_mistral`, `gemini` for `batch_ocr_gemini`). If no
matching provider exists, the create button is disabled.

Document selection is identical for both: `ocr_status == "pending"` and
`is_deleted == False`, capped at `limit`. Each request is keyed by the document
id so results can be mapped back.

## Shared flow

```
1. Resolve provider (by provider_id, else first enabled of the right type)
2. Collect up to `limit` pending documents
3. Load first page of each as a resized JPEG (ai_vision.load_first_page)
4. Build a JSONL file, one inline-base64 request per document
5. Upload the JSONL to the provider's Files API
6. Create a batch job pointing at the uploaded file
7. Save the remote job id into Task.result_summary (visible while polling)
8. Poll every `poll_interval`s until the job succeeds / fails
9. Download the results file, parse per-line, write ocr_text back per document
```

Soft-stop: clicking **Stop** sets `status="stopped"`. The poller notices on its
next wake-up and returns — **the remote batch keeps running** on the provider;
only local polling stops. The job id is logged so it can be inspected manually.

## Mistral specifics

- **Auth**: `Authorization: Bearer <api_key>`
- **Upload**: `POST https://api.mistral.ai/v1/files` (multipart, `purpose=batch`) → `id`
- **Create**: `POST https://api.mistral.ai/v1/batch/jobs` with
  `{"input_files": [id], "endpoint": "/v1/ocr", "model": ...}` → job `id`
- **Poll**: `GET https://api.mistral.ai/v1/batch/jobs/{id}` → `status`
  (`QUEUED` / `RUNNING` / `SUCCESS` / `FAILED` / `CANCELLED` / `TIMEOUT_EXCEEDED`)
- **Results**: `GET https://api.mistral.ai/v1/files/{output_file}/content`
- **JSONL request line**: `{"custom_id": "<doc.id>", "body": {"model": ..., "document": {"type": "image_url", "image_url": "data:image/jpeg;base64,..."}, "include_image_base64": false}}`
- **Parsing**: each line is `{"custom_id", "response": {"body": <ocr response>}}` or `{"error": {...}}`; text is joined page markdown via `parse_mistral_ocr()`, which also computes cost (per-page, ~$0.001/page) and applies the provider's `image_policy`.

## Gemini specifics

- **Auth**: `x-goog-api-key: <api_key>`
- **Upload** (resumable, two steps):
  1. `POST https://generativelanguage.googleapis.com/upload/v1beta/files` with
     headers `X-Goog-Upload-Protocol: resumable`, `X-Goog-Upload-Command: start`,
     `X-Goog-Upload-Header-Content-Length`, `X-Goog-Upload-Header-Content-Type: application/jsonl`
     and body `{"file": {"display_name": ...}}` → response header `x-goog-upload-url`
  2. `POST <upload_url>` with `X-Goog-Upload-Command: upload, finalize`,
     `X-Goog-Upload-Offset: 0` and the raw JSONL bytes → `{"file": {"name": "files/..."}}`
- **Create**: `POST .../v1beta/models/{model}:batchGenerateContent` with
  `{"batch": {"display_name": ..., "input_config": {"file_name": "files/..."}}}` → job `name` (`batches/...`)
- **Poll**: `GET .../v1beta/{batch_name}` → state at `metadata.state`
  (`JOB_STATE_PENDING` / `RUNNING` / `SUCCEEDED` / `FAILED` / `CANCELLED` / `EXPIRED`); `done: true` also signals completion. Expiry is 48 h.
- **Results**: file name at `response.responsesFile` (fallbacks: `response.dest.fileName`, `dest.fileName`), then
  `GET .../download/v1beta/{file}:download?alt=media`
- **JSONL request line**: `{"key": "<doc.id>", "request": {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": "<b64>"}}, {"text": GEMINI_OCR_PROMPT}]}], "generation_config": {"max_output_tokens": 8192}}}`
- **Parsing**: each line is `{"key", "response": {"candidates": [{"content": {"parts": [{"text": ...}]}}], "usageMetadata": {...}}}` or `{"key", "error": {...}}`; text is the concatenated `parts[].text`. Token counts are summed into the result summary; **cost is not computed** for Gemini (consistent with the synchronous Gemini vision path).

## Result summary fields

| Field | Both | Notes |
|-------|------|-------|
| `processed` | ✓ | Documents with OCR text saved |
| `failed` | ✓ | Per-document errors + parse errors |
| `batch_job_id` | ✓ | Remote job id (hidden from the card's result chips) |
| `cost_usd` | Mistral only | Per-page OCR cost with batch discount |
| `tokens_in` / `tokens_out` | Gemini only | Summed from `usageMetadata` |

While a job polls, `Task.result_summary` is `{"phase": "polling", "batch_job_id", "doc_count"}`
so the card shows the remote job id.

## References

- Mistral Batch API: <https://docs.mistral.ai/capabilities/batch/>
- Gemini Batch Mode: <https://ai.google.dev/gemini-api/docs/batch-mode>
