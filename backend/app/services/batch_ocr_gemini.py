"""Gemini Batch OCR runner — see docs/batch-ocr.md.

Split out of batch_ocr.py to keep each provider's integration in its own file.
Shared document-scope filtering and the vision-vs-text routing rule live in
batch_ocr.py.
"""
import asyncio
import base64
import json
from datetime import datetime

import httpx

from ..database import SessionLocal
from ..models import AIProvider, Document, Task
from .task_runtime import (
    finish as _finish,
    is_stopped as _is_stopped,
    log_task as _log,
    set_progress as _set_progress,
)
from .ai_vision import VISION_FULL_PROMPT
from .ai_analysis import ANALYSIS_SYSTEM
from .ai_common import parse_llm_json
from .batch_ocr import GEMINI_BATCH_BASE, _needs_vision, _scope_filter
from .indexer import _extract_native_text, _is_native_text


async def run_batch_ocr_gemini(task_id: int, config: dict) -> None:
    """
    Gemini Batch OCR — uses Google Gemini's Batch Mode (50 % cheaper, async).

    Per document, picks one of two request modes (see `_needs_vision`):
      - vision: no OCR text exists yet — sends the first page image with
        VISION_FULL_PROMPT, gets back verbatim text + all analysis fields.
      - text-only: OCR text already exists (any engine, including local
        tesseract/easyocr — it's reused as-is, not re-transcribed), only
        analysis is missing — sends just that text with ANALYSIS_SYSTEM (no
        image, cheaper). `ocr_text`/`ocr_model` are left untouched in this mode.

    `.docx`/`.txt` documents have no page image to send, so before the
    vision/text split above, any such document still missing `ocr_text` is
    extracted natively (free, local, `ocr_model="native"`) — this naturally
    routes it into the text-only branch afterwards, so it still gets
    analysis via the batch job.

    Flow (REST, mirrors `run_batch_ocr_mistral`):
      1. For each pending document, build either a vision or text-only request.
      2. Build a JSONL file with inline-base64 / text generateContent requests.
      3. Upload JSONL via the Files API (resumable upload).
      4. Create a batch job (models/{model}:batchGenerateContent).
      5. Poll every `poll_interval` seconds until JOB_STATE_SUCCEEDED.
      6. Download the responses file and save results back to each document.

    Flow (resume via config["resume_batch_job_id"]):
      Skips phases 1–4, jumps straight to polling an existing remote job.
    """
    from .ai_vision import load_first_page, _get_max_image_size

    limit = int(config.get("limit", 50))
    provider_id = config.get("provider_id")
    poll_interval = int(config.get("poll_interval", 30))
    resume_job_id = config.get("resume_batch_job_id")

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
            _log(task_id, "❌ No Gemini provider configured — add one in AI Settings", "error")
            _finish(task_id, "error")
            return

        api_key = provider.api_key
        model = provider.model or "gemini-2.5-flash"
    finally:
        db.close()

    key_header = {"x-goog-api-key": api_key}

    if resume_job_id:
        # ── Resume path: skip submission, reconnect to existing job ──────────
        batch_job_name = resume_job_id
        _log(task_id, f"🔄 Resuming existing Gemini batch job: {batch_job_name}")
        db = SessionLocal()
        try:
            all_docs = db.query(Document).filter(Document.is_deleted == False).all()
            doc_id_map: dict[str, int] = {}
            doc_mode_map: dict[str, str] = {}
            for d in all_docs:
                k = str(d.id)
                doc_id_map[k] = d.id
                doc_mode_map[k] = "vision" if _needs_vision(d) else "text"
        finally:
            db.close()
    else:
        # ── 2. Collect documents by scope ─────────────────────────────────────
        db = SessionLocal()
        try:
            scope = int(config.get("scope", 1))
            docs = _scope_filter(db.query(Document), scope).limit(limit).all()
            total = len(docs)
            max_size = _get_max_image_size(db)
        finally:
            db.close()

        if total == 0:
            _log(task_id, "📭 No pending documents found")
            _finish(task_id, "done", {"processed": 0})
            return

        _log(task_id, f"📋 Found {total} document(s) — model: {model}")
        _set_progress(task_id, 0, total)

        # ── 3. Build JSONL — vision when no usable text exists, text-only otherwise ──
        jsonl_lines: list[str] = []
        doc_id_map = {}
        doc_mode_map: dict[str, str] = {}
        vision_count = 0
        text_count = 0

        for i, doc in enumerate(docs):
            if _is_stopped(task_id):
                _log(task_id, f"Stopped during request building after {i} document(s)")
                return

            if _is_native_text(doc) and _needs_vision(doc):
                # No page image exists for .docx/.txt — extract text natively
                # (free, local) instead of trying to load a first-page image.
                # Once ocr_text is populated, _needs_vision(doc) below is
                # False, so the doc falls through to the text-only branch and
                # still gets analysis via this same batch job.
                with SessionLocal() as docx_db:
                    try:
                        text = _extract_native_text(doc.filepath)
                        live_doc = docx_db.query(Document).filter(Document.id == doc.id).first()
                        if live_doc:
                            live_doc.ocr_text = text
                            live_doc.ocr_status = "done"
                            live_doc.ocr_model = "native"
                            live_doc.vision_status = "skipped"
                            docx_db.commit()
                        doc.ocr_text = text
                        _log(task_id, f"📄 {doc.filename}: native text extraction (no page image)")
                    except Exception as exc:
                        live_doc = docx_db.query(Document).filter(Document.id == doc.id).first()
                        if live_doc:
                            live_doc.ocr_status = "error"
                            live_doc.ocr_error = str(exc)
                            docx_db.commit()
                        _log(task_id, f"❌ {doc.filename}: native text extraction failed — {exc}", "error")
                        _set_progress(task_id, i + 1, total)
                        continue

            key = str(doc.id)
            try:
                if _needs_vision(doc):
                    img_bytes = load_first_page(doc.filepath, max_size=max_size)
                    b64 = base64.b64encode(img_bytes).decode()
                    doc_id_map[key] = doc.id
                    doc_mode_map[key] = "vision"
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
                    vision_count += 1
                    _log(task_id, f"🖼️ {doc.filename}: image sent (vision OCR + analysis)")
                else:
                    text_snippet = doc.ocr_text.strip()[:4000]
                    doc_id_map[key] = doc.id
                    doc_mode_map[key] = "text"
                    jsonl_lines.append(json.dumps({
                        "key": key,
                        "request": {
                            "system_instruction": {"parts": [{"text": ANALYSIS_SYSTEM}]},
                            "contents": [{
                                "parts": [{"text": f"OCR Text:\n{text_snippet}"}],
                            }],
                            "generation_config": {"max_output_tokens": 1024},
                        },
                    }))
                    text_count += 1
                    _log(task_id, f"📝 {doc.filename}: {len(text_snippet)} chars (text-only, no image)")
            except Exception as exc:
                _log(task_id, f"❌ {doc.filename}: cannot build request — {exc}", "error")
            _set_progress(task_id, i + 1, total)

        if not jsonl_lines:
            _log(task_id, "No requests could be built", "error")
            _finish(task_id, "error")
            return

        _log(task_id, f"📊 {vision_count} via image, {text_count} via text-only")
        jsonl_bytes = ("\n".join(jsonl_lines)).encode()

        # ── 4. Upload JSONL via Files API (resumable upload) ──────────────────
        _log(task_id, f"📤 Uploading batch ({len(jsonl_lines)} requests) to Gemini…")
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
                _log(task_id, "❌ Gemini did not return an upload URL", "error")
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

        _log(task_id, f"☁️ Uploaded input file: {input_file_name}")

        # ── 5. Create batch job ──────────────────────────────────────────────
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
        _log(task_id, f"🚀 Batch job created: {batch_job_name}")

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

    if resume_job_id:
        # Fresh path counted vision_count/text_count while building requests;
        # resume reconstructs them from the recomputed doc_mode_map instead.
        vision_count = sum(1 for v in doc_mode_map.values() if v == "vision")
        text_count = sum(1 for v in doc_mode_map.values() if v == "text")

    # ── 6. Poll until complete ────────────────────────────────────────────────
    _log(task_id, f"⏳ Job submitted. Polling every {poll_interval}s… (up to 48 h)")

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
        _log(task_id, f"⏳ Status: {job_status}")

        if job_status == "JOB_STATE_SUCCEEDED" or job_data.get("done"):
            break
        if job_status in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
            err = (job_data.get("error") or {}).get("message", job_status)
            _log(task_id, f"❌ Batch job ended with status: {job_status} — {err}", "error")
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
        _log(task_id, "❌ Batch completed but no responses file in response", "error")
        _finish(task_id, "error")
        return

    _log(task_id, f"📥 Downloading results from {output_file_name}…")
    async with httpx.AsyncClient(timeout=180) as client:
        results_resp = await client.get(
            f"{GEMINI_BATCH_BASE}/download/v1beta/{output_file_name}:download",
            headers=key_header,
            params={"alt": "media"},
        )
        results_resp.raise_for_status()
        results_text = results_resp.text

    # Save raw results locally for debugging / manual download
    from ..config import settings as _cfg
    try:
        _batch_dir = _cfg.docintell_dir / "batch_results"
        _batch_dir.mkdir(parents=True, exist_ok=True)
        (_batch_dir / f"task_{task_id}.jsonl").write_text(results_text, encoding="utf-8")
        _log(task_id, f"💾 Raw results saved → .docintell/batch_results/task_{task_id}.jsonl")
    except Exception as _save_exc:
        _log(task_id, f"⚠️ Could not save raw results file: {_save_exc}", "warning")

    # ── 8. Save results to documents (branches on per-doc mode) ───────────────
    _log(task_id, "💾 Saving results…")
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

                mode = doc_mode_map.get(key, "vision")
                mode_icon = "🖼️" if mode == "vision" else "📝"

                if result_obj.get("error"):
                    err_msg = result_obj["error"].get("message", "Unknown Gemini error")
                    _log(task_id, f"❌ {mode_icon} Doc {doc_id}: {err_msg}", "error")
                    doc = db.query(Document).filter(Document.id == doc_id).first()
                    if doc and mode == "vision":
                        # Only a vision request can leave OCR itself undone — a failed
                        # text-only request just means analysis stays pending.
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
                if not doc:
                    continue

                parse_error: str | None = None
                parsed = None
                try:
                    parsed = parse_llm_json(text)
                except Exception as exc:
                    parse_error = str(exc)

                if mode == "text":
                    # Text-only request — OCR text already existed; only analysis fields expected.
                    if parsed and isinstance(parsed, dict):
                        doc.summary = parsed.get("summary", "")
                        title = parsed.get("title", "")
                        doc.title = " ".join(title.split()[:10])[:150] if title else None
                        doc.document_type = parsed.get("document_type", "unclassified")
                        doc.document_type_confidence = float(parsed.get("document_type_confidence") or 0.0)
                        doc.tags = parsed.get("tags") or []
                        doc.language = parsed.get("language", "")
                        doc.organization = parsed.get("organization")
                        amount = parsed.get("amount")
                        doc.amount = float(amount) if amount is not None else None
                        doc.amount_currency = parsed.get("amount_currency")
                        doc.person_first_name = parsed.get("person_first_name")
                        doc.person_last_name = parsed.get("person_last_name")
                        raw_date = parsed.get("document_date")
                        if raw_date:
                            try:
                                doc.document_date = datetime.strptime(raw_date, "%Y-%m-%d")
                            except ValueError:
                                doc.document_date = None
                        else:
                            doc.document_date = None
                        short_title = parsed.get("short_title", "")
                        if short_title:
                            doc.short_title = short_title
                        doc.analysis_status = "done"
                        doc.analysis_model = f"{model} (batch, text-only)"
                        db.commit()
                        from .indexer import _run_embedding
                        await _run_embedding(doc, db)
                        _log(task_id, f"✅ {mode_icon} {doc.filename} → {doc.document_type} (text-only, no image sent)")
                        processed += 1
                    else:
                        _log(task_id, f"⚠️ {mode_icon} Doc {doc_id}: JSON parse error — {parse_error or 'no JSON'}", "error")
                        preview = text[:400].replace("\n", " ")
                        _log(task_id, f"  Model response preview: {preview}", "error")
                        failed_count += 1
                    continue

                # mode == "vision" — full transcription + analysis expected.
                if parsed and isinstance(parsed, dict) and parsed.get("text"):
                    doc.ocr_text = parsed["text"]
                    doc.ocr_status = "done"
                    doc.ocr_model = f"{model} (batch)"
                    doc.summary = parsed.get("summary", "")
                    title = parsed.get("title", "")
                    doc.title = " ".join(title.split()[:10])[:150] if title else None
                    doc.document_type = parsed.get("document_type", "unclassified")
                    doc.document_type_confidence = float(parsed.get("document_type_confidence") or 0.0)
                    doc.tags = parsed.get("tags") or []
                    doc.language = parsed.get("language", "")
                    doc.organization = parsed.get("organization")
                    amount = parsed.get("amount")
                    doc.amount = float(amount) if amount is not None else None
                    doc.amount_currency = parsed.get("amount_currency")
                    doc.person_first_name = parsed.get("person_first_name")
                    doc.person_last_name = parsed.get("person_last_name")
                    raw_date = parsed.get("document_date")
                    if raw_date:
                        try:
                            doc.document_date = datetime.strptime(raw_date, "%Y-%m-%d")
                        except ValueError:
                            doc.document_date = None
                    else:
                        doc.document_date = None
                    short_title = parsed.get("short_title", "")
                    if short_title:
                        doc.short_title = short_title
                    doc.analysis_status = "done"
                    doc.analysis_model = f"{model} (batch)"
                    db.commit()
                    # Re-embed now that summary + OCR text exist.
                    from .indexer import _run_embedding
                    await _run_embedding(doc, db)
                    _log(task_id, f"✅ {mode_icon} {doc.filename} → {doc.document_type} (image sent)")
                    processed += 1
                else:
                    # Save raw text as OCR only; leave analysis pending
                    doc.ocr_text = text
                    doc.ocr_status = "done"
                    doc.ocr_model = f"{model} (batch)"
                    db.commit()
                    if parse_error:
                        _log(task_id, f"⚠️ {mode_icon} Doc {doc_id}: JSON parse error — {parse_error}", "error")
                    elif not parsed:
                        _log(task_id, f"⚠️ {mode_icon} Doc {doc_id}: response produced no JSON", "error")
                    else:
                        keys = list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
                        _log(task_id, f"⚠️ {mode_icon} Doc {doc_id}: parsed JSON missing 'text' field (got keys: {keys})", "error")
                    preview = text[:400].replace("\n", " ")
                    _log(task_id, f"  Model response preview: {preview}", "error")
                    processed += 1

            except Exception as exc:
                _log(task_id, f"❌ Result parse error: {exc}", "error")
                failed_count += 1
    finally:
        db.close()

    summary = {
        "processed": processed,
        "failed": failed_count,
        "vision_count": vision_count,
        "text_count": text_count,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "batch_job_id": batch_job_name,
    }
    from .usage import record_usage
    from .pricing import estimate_cost
    record_usage(
        usage_type="batch_ocr", provider_type="gemini", model=model,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=estimate_cost(model, tokens_in, tokens_out),
        detail=f"{processed} docs, {failed_count} failed",
    )
    _finish(task_id, "done", summary)
    _log(task_id, (
        f"✅ Done — {processed} processed ({vision_count} via image, {text_count} via text-only), "
        f"{failed_count} failed, {tokens_in}+{tokens_out} tokens (batch discount applied)"
    ))
