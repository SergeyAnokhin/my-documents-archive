# Batch Tasks (Mistral & Gemini)

Five task types run AI processing **asynchronously** through a provider's batch
API, billed at ~50 % of the interactive price. All are dispatched from
[`backend/app/services/task_runners.py`](../backend/app/services/task_runners.py)
(endpoints in `routers/tasks.py`) and are driven from the **Tasks** panel
(advanced mode only).

## Task types

| Task type | Service | Provider API | Document scope |
|-----------|---------|--------------|----------------|
| `batch_ocr_mistral` | `batch_ocr.py` | Mistral Batch `/v1/ocr` | `ocr_status="pending"` |
| `batch_ocr_gemini`  | `batch_ocr.py` | Gemini `:batchGenerateContent` | scope-selected (see below); **per-document hybrid** vision/text routing |
| `batch_analysis_gemini` | `batch_analysis.py` | Gemini `:batchGenerateContent` | has `ocr_text`, no analysis yet — **internal only**, not directly creatable from the Tasks UI; used by `reclassify_unclassified`/`reclassify_all` below |
| `reclassify_unclassified` | `batch_analysis.py` | Gemini `:batchGenerateContent` | `ocr_done`, type = unclassified/other, not manually set |
| `reclassify_all` | `batch_analysis.py` | Gemini `:batchGenerateContent` | `ocr_done`, `analysis_status != "done"` |

> Mistral has a dedicated OCR endpoint for true OCR — it always sends the image,
> since `/v1/ocr` has no text-only mode. Gemini has **no** OCR endpoint, so the
> batch sends each page to a vision model with a verbatim-transcription prompt
> and treats the returned text as OCR — but Gemini *can* also analyze plain text,
> so `batch_ocr_gemini` skips the image entirely for any document that already
> has OCR text (see **Hybrid vision/text routing** below).
>
> `reclassify_unclassified` and `reclassify_all` are thin wrappers that call
> `run_batch_analysis_gemini()` (in `batch_analysis.py`) with a `doc_scope`
> parameter selecting the appropriate document set — always text-only, since by
> definition these documents already have OCR text. This makes them 2× cheaper
> at the cost of async turnaround (up to 24 h). `batch_analysis_gemini` is not
> offered as its own card in the Tasks "create" modal — it only runs as the
> engine behind those two reclassify tasks (or via a direct API call / resume).

## Hybrid vision/text routing (`batch_ocr_gemini`)

Sending images to Gemini costs image tokens; sending text-only is much cheaper.
`run_batch_ocr_gemini()` decides per document via `_needs_vision(doc)`
([`batch_ocr.py`](../backend/app/services/batch_ocr.py)):

| Document state | Mode | Request sent |
|-----------------|------|---------------|
| No `ocr_text` yet | **vision** | first-page image + `VISION_FULL_PROMPT` → transcription + all analysis fields in one call |
| `ocr_text` already exists, from *any* engine — including local `tesseract`/`easyocr` | **text-only** | existing `ocr_text` (first 4000 chars) + `ANALYSIS_SYSTEM` → analysis fields only, no image, `ocr_text`/`ocr_model` left untouched |

