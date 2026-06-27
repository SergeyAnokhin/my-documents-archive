"""Async batch-OCR task runners — Mistral Batch API and Gemini Batch Mode.

Both submit a remote batch job, then poll every `poll_interval` seconds until the
provider finishes (up to 24–48 h), and write the transcription back to each
Document. Split out of routers/tasks.py to keep that router focused on CRUD.
See docs/batch-ocr.md.
"""
import asyncio
import base64
import json

import httpx
from sqlalchemy import or_

from ..database import SessionLocal
from ..models import AIProvider, Document, Task
from .task_runtime import (
    finish as _finish,
    is_stopped as _is_stopped,
    log_task as _log,
    set_progress as _set_progress,
)
from .ai_vision import VISION_FULL_PROMPT
from .ai_common import strip_code_fences


_LOCAL_OCR_MODELS = {"tesseract", "easyocr"}


def _scope_filter(query, scope: int):
    """Return query filtered to documents that qualify for re-OCR at the given scope (cumulative ≤ N).

    Scope 1: no extracted text at all.
    Scope 2: +documents with local-only OCR (Tesseract / EasyOCR).
    Scope 3: +documents that have AI OCR text but no AI analysis yet.
    Scope 4: all non-deleted documents (full reprocessing).
    """
    base = Document.is_deleted == False
    if scope <= 1:
        return query.filter(base, Document.ocr_text.is_(None))
    if scope == 2:
        return query.filter(
            base,
            or_(
                Document.ocr_text.is_(None),
                Document.ocr_model.is_(None),
                Document.ocr_model.in_(_LOCAL_OCR_MODELS),
            ),
        )
    if scope == 3:
        return query.filter(
            base,
            or_(
                Document.ocr_text.is_(None),
                Document.analysis_status != "done",
            ),
        )
    # scope 4: all
    return query.filter(base)


