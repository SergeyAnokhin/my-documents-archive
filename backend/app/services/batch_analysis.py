"""Batch AI analysis via Gemini Batch API.

Selects documents that have OCR text but no AI analysis yet, submits them
as a text-only batch to Gemini, and saves the analysis results back to each
document (summary, document_type, tags, language, etc.).

This is analogous to batch_ocr_gemini but for the analysis phase — useful after
Mistral batch OCR has produced ocr_text that still needs AI metadata extraction.
"""
import asyncio
import json
import logging
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
from .ai_analysis import ANALYSIS_SYSTEM, CLASSIFICATION_SYSTEM, METADATA_SYSTEM
from .ai_common import parse_llm_json
from .batch_ocr import GEMINI_BATCH_BASE

log = logging.getLogger(__name__)


async def run_batch_analysis_gemini(task_id: int, config: dict) -> None:
    """Submit text-only analysis batch to Gemini and persist results.

    Config keys:
      limit                 — max documents to include (default 50)
      provider_id           — AIProvider id to use; falls back to first enabled Gemini
      poll_interval         — seconds between status polls (default 30)
      resume_batch_job_id   — if set, skip submission and resume polling this job
      doc_scope             — which documents to include:
                              "needs_analysis" (default) — has ocr_text, no analysis or unclassified
                              "unclassified"  — ocr done, type is unclassified/other, not manually set
                              "pending"       — ocr done, analysis_status != "done"
      doc_ids               — explicit list of document IDs to process (overrides doc_scope)
    """
    limit = int(config.get("limit", 50))
    provider_id = config.get("provider_id")
    poll_interval = int(config.get("poll_interval", 30))
    resume_job_id = config.get("resume_batch_job_id")
    doc_scope = config.get("doc_scope", "needs_analysis")
    doc_ids_filter = config.get("doc_ids")  # list[int] | None
    metadata_only = bool(config.get("metadata_only", False))
    classification_only = bool(config.get("classification_only", False))

    # ── 1. Resolve provider ───────────────────────────────────────────────────
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
        _log(task_id, f"🔄 Resuming existing Gemini analysis batch job: {batch_job_name}")
        db = SessionLocal()
        try:
            all_ids = db.query(Document.id).filter(Document.is_deleted == False).all()
            doc_id_map: dict[str, int] = {str(row[0]): row[0] for row in all_ids}
        finally:
            db.close()
    else:
        # ── 2. Collect documents needing analysis ─────────────────────────────
        from sqlalchemy import or_
        db = SessionLocal()
        try:
            base_q = db.query(Document).filter(Document.is_deleted == False)

            if doc_ids_filter is not None:
                # Explicit ID list — no extra filters applied; caller is responsible for selection.
                docs = base_q.filter(Document.id.in_(doc_ids_filter)).all()
            elif doc_scope in ("unclassified", "classification_unclassified"):
                # reclassify_unclassified: has ocr done, type is unclassified/other, not manually set
                docs = (
                    base_q
                    .filter(
                        Document.ocr_status == "done",
                        Document.manually_classified != True,
                        or_(
                            Document.document_type == "unclassified",
                            Document.document_type == "other",
                            Document.document_type.is_(None),
                        ),
                        Document.ocr_text.isnot(None),
                        Document.ocr_text != "",
                    )
                    .limit(limit)
                    .all()
                )
            elif doc_scope == "classification_all":
                docs = (
                    base_q.filter(
                        Document.manually_classified != True,
                        or_(Document.summary.isnot(None), Document.ocr_text.isnot(None)),
                    ).limit(limit).all()
                )
            elif doc_scope == "pending":
                # reclassify_all: ocr done but analysis not yet complete
                docs = (
                    base_q
                    .filter(
                        Document.ocr_status == "done",
                        Document.analysis_status != "done",
                        Document.ocr_text.isnot(None),
                        Document.ocr_text != "",
                    )
                    .limit(limit)
                    .all()
                )
            else:
                # needs_analysis (default): has text, no analysis or unclassified, not manually set
                docs = (
                    base_q
                    .filter(
                        Document.ocr_text.isnot(None),
                        Document.ocr_text != "",
                        Document.manually_classified != True,
                        or_(
                            Document.analysis_status != "done",
                            Document.document_type == "unclassified",
                            Document.document_type == "other",
                            Document.document_type.is_(None),
                        ),
                    )
                    .limit(limit)
                    .all()
                )

            total = len(docs)
        finally:
            db.close()

        if total == 0:
            _log(task_id, "📭 No documents found with OCR text pending analysis")
            _finish(task_id, "done", {"processed": 0})
            return

        _log(task_id, f"📋 Found {total} document(s) for analysis — model: {model}")
        _log(task_id, "📝 Mode: text-only — extracted OCR text is sent, no images")
        _set_progress(task_id, 0, total)

        # ── 3. Build JSONL (text-only requests) ──────────────────────────────
        jsonl_lines: list[str] = []
        doc_id_map = {}

        for doc in docs:
            source_text = doc.summary if classification_only and doc.summary else (doc.ocr_text or doc.vision_description)
            text_snippet = (source_text or "").strip()[:4000]
            if not text_snippet:
                _log(task_id, f"⚠️ {doc.filename}: no text to analyze, skipping")
                continue
            _log(task_id, f"📄 {doc.filename}: {len(text_snippet)} chars (text-only, no image)")
            user_msg = f"OCR Text:\n{text_snippet}"
            key = str(doc.id)
            doc_id_map[key] = doc.id
            jsonl_lines.append(json.dumps({
                "key": key,
                "request": {
                    "system_instruction": {"parts": [{"text": CLASSIFICATION_SYSTEM if classification_only else (METADATA_SYSTEM if metadata_only else ANALYSIS_SYSTEM)}]},
                    "contents": [{
                        "parts": [{"text": user_msg}],
                    }],
                    "generation_config": {"max_output_tokens": 1024},
                },
            }))

        if not jsonl_lines:
            _log(task_id, "📭 No documents had text to analyze — nothing to submit", "warning")
            _finish(task_id, "done", {"processed": 0, "failed": 0})
            return

        jsonl_bytes = ("\n".join(jsonl_lines)).encode()

        # ── 4. Upload JSONL ───────────────────────────────────────────────────
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
                json={"file": {"display_name": f"docintel_analysis_{task_id}"}},
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
            input_file_name = upload_resp.json()["file"]["name"]

        _log(task_id, f"☁️ Uploaded input file: {input_file_name}")

        # ── 5. Create batch job ──────────────────────────────────────────────
        async with httpx.AsyncClient(timeout=60) as client:
            batch_resp = await client.post(
                f"{GEMINI_BATCH_BASE}/v1beta/models/{model}:batchGenerateContent",
                headers={**key_header, "Content-Type": "application/json"},
                json={
                    "batch": {
                        "display_name": f"docintel-analysis-{task_id}",
                        "input_config": {"file_name": input_file_name},
                    },
                },
            )
            try:
                batch_resp.raise_for_status()
            except httpx.HTTPStatusError:
                _log(task_id, f"❌ Gemini rejected batch job ({batch_resp.status_code}): {batch_resp.text}", "error")
                _finish(task_id, "error")
                return
            batch_data = batch_resp.json()

        batch_job_name = batch_data["name"]
        _log(task_id, f"🚀 Batch job created: {batch_job_name}")

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
    _log(task_id, f"⏳ Job submitted. Polling every {poll_interval}s…")

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
            _log(task_id, f"❌ Batch job ended: {job_status} — {err}", "error")
            _finish(task_id, "error", {"batch_job_id": batch_job_name, "status": job_status})
            return

    # ── 7. Download results ──────────────────────────────────────────────────
    response_obj = job_data.get("response") or {}
    output_file_name = (
        response_obj.get("responsesFile")
        or (response_obj.get("dest") or {}).get("fileName")
        or (job_data.get("dest") or {}).get("fileName")
    )
    if not output_file_name:
        _log(task_id, "❌ Batch completed but no responses file found", "error")
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

    # ── 8. Save analysis to documents ────────────────────────────────────────
    _log(task_id, "💾 Saving analysis results…")
    processed = 0
    failed_count = 0
    tokens_in = 0
    tokens_out = 0
    key = ""

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
                    err_msg = result_obj["error"].get("message", "Unknown error")
                    _log(task_id, f"❌ Doc {doc_id}: {err_msg}", "error")
                    failed_count += 1
                    continue

                resp_body = result_obj.get("response") or {}
                candidates = resp_body.get("candidates") or []
                usage = resp_body.get("usageMetadata") or {}
                tokens_in += usage.get("promptTokenCount", 0)
                tokens_out += usage.get("candidatesTokenCount", 0)

                text = ""
                for cand in candidates:
                    for part in (cand.get("content") or {}).get("parts") or []:
                        text += part.get("text", "")

                parsed = parse_llm_json(text.strip())

                doc = db.query(Document).filter(Document.id == doc_id).first()
                if not doc:
                    continue

                if classification_only:
                    doc.document_type = parsed.get("document_type") or "unclassified"
                    doc.classification_confidence = float(parsed.get("document_type_confidence") or 0.0)
                    doc.classification_source = "auto"
                    doc.manually_classified = False
                    db.commit()
                    processed += 1
                    _log(task_id, f"Classified {doc.filename} as {doc.document_type}")
                    continue

                doc.summary = parsed.get("summary", "")
                title = parsed.get("title", "")
                doc.title = " ".join(title.split()[:10])[:150] if title else None
                if not metadata_only:
                    doc.document_type = parsed.get("document_type") or "unclassified"
                    doc.classification_confidence = float(parsed.get("document_type_confidence") or 0.0)
                    doc.classification_source = "auto"
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
                doc.analysis_status = "done"
                doc.analysis_model = f"{model} (batch, metadata-only)" if metadata_only else f"{model} (batch)"
                db.commit()
                # Re-embed now that the summary exists so semantic search/ask sees it.
                from .indexer import _run_embedding
                await _run_embedding(doc, db)
                processed += 1
                doc_type = doc.document_type or "unclassified"
                tags_str = ", ".join((doc.tags or [])[:5])
                suffix = f" [{tags_str}]" if tags_str else ""
                _log(task_id, f"✅ {doc.filename} → {doc_type}{suffix}")

            except Exception as exc:
                db.rollback()
                text_preview = (text[:400].replace("\n", " ")) if "text" in dir() else ""
                _log(task_id, f"❌ Doc key '{key}': {exc}", "error")
                if text_preview:
                    _log(task_id, f"  Model response preview: {text_preview}", "error")
                failed_count += 1
    finally:
        db.close()

    summary = {"processed": processed, "failed": failed_count, "batch_job_id": batch_job_name}
    if tokens_in or tokens_out:
        summary["tokens_in"] = tokens_in
        summary["tokens_out"] = tokens_out

    from .usage import record_usage
    from .pricing import estimate_cost
    record_usage(
        usage_type="batch_analysis", provider_type="gemini", model=model,
        tokens_in=tokens_in, tokens_out=tokens_out,
        cost_usd=estimate_cost(model, tokens_in, tokens_out),
        detail=f"{processed} docs, {failed_count} failed",
    )
    _finish(task_id, "done", summary)
    _log(task_id, f"✅ Done — {processed} analyzed, {failed_count} failed")
