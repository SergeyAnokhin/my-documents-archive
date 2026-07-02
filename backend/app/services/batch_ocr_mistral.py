"""Mistral Batch OCR runner — see docs/batch-ocr.md.

Split out of batch_ocr.py to keep each provider's integration in its own file.
Shared document-scope filtering lives in batch_ocr.py.
"""
import asyncio
import base64
import json

import httpx

from ..database import SessionLocal
from ..models import AIProvider, Document, Task
from .task_runtime import (
    finish as _finish,
    is_stopped as _is_stopped,
    log_task as _log,
    set_progress as _set_progress,
)
from .batch_ocr import _scope_filter
from .docx_extract import extract_docx_text
from .indexer import _is_docx


async def run_batch_ocr_mistral(task_id: int, config: dict) -> None:
    """
    Mistral Batch OCR — uses Mistral's Batch API (50 % cheaper, async).

    Flow (normal):
      1. Load first page of each pending document as JPEG.
      2. Build a JSONL file with inline-base64 OCR requests.
      3. Upload JSONL to Mistral Files API.
      4. Create a batch job pointing at that file.
      5. Poll every `poll_interval` seconds until the job completes.
      6. Download the output file and save OCR text back to each document.

    Flow (resume via config["resume_batch_job_id"]):
      Skips phases 1–4, jumps straight to polling an existing remote job.

    `.docx` documents have no page image to send to Mistral OCR — they're
    extracted natively instead (free, local, `ocr_model="native"`) and never
    added to the JSONL batch. A follow-up batch-analysis run (which only
    requires `ocr_text` to be set) picks them up like any other document.
    """
    from .ai_vision import load_first_page, parse_mistral_ocr, _get_max_image_size

    limit = int(config.get("limit", 50))
    provider_id = config.get("provider_id")
    poll_interval = int(config.get("poll_interval", 30))
    resume_job_id = config.get("resume_batch_job_id")

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
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {api_key}"}
    native_processed = 0  # .docx documents handled locally, never sent to Mistral

    if resume_job_id:
        # ── Resume path: skip submission, reconnect to existing job ──────────
        batch_job_id = resume_job_id
        _log(task_id, f"Resuming existing Mistral batch job: {batch_job_id}")
        db = SessionLocal()
        try:
            all_ids = db.query(Document.id).filter(Document.is_deleted == False).all()
            doc_id_map: dict[str, int] = {str(row[0]): row[0] for row in all_ids}
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
            _log(task_id, "No documents found for the selected scope")
            _finish(task_id, "done", {"processed": 0})
            return

        _log(task_id, f"Found {total} document(s) — model: {model}")
        _set_progress(task_id, 0, total)

        # ── 3. Build JSONL (inline base64) ───────────────────────────────────
        _log(task_id, "Loading document images…")
        jsonl_lines: list[str] = []
        doc_id_map = {}

        for i, doc in enumerate(docs):
            if _is_stopped(task_id):
                _log(task_id, f"Stopped during image loading after {i} document(s)")
                return

            if _is_docx(doc):
                # .docx has no page image — Mistral OCR doesn't apply. Extract
                # text natively (free, local) instead; the follow-up batch
                # analysis step picks it up like any other document with
                # ocr_text already set.
                with SessionLocal() as docx_db:
                    try:
                        text = extract_docx_text(doc.filepath)
                        live_doc = docx_db.query(Document).filter(Document.id == doc.id).first()
                        if live_doc:
                            live_doc.ocr_text = text
                            live_doc.ocr_status = "done"
                            live_doc.ocr_model = "native"
                            live_doc.vision_status = "skipped"
                            docx_db.commit()
                        native_processed += 1
                        _log(task_id, f"✓ {doc.filename}: native text extraction (.docx has no page image — Mistral OCR skipped)")
                    except Exception as exc:
                        live_doc = docx_db.query(Document).filter(Document.id == doc.id).first()
                        if live_doc:
                            live_doc.ocr_status = "error"
                            live_doc.ocr_error = str(exc)
                            docx_db.commit()
                        _log(task_id, f"✗ {doc.filename}: native docx extraction failed — {exc}", "error")
                _set_progress(task_id, i + 1, total)
                continue

            try:
                img_bytes = load_first_page(doc.filepath, max_size=max_size)
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
            if native_processed:
                _log(task_id, f"All {native_processed} document(s) handled natively (.docx) — nothing to send to Mistral")
                _finish(task_id, "done", {"processed": native_processed, "native": native_processed})
                return
            _log(task_id, "No document images could be loaded", "error")
            _finish(task_id, "error")
            return

        # ── 4. Upload JSONL to Mistral Files API ─────────────────────────────
        _log(task_id, f"Uploading batch ({len(jsonl_lines)} requests) to Mistral…")
        jsonl_bytes = "\n".join(jsonl_lines).encode()

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

        # ── 5. Create batch job ──────────────────────────────────────────────
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

    job_data: dict = {}
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

    # Save raw results locally for debugging / manual download
    from ..config import settings as _cfg
    try:
        _batch_dir = _cfg.docintell_dir / "batch_results"
        _batch_dir.mkdir(parents=True, exist_ok=True)
        (_batch_dir / f"task_{task_id}.jsonl").write_text(results_text, encoding="utf-8")
        _log(task_id, f"Raw results saved → .docintell/batch_results/task_{task_id}.jsonl")
    except Exception as _save_exc:
        _log(task_id, f"Could not save raw results file: {_save_exc}", "warning")

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
                doc_id = doc_id_map.get(custom_id) or (int(custom_id) if custom_id.isdigit() else None)
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
        "processed": processed + native_processed,
        "failed": failed_count,
        "cost_usd": round(total_cost, 5),
        "batch_job_id": batch_job_id,
    }
    if native_processed:
        summary["native"] = native_processed
    from .usage import record_usage
    record_usage(
        usage_type="batch_ocr", provider_type="mistral", model=model,
        cost_usd=round(total_cost, 5), detail=f"{processed} docs, {failed_count} failed",
    )
    _finish(task_id, "done", summary)
    _log(task_id, (
        f"Done — {processed} saved, {failed_count} failed, "
        f"cost ${total_cost:.5f} (batch discount applied)"
    ))