async def run_batch_ocr_mistral(task_id: int, config: dict) -> None:
    """
    Mistral Batch OCR — uses Mistral's Batch API (50 % cheaper, async).

    Flow:
      1. Load first page of each pending document as JPEG.
      2. Build a JSONL file with inline-base64 OCR requests.
      3. Upload JSONL to Mistral Files API.
      4. Create a batch job pointing at that file.
      5. Poll every `poll_interval` seconds until the job completes.
      6. Download the output file and save OCR text back to each document.
    """
    from .ai_vision import load_first_page, parse_mistral_ocr

    limit = int(config.get("limit", 50))
    provider_id = config.get("provider_id")
    poll_interval = int(config.get("poll_interval", 300))

    # ── 1. Resolve Mistral provider ──────────────────────────────────────────
    db = SessionLocal()
    try:
        if provider_id:
            provider = db.query(AIProvider).filter(
                AIProvider.id == int(provider_id),
                AIProvider.provider_type == "mistral",
            ).first()
        else:
            provider = None

        if not provider:
            provider = db.query(AIProvider).filter(
                AIProvider.provider_type == "mistral",
                AIProvider.enabled == True,
            ).order_by(AIProvider.sort_order).first()

        if not provider:
            _log(task_id, "No Mistral provider configured — add one in AI Settings", "error")
            _finish(task_id, "error")
            return

        api_key = provider.api_key
        model = provider.model or "mistral-ocr-latest"
        image_policy = (provider.extra_params or {}).get("image_policy", "placeholder")

        # ── 2. Collect documents by scope ─────────────────────────────────────
        scope = int(config.get("scope", 1))
        docs = _scope_filter(db.query(Document), scope).limit(limit).all()
        total = len(docs)
    finally:
        db.close()

    if total == 0:
        _log(task_id, "No documents found for the selected scope")
        _finish(task_id, "done", {"processed": 0})
        return

    _log(task_id, f"Found {total} document(s) — model: {model}")
    _set_progress(task_id, 0, total)

    # ── 3. Build JSONL (inline base64) ───────────────────────────────────────
    _log(task_id, "Loading document images…")
    jsonl_lines: list[str] = []
    doc_id_map: dict[str, int] = {}   # custom_id (str doc.id) → doc.id

    for i, doc in enumerate(docs):
        if _is_stopped(task_id):
            _log(task_id, f"Stopped during image loading after {i} document(s)")
            return
        try:
            img_bytes = load_first_page(doc.filepath)
            b64 = base64.b64encode(img_bytes).decode()
            custom_id = str(doc.id)
            doc_id_map[custom_id] = doc.id
            jsonl_lines.append(json.dumps({
                "custom_id": custom_id,
                "body": {
                    "model": model,
                    "document": {
                        "type": "image_url",
                        "image_url": f"data:image/jpeg;base64,{b64}",
                    },
                    "include_image_base64": False,
                },
            }))
            _log(task_id, f"✓ Loaded: {doc.filename}")
        except Exception as exc:
            _log(task_id, f"✗ {doc.filename}: cannot load image — {exc}", "error")
        _set_progress(task_id, i + 1, total)

    if not jsonl_lines:
        _log(task_id, "No document images could be loaded", "error")
        _finish(task_id, "error")
        return

    # ── 4. Upload JSONL to Mistral Files API ─────────────────────────────────
    _log(task_id, f"Uploading batch ({len(jsonl_lines)} requests) to Mistral…")
    jsonl_bytes = "\n".join(jsonl_lines).encode()

    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=180) as client:
        upload_resp = await client.post(
            "https://api.mistral.ai/v1/files",
            headers=headers,
            files={"file": ("batch_ocr.jsonl", jsonl_bytes, "application/jsonl")},
            data={"purpose": "batch"},
        )
        upload_resp.raise_for_status()
        input_file_id = upload_resp.json()["id"]

    _log(task_id, f"Uploaded input file: {input_file_id}")

    # ── 5. Create batch job ──────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=60) as client:
        batch_resp = await client.post(
            "https://api.mistral.ai/v1/batch/jobs",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "input_files": [input_file_id],
                "endpoint": "/v1/ocr",
                "model": model,
            },
        )
        batch_resp.raise_for_status()
        batch_data = batch_resp.json()

    batch_job_id = batch_data["id"]
    _log(task_id, f"Batch job created: {batch_job_id}")

    # Save job ID so it's visible in result_summary during polling
    db = SessionLocal()
    try:
        task_row = db.query(Task).filter(Task.id == task_id).first()
        if task_row:
            task_row.result_summary = {
                "phase": "polling",
                "batch_job_id": batch_job_id,
                "doc_count": len(jsonl_lines),
            }
            db.commit()
    finally:
        db.close()

    # ── 6. Poll until complete ────────────────────────────────────────────────
    _log(task_id, f"Job submitted. Polling every {poll_interval}s… (up to 24 h)")

    while True:
        await asyncio.sleep(poll_interval)

        if _is_stopped(task_id):
            _log(task_id, f"Stopped by user. Batch job {batch_job_id} is still running on Mistral.")
            return

        async with httpx.AsyncClient(timeout=30) as client:
            status_resp = await client.get(
                f"https://api.mistral.ai/v1/batch/jobs/{batch_job_id}",
                headers=headers,
            )
            status_resp.raise_for_status()
            job_data = status_resp.json()

        job_status = job_data.get("status", "UNKNOWN")
        succeeded = job_data.get("succeeded_requests", 0)
        failed_req = job_data.get("failed_requests", 0)
        _log(task_id, f"Status: {job_status} — succeeded: {succeeded}, failed: {failed_req}")

        if job_status == "SUCCESS":
            break
        if job_status in ("FAILED", "CANCELLED", "TIMEOUT_EXCEEDED"):
            _log(task_id, f"Batch job ended with status: {job_status}", "error")
            _finish(task_id, "error", {"batch_job_id": batch_job_id, "status": job_status})
            return
        # Still pending (QUEUED / RUNNING / VALIDATING) — keep polling

    # ── 7. Download and parse results ────────────────────────────────────────
    output_file_id = job_data.get("output_file")
    if not output_file_id:
        _log(task_id, "Batch completed but no output_file in response", "error")
        _finish(task_id, "error")
        return

    _log(task_id, f"Downloading results from {output_file_id}…")
    async with httpx.AsyncClient(timeout=180) as client:
        results_resp = await client.get(
            f"https://api.mistral.ai/v1/files/{output_file_id}/content",
            headers=headers,
        )
        results_resp.raise_for_status()
        results_text = results_resp.text

    # ── 8. Save OCR text to documents ────────────────────────────────────────
    _log(task_id, "Saving OCR results to documents…")
    processed = 0
    failed_count = 0
    total_cost = 0.0

    db = SessionLocal()
    try:
        for line in results_text.strip().splitlines():
            if not line.strip():
                continue
            try:
                result_obj = json.loads(line)
                custom_id = result_obj.get("custom_id", "")
                doc_id = doc_id_map.get(custom_id)
                if not doc_id:
                    continue

                if result_obj.get("error"):
                    err_msg = result_obj["error"].get("message", "Unknown Mistral error")
                    _log(task_id, f"✗ Doc {doc_id}: {err_msg}", "error")
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.ocr_status = "error"
                        doc.ocr_error = err_msg
                        db.commit()
                    failed_count += 1
                    continue

                # response.body = OCR response dict
                ocr_body = (result_obj.get("response") or {}).get("body") or {}
                text, cost = parse_mistral_ocr(ocr_body, image_policy)
                total_cost += cost

                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.ocr_text = text
                    doc.ocr_status = "done"
                    doc.ocr_model = f"{model} (batch)"
                    doc.api_cost_vision = (doc.api_cost_vision or 0.0) + cost
                    db.commit()
                    _log(task_id, f"✓ Saved OCR for doc {doc_id}")
                    processed += 1

            except Exception as exc:
                _log(task_id, f"✗ Result parse error: {exc}", "error")
                failed_count += 1
    finally:
        db.close()

    summary = {
        "processed": processed,
        "failed": failed_count,
        "cost_usd": round(total_cost, 5),
        "batch_job_id": batch_job_id,
    }
    _finish(task_id, "done", summary)
    _log(task_id, (
        f"Done — {processed} saved, {failed_count} failed, "
        f"cost ${total_cost:.5f} (batch discount applied)"
    ))