Local-engine text is **not** re-transcribed via vision: if it was kept rather
than re-OCR'd, its quality is assumed acceptable, so only the cheaper
text-only analysis pass runs. This means a single `batch_ocr_gemini` run at
scope 2+ (which includes local-OCR'd documents) will mix both request types in
the same JSONL batch — Gemini batch lines are independent, so this is safe.
Task logs show which mode was used per document (🖼️ image sent / 📝 text-only,
no image) and a `📊 N via image, M via text-only` summary before upload. The
final `result_summary` includes `vision_count` / `text_count` alongside
`processed`/`failed`.

## `.docx`/`.txt` documents (no page image)

Both batch runners select documents purely by `ocr_status`/`ocr_text` state —
they don't filter by file format. A `.docx`/`.txt` has no rendered page, so
neither provider can OCR it; each runner detects it (`indexer._is_native_text`)
and extracts its text natively via `indexer._extract_native_text()` — which
dispatches to `docx_extract.extract_docx_text()` or `text_extract.extract_text_file()`
by extension (free, local, no API call) — **before** deciding what to send:

- **`batch_ocr_mistral`**: the document is extracted and marked
  `ocr_status="done"`, `ocr_model="native"`, `vision_status="skipped"` —  it is
  **excluded from the Mistral JSONL entirely** (there's nothing to send to
  `/v1/ocr`). Its count is folded into `result_summary["processed"]` and
  surfaced separately as `result_summary["native"]`. If every document in the
  scope turns out to be `.docx`/`.txt`, the task finishes `"done"` without ever
  calling the Mistral API.
- **`batch_ocr_gemini`**: since this runner also handles analysis, the
  extracted text simply makes `_needs_vision(doc)` become `False`, so the
  document falls through into the existing **text-only** branch (see Hybrid
  routing above) and still gets analysis via the same batch job — no separate
  handling needed downstream.

A failed native extraction (corrupt/encrypted docx, unreadable txt) sets
`ocr_status="error"` with the exception message, same contract as an OCR
failure, and the document is excluded from that run's batch request.

**Practical effect**: your normal two-step habit (batch OCR → batch analysis)
works unchanged for a mixed batch of scans, Word documents, and plain text —
`.docx`/`.txt` files just skip the OCR/vision step for free instead of being
silently dropped.

## Provider batch support

`AIProvider.supports_batch` is a computed property (`True` for `gemini` and
`mistral`). It is exposed in `AIProviderOut` so the Tasks UI can filter the
provider picker to only batch-capable providers for batch tasks.

## Config (task `config` JSON)

| Key | Default | Meaning |
|-----|---------|---------|
| `limit` | 50 | Max pending documents to include in one batch |
| `provider_id` | (first enabled) | Which `AIProvider` row to use; must match the provider type |
| `poll_interval` | 30 | Seconds between status checks while the job runs |
| `doc_scope` | `needs_analysis` | Which documents to include (analysis tasks only): `needs_analysis` — has `ocr_text`, no analysis or unclassified; `unclassified` — `ocr_done`, type is `unclassified`/`other`, not manually set; `pending` — `ocr_done`, `analysis_status != "done"` |

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
3. Load first page of each as a resized JPEG (ai_vision.load_first_page) —
   for `batch_ocr_gemini`, only documents in **vision** mode (see hybrid
   routing above); text-mode documents reuse the existing `ocr_text` instead
4. Build a JSONL file, one inline-base64 (vision) or plain-text (Gemini
   text-only) request per document
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

## Resume support

`POST /api/tasks/{task_id}/resume-batch` restarts polling for a stopped or interrupted job without re-submitting it. Supported task types: `batch_ocr_mistral`, `batch_ocr_gemini`, `batch_analysis_gemini`, `reclassify_unclassified`, `reclassify_all`. The original `batch_job_id` is read from `Task.result_summary`.

### Automatic recovery on backend restart

Polling runs as an in-process `asyncio` coroutine (FastAPI `BackgroundTasks`) — there is no separate worker process. If the backend pod restarts mid-poll (e.g. a `kubectl rollout restart` during an overnight Mistral run), the coroutine simply dies; the remote batch job is **not** affected, since it keeps running on the provider's servers (up to 24 h Mistral / 48 h Gemini) and `batch_job_id` was already persisted to `Task.result_summary` before polling started.

`recover_running_tasks()` ([`backend/app/services/task_runners.py`](../backend/app/services/task_runners.py)) runs once at app startup (wired in `main.py`) and sweeps every `Task` left at `status="running"`:

- Batch task with a saved `batch_job_id` → auto-resumed (same as `resume-batch`, status stays `"running"`).
- Anything else (batch task with no job id yet, or a non-batch task type) → reset to `"stopped"` so the Run/Resume buttons work again; any per-document work already committed before the restart is preserved.

## Batch result download

After a successful batch run the raw JSONL response is saved to `.docintell/batch_results/task_{id}.jsonl`. Retrieve it with:

`GET /api/tasks/{task_id}/batch-result` → downloads `batch_result_task_{id}.jsonl` (application/octet-stream)

Useful for debugging parse errors or auditing what the provider returned.

## Result summary fields

| Field | Both | Notes |
|-------|------|-------|
| `processed` | ✓ | Documents with OCR text saved |
| `failed` | ✓ | Per-document errors + parse errors |
| `batch_job_id` | ✓ | Remote job id (hidden from the card's result chips) |
| `cost_usd` | Mistral only | Per-page OCR cost with batch discount |
| `tokens_in` / `tokens_out` | Gemini only | Summed from `usageMetadata` |
| `native` | Mistral only, when present | Count of `.docx`/`.txt` documents handled via native text extraction (already folded into `processed`) |

While a job polls, `Task.result_summary` is `{"phase": "polling", "batch_job_id", "doc_count"}`
so the card shows the remote job id.

## References

- Mistral Batch API: <https://docs.mistral.ai/capabilities/batch/>
- Gemini Batch Mode: <https://ai.google.dev/gemini-api/docs/batch-mode>