GEMINI_BATCH_BASE = "https://generativelanguage.googleapis.com"


async def run_batch_ocr_gemini(task_id: int, config: dict) -> None:
    """
    Gemini Batch OCR — uses Google Gemini's Batch Mode (50 % cheaper, async).

    Gemini has no dedicated OCR endpoint, so we send each document's first page
    to a vision model with VISION_FULL_PROMPT and store both the verbatim text
    (ocr_text) and all analysis fields (summary, document_type, tags, etc.) in
    one pass — equivalent to what the synchronous vision pipeline does.

    Flow (REST, mirrors `run_batch_ocr_mistral`):
      1. Load first page of each pending document as JPEG.
      2. Build a JSONL file with inline-base64 generateContent requests.
      3. Upload JSONL via the Files API (resumable upload).
      4. Create a batch job (models/{model}:batchGenerateContent).
      5. Poll every `poll_interval` seconds until JOB_STATE_SUCCEEDED.
      6. Download the responses file and save OCR text back to each document.
    """
    from .ai_vision import load_first_page

    limit = int(config.get("limit", 50))
    provider_id = config.get("provider_id")
    poll_interval = int(config.get("poll_interval", 300))

    # ── 1. Resolve Gemini provider ───────────────────────────────────────────
    db = SessionLocal()
    try:
        if provider_id:
            provider = db.query(AIProvider).filter(
                AIProvider.id == int(provider_id),
                AIProvider.provider_type == "gemini",
            ).first()
        else:
            provider = None

        if not provider:
            provider = db.query(AIProvider).filter(
                AIProvider.provider_type == "gemini",
                AIProvider.enabled == True,
            ).order_by(AIProvider.sort_order).first()

        if not provider:
            _log(task_id, "No Gemini provider configured — add one in AI Settings", "error")
            _finish(task_id, "error")
            return

        api_key = provider.api_key
        model = provider.model or "gemini-2.5-flash"

        # ── 2. Collect documents by scope ─────────────────────────────────────
        scope = int(config.get("scope", 1))
        docs = _scope_filter(db.query(Document), scope).limit(limit).all()
        total = len(docs)
    finally:
        db.close()

    if total == 0:
        _log(task_id, "No pending documents found")
        _finish(task_id, "done", {"processed": 0})
        return

    _log(task_id, f"Found {total} document(s) — model: {model}")
    _set_progress(task_id, 0, total)

    # ── 3. Build JSONL (inline base64) ───────────────────────────────────────
    _log(task_id, "Loading document images…")
    jsonl_lines: list[str] = []
    doc_id_map: dict[str, int] = {}   # key (str doc.id) → doc.id

    for i, doc in enumerate(docs):
        if _is_stopped(task_id):
            _log(task_id, f"Stopped during image loading after {i} document(s)")
            return
        try:
            img_bytes = load_first_page(doc.filepath)
            b64 = base64.b64encode(img_bytes).decode()
            key = str(doc.id)
            doc_id_map[key] = doc.id
            jsonl_lines.append(json.dumps({
                "key": key,
                "request": {
                    "contents": [{
                        "parts": [
                            {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                            {"text": VISION_FULL_PROMPT},
                        ],
                    }],
                    "generation_config": {"max_output_tokens": 16384},
                },
            }))
            _log(task_id, f"✓ Loaded: {doc.filename}")
        except Exception as exc:
            _log(task_id, f"✗ {doc.filename}: cannot load image — {exc}", "error")
        _set_progress(task_id, i + 1, total)

    if not jsonl_lines:
        _log(task_id, "No document images could be loaded", "error")
        _finish(task_id, "error")
        return

    jsonl_bytes = ("\n".join(jsonl_lines)).encode()
    key_header = {"x-goog-api-key": api_key}

    # ── 4. Upload JSONL via Files API (resumable upload) ──────────────────────
    _log(task_id, f"Uploading batch ({len(jsonl_lines)} requests) to Gemini…")
    async with httpx.AsyncClient(timeout=180) as client:
        start_resp = await client.post(
            f"{GEMINI_BATCH_BASE}/upload/v1beta/files",
            headers={
                **key_header,
                "X-Goog-Upload-Protocol": "resumable",
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(jsonl_bytes)),
                "X-Goog-Upload-Header-Content-Type": "application/jsonl",
                "Content-Type": "application/json",
            },
            json={"file": {"display_name": f"docintel_ocr_{task_id}"}},
        )
        start_resp.raise_for_status()
        upload_url = start_resp.headers.get("x-goog-upload-url")
        if not upload_url:
            _log(task_id, "Gemini did not return an upload URL", "error")
            _finish(task_id, "error")
            return

        upload_resp = await client.post(
            upload_url,
            headers={
                "Content-Length": str(len(jsonl_bytes)),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
            },
            content=jsonl_bytes,
        )
        upload_resp.raise_for_status()
        input_file_name = upload_resp.json()["file"]["name"]   # files/xxxx

    _log(task_id, f"Uploaded input file: {input_file_name}")

    # ── 5. Create batch job ──────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=60) as client:
        batch_resp = await client.post(
            f"{GEMINI_BATCH_BASE}/v1beta/models/{model}:batchGenerateContent",
            headers={**key_header, "Content-Type": "application/json"},
            json={
                "batch": {
                    "display_name": f"docintel-ocr-{task_id}",
                    "input_config": {"file_name": input_file_name},
                },
            },
        )
        batch_resp.raise_for_status()
        batch_data = batch_resp.json()

    batch_job_name = batch_data["name"]   # e.g. batches/xxxx
    _log(task_id, f"Batch job created: {batch_job_name}")

    # Save job name so it's visible in result_summary during polling
    db = SessionLocal()
    try:
        task_row = db.query(Task).filter(Task.id == task_id).first()
        if task_row:
            task_row.result_summary = {
                "phase": "polling",
                "batch_job_id": batch_job_name,
                "doc_count": len(jsonl_lines),
            }
            db.commit()
    finally:
        db.close()

    # ── 6. Poll until complete ────────────────────────────────────────────────
    _log(task_id, f"Job submitted. Polling every {poll_interval}s… (up to 48 h)")

    job_data: dict = {}
    while True:
        await asyncio.sleep(poll_interval)

        if _is_stopped(task_id):
            _log(task_id, f"Stopped by user. Batch job {batch_job_name} is still running on Gemini.")
            return

        async with httpx.AsyncClient(timeout=30) as client:
            status_resp = await client.get(
                f"{GEMINI_BATCH_BASE}/v1beta/{batch_job_name}",
                headers=key_header,
            )
            status_resp.raise_for_status()
            job_data = status_resp.json()

        meta = job_data.get("metadata") or {}
        job_status = meta.get("state") or job_data.get("state") or "JOB_STATE_UNSPECIFIED"
        _log(task_id, f"Status: {job_status}")

        if job_status == "JOB_STATE_SUCCEEDED" or job_data.get("done"):
            break
        if job_status in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
            err = (job_data.get("error") or {}).get("message", job_status)
            _log(task_id, f"Batch job ended with status: {job_status} — {err}", "error")
            _finish(task_id, "error", {"batch_job_id": batch_job_name, "status": job_status})
            return
        # Still pending (JOB_STATE_PENDING / JOB_STATE_RUNNING) — keep polling

    # ── 7. Download and parse results ────────────────────────────────────────
    response_obj = job_data.get("response") or {}
    output_file_name = (
        response_obj.get("responsesFile")
        or (response_obj.get("dest") or {}).get("fileName")
        or (job_data.get("dest") or {}).get("fileName")
    )
    if not output_file_name:
        _log(task_id, "Batch completed but no responses file in response", "error")
        _finish(task_id, "error")
        return

    _log(task_id, f"Downloading results from {output_file_name}…")
    async with httpx.AsyncClient(timeout=180) as client:
        results_resp = await client.get(
            f"{GEMINI_BATCH_BASE}/download/v1beta/{output_file_name}:download",
            headers=key_header,
            params={"alt": "media"},
        )
        results_resp.raise_for_status()
        results_text = results_resp.text

    # ── 8. Save OCR text to documents ────────────────────────────────────────
    _log(task_id, "Saving OCR results to documents…")
    processed = 0
    failed_count = 0
    tokens_in = 0
    tokens_out = 0

    db = SessionLocal()
    try:
        for line in results_text.strip().splitlines():
            if not line.strip():
                continue
            try:
                result_obj = json.loads(line)
                key = result_obj.get("key", "")
                doc_id = doc_id_map.get(key)
                if not doc_id:
                    continue

                if result_obj.get("error"):
                    err_msg = result_obj["error"].get("message", "Unknown Gemini error")
                    _log(task_id, f"✗ Doc {doc_id}: {err_msg}", "error")
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc:
                        doc.ocr_status = "error"
                        doc.ocr_error = err_msg
                        db.commit()
                    failed_count += 1
                    continue

                resp_body = result_obj.get("response") or {}
                candidates = resp_body.get("candidates") or []
                parts = (candidates[0].get("content", {}).get("parts", [])) if candidates else []
                text = "".join(p.get("text", "") for p in parts).strip()

                usage = resp_body.get("usageMetadata") or {}
                tokens_in += usage.get("promptTokenCount", 0)
                tokens_out += usage.get("candidatesTokenCount", 0)

                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    try:
                        parsed = json.loads(strip_code_fences(text))
                    except Exception:
                        parsed = None

                    if parsed and isinstance(parsed, dict) and parsed.get("text"):
                        doc.ocr_text = parsed["text"]
                        doc.ocr_status = "done"
                        doc.ocr_model = f"{model} (batch)"
                        doc.summary = parsed.get("summary", "")
                        doc.document_type = parsed.get("document_type", "unclassified")
                        doc.document_type_confidence = float(parsed.get("document_type_confidence") or 0.0)
                        tags = parsed.get("tags") or []
                        doc.tags = json.dumps(tags, ensure_ascii=False)
                        doc.language = parsed.get("language", "")
                        doc.organization = parsed.get("organization")
                        amount = parsed.get("amount")
                        doc.amount = float(amount) if amount is not None else None
                        doc.amount_currency = parsed.get("amount_currency")
                        doc.person_first_name = parsed.get("person_first_name")
                        doc.person_last_name = parsed.get("person_last_name")
                        doc.document_date = parsed.get("document_date")
                        short_title = parsed.get("short_title", "")
                        if short_title:
                            doc.short_title = short_title
                        doc.analysis_status = "done"
                        doc.analysis_model = f"{model} (batch)"
                        db.commit()
                        _log(task_id, f"✓ OCR + analysis saved for doc {doc_id}")
                        processed += 1
                    else:
                        # JSON parse failed — save raw text as OCR only, leave analysis pending
                        doc.ocr_text = text
                        doc.ocr_status = "done"
                        doc.ocr_model = f"{model} (batch)"
                        db.commit()
                        _log(task_id, f"⚠ Doc {doc_id}: saved raw OCR text (JSON parse failed)", "error")
                        processed += 1

            except Exception as exc:
                _log(task_id, f"✗ Result parse error: {exc}", "error")
                failed_count += 1
    finally:
        db.close()

    summary = {
        "processed": processed,
        "failed": failed_count,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "batch_job_id": batch_job_name,
    }
    _finish(task_id, "done", summary)
    _log(task_id, (
        f"Done — {processed} OCR+analyzed, {failed_count} failed, "
        f"{tokens_in}+{tokens_out} tokens (batch discount applied)"
    ))
