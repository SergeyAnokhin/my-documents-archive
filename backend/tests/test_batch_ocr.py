"""Pins the vision-vs-text routing rule and the Mistral/Gemini batch-OCR
request+response handling for services/batch_ocr.py — see docs/batch-ocr.md.

`_needs_vision` decides whether a document's image must be sent to Gemini (vision,
billed for image tokens) or whether the existing OCR text is good enough to send
text-only (cheaper, no image). The rule: no text at all → vision; any existing
text, regardless of which engine produced it (including local tesseract/easyocr)
→ text-only, since keeping that text implies its quality is acceptable.

`run_batch_ocr_mistral()`/`run_batch_ocr_gemini()` are long-running integrations:
they select documents, build a provider-specific JSONL batch request, upload/
submit/poll/download via httpx, then write parsed results back onto Document
rows. All httpx calls below are mocked (no network, no cost) and the functions
are driven end-to-end against an in-memory SQLite DB, pinning the outbound
request shapes (JSONL lines, upload/create payloads), the status-polling
interpretation, and the result-line parsing (success/error branches,
vision-vs-text-only field handling).

`.docx`/`.txt` documents have no page image to send to either provider — both
runners extract their text natively (`indexer._extract_native_text`, no OCR/LLM
call) before building any request. For Mistral (OCR-only) this means the
document is excluded from the JSONL entirely; for Gemini (which also handles
analysis) the extracted text routes the document into the existing text-only
branch, so it still gets analysis via the batch job.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.database import Base
from app.models import AIProvider, Document, Task
from app.services import batch_ocr_gemini, batch_ocr_mistral, task_runtime
from app.services import usage as usage_module
from app.services.batch_ocr import GEMINI_BATCH_BASE, _needs_vision
from app.services.batch_ocr_gemini import run_batch_ocr_gemini
from app.services.batch_ocr_mistral import run_batch_ocr_mistral


def _doc(ocr_text=None, ocr_model=None):
    return SimpleNamespace(ocr_text=ocr_text, ocr_model=ocr_model)


def test_needs_vision_when_no_text():
    # Doc:  docs/batch-ocr.md — hybrid routing
    # Rule: a document with no OCR text at all must go through vision.
    assert _needs_vision(_doc(ocr_text=None)) is True
    assert _needs_vision(_doc(ocr_text="   ")) is True


def test_text_only_for_local_ocr_engines():
    # Doc:  docs/batch-ocr.md — hybrid routing
    # Rule: local-engine text (tesseract/easyocr) is reused as-is, not re-OCR'd —
    # keeping it implies the quality is already acceptable.
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="tesseract")) is False
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="easyocr")) is False


def test_text_only_when_ai_ocr_text_already_exists():
    # Doc:  docs/batch-ocr.md — hybrid routing
    # Rule: text from an AI-grade engine is reused — no image is sent.
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="mistral-ocr-latest (batch)")) is False
    assert _needs_vision(_doc(ocr_text="some text", ocr_model="gemini-2.5-flash (batch)")) is False


# ── shared test harness ──────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)

    monkeypatch.setattr(batch_ocr_mistral, "SessionLocal", SessionLocal)
    monkeypatch.setattr(batch_ocr_gemini, "SessionLocal", SessionLocal)
    monkeypatch.setattr(task_runtime, "SessionLocal", SessionLocal)
    monkeypatch.setattr(usage_module, "SessionLocal", SessionLocal)
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    monkeypatch.setattr("app.services.indexer._run_embedding", AsyncMock())
    monkeypatch.setattr("app.services.ai_vision.load_first_page", lambda filepath, max_size=1024: b"fake-jpeg-bytes")
    monkeypatch.setattr(batch_ocr_mistral, "_log", lambda *a, **k: None)
    monkeypatch.setattr(batch_ocr_gemini, "_log", lambda *a, **k: None)

    def _make_task(task_type: str) -> int:
        db = SessionLocal()
        t = Task(task_type=task_type, title="t", status="running")
        db.add(t)
        db.commit()
        db.refresh(t)
        tid = t.id
        db.close()
        return tid

    def _make_provider(provider_type: str, **kwargs) -> int:
        db = SessionLocal()
        defaults = dict(name="p", provider_type=provider_type, api_key="k", enabled=True, sort_order=0, task_type="both")
        defaults.update(kwargs)
        p = AIProvider(**defaults)
        db.add(p)
        db.commit()
        db.refresh(p)
        pid = p.id
        db.close()
        return pid

    def _add_doc(**kwargs) -> int:
        db = SessionLocal()
        defaults = dict(filename="d.pdf", filepath=f"/lib/{len(kwargs)}-{kwargs.get('filename', 'd')}.pdf")
        defaults.update(kwargs)
        doc = Document(**defaults)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        did = doc.id
        db.close()
        return did

    def _get_doc(doc_id: int) -> Document:
        db = SessionLocal()
        d = db.query(Document).filter(Document.id == doc_id).first()
        db.expunge(d)
        db.close()
        return d

    def _get_task(task_id: int) -> Task:
        db = SessionLocal()
        t = db.query(Task).filter(Task.id == task_id).first()
        db.expunge(t)
        db.close()
        return t

    return SimpleNamespace(
        SessionLocal=SessionLocal, make_task=_make_task, make_provider=_make_provider,
        add_doc=_add_doc, get_doc=_get_doc, get_task=_get_task,
    )


def _jsonl_lines(raw_bytes: bytes) -> list[dict]:
    return [json.loads(line) for line in raw_bytes.decode().splitlines() if line.strip()]


# ═══════════════════════════════ Mistral batch OCR ══════════════════════════════

MISTRAL_UPLOAD_URL = "https://api.mistral.ai/v1/files"
MISTRAL_JOBS_URL = "https://api.mistral.ai/v1/batch/jobs"
MISTRAL_FILE_ID = "file-abc123"
MISTRAL_JOB_ID = "job-xyz789"
MISTRAL_OUTPUT_FILE_ID = "file-out456"

MISTRAL_POLL_SUCCESS = {"status": "SUCCESS", "succeeded_requests": 1, "failed_requests": 0, "output_file": MISTRAL_OUTPUT_FILE_ID}


def _mock_httpx_mistral(captured: dict, poll_response: dict, download_text: str):
    async def _post(url, **kwargs):
        if url == MISTRAL_UPLOAD_URL:
            captured["upload_files"] = kwargs.get("files")
            captured["upload_data"] = kwargs.get("data")
            resp = MagicMock()
            resp.json.return_value = {"id": MISTRAL_FILE_ID}
            resp.raise_for_status = MagicMock()
            return resp
        if url == MISTRAL_JOBS_URL:
            captured["batch_create_body"] = kwargs.get("json")
            resp = MagicMock()
            resp.json.return_value = {"id": MISTRAL_JOB_ID}
            resp.raise_for_status = MagicMock()
            return resp
        raise AssertionError(f"unexpected POST {url}")

    async def _get(url, **kwargs):
        if url == f"{MISTRAL_JOBS_URL}/{MISTRAL_JOB_ID}":
            resp = MagicMock()
            resp.json.return_value = poll_response
            resp.raise_for_status = MagicMock()
            return resp
        if url == f"https://api.mistral.ai/v1/files/{MISTRAL_OUTPUT_FILE_ID}/content":
            captured["download_called"] = True
            resp = MagicMock(text=download_text)
            resp.raise_for_status = MagicMock()
            return resp
        raise AssertionError(f"unexpected GET {url}")

    client = MagicMock()
    client.post = AsyncMock(side_effect=_post)
    client.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _run_mistral(env, task_id, config, poll_response=None, download_text=""):
    captured: dict = {}
    with patch("httpx.AsyncClient", _mock_httpx_mistral(captured, poll_response or MISTRAL_POLL_SUCCESS, download_text)):
        asyncio.run(run_batch_ocr_mistral(task_id, config))
    return captured


def test_mistral_no_provider_finishes_with_error(env):
    # Doc:  docs/batch-ocr.md — Mistral batch OCR requires a configured provider
    # Rule: with no Mistral provider configured, the task is marked "error" and
    #       no network call is attempted.
    task_id = env.make_task("batch_ocr_mistral")
    _run_mistral(env, task_id, {})
    assert env.get_task(task_id).status == "error"


def test_mistral_no_documents_finishes_done_zero_processed(env):
    # Doc:  docs/batch-ocr.md — Mistral batch OCR document scope
    # Rule: no matching documents → task finishes "done" with processed=0.
    env.make_provider("mistral")
    task_id = env.make_task("batch_ocr_mistral")
    _run_mistral(env, task_id, {})
    task = env.get_task(task_id)
    assert task.status == "done"
    assert task.result_summary["processed"] == 0


def test_mistral_jsonl_request_shape_and_upload_payload(env):
    # Doc:  docs/batch-ocr.md — Mistral Batch API request build
    # Rule: each JSONL line is {"custom_id", "body": {model, document.image_url,
    #       include_image_base64: False}}; the file is uploaded as multipart with
    #       purpose="batch".
    env.make_provider("mistral", model="mistral-ocr-latest")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    captured = _run_mistral(env, task_id, {})

    assert captured["upload_data"] == {"purpose": "batch"}
    filename, content, content_type = captured["upload_files"]["file"]
    lines = _jsonl_lines(content)
    assert len(lines) == 1
    line = lines[0]
    assert line["custom_id"] == str(doc_id)
    assert line["body"]["model"] == "mistral-ocr-latest"
    assert line["body"]["document"] == {"type": "image_url", "image_url": "data:image/jpeg;base64,ZmFrZS1qcGVnLWJ5dGVz"}
    assert line["body"]["include_image_base64"] is False


def test_mistral_batch_job_create_payload(env):
    # Doc:  docs/batch-ocr.md — Mistral Batch API job creation
    # Rule: the batch job is created with {input_files:[uploaded_id], endpoint:
    #       "/v1/ocr", model}.
    env.make_provider("mistral", model="mistral-ocr-latest")
    task_id = env.make_task("batch_ocr_mistral")
    env.add_doc(filename="a.pdf", ocr_text=None)

    captured = _run_mistral(env, task_id, {})

    assert captured["batch_create_body"] == {
        "input_files": [MISTRAL_FILE_ID], "endpoint": "/v1/ocr", "model": "mistral-ocr-latest",
    }


def test_mistral_success_result_line_saves_ocr_text_and_cost(env):
    # Doc:  docs/batch-ocr.md — Mistral batch result saving
    # Rule: a successful result line's OCR body is parsed via parse_mistral_ocr
    #       and written onto ocr_text/ocr_status/ocr_model/api_cost_vision.
    env.make_provider("mistral", model="mistral-ocr-latest")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    result_line = json.dumps({
        "custom_id": str(doc_id),
        "response": {"body": {"pages": [{"markdown": "hello world"}], "usage_info": {"pages_processed": 1}}},
    })
    _run_mistral(env, task_id, {}, download_text=result_line)

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "hello world"
    assert doc.ocr_status == "done"
    assert doc.ocr_model == "mistral-ocr-latest (batch)"
    assert doc.api_cost_vision > 0


def test_mistral_error_result_line_marks_doc_ocr_error(env):
    # Doc:  docs/batch-ocr.md — Mistral batch result saving
    # Rule: a per-line {"error": {...}} response sets ocr_status="error" with
    #       the provider's message, and counts as failed.
    env.make_provider("mistral")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    result_line = json.dumps({"custom_id": str(doc_id), "error": {"message": "page limit exceeded"}})
    _run_mistral(env, task_id, {}, download_text=result_line)

    doc = env.get_doc(doc_id)
    assert doc.ocr_status == "error"
    assert doc.ocr_error == "page limit exceeded"

    task = env.get_task(task_id)
    assert task.result_summary["failed"] == 1


def test_mistral_poll_failed_status_finishes_error_without_download(env):
    # Doc:  docs/batch-ocr.md — Mistral batch status polling
    # Rule: a terminal FAILED status ends the task as "error" without ever
    #       attempting to download results.
    env.make_provider("mistral")
    task_id = env.make_task("batch_ocr_mistral")
    env.add_doc(filename="a.pdf", ocr_text=None)

    captured = _run_mistral(env, task_id, {}, poll_response={"status": "FAILED"})

    assert "download_called" not in captured
    task = env.get_task(task_id)
    assert task.status == "error"


def test_mistral_resume_job_id_skips_submission(env):
    # Doc:  docs/batch-ocr.md §Resume support
    # Rule: resume_batch_job_id skips document collection/upload/create — only
    #       the existing job is polled and downloaded.
    env.make_provider("mistral", model="mistral-ocr-latest")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    result_line = json.dumps({
        "custom_id": str(doc_id),
        "response": {"body": {"pages": [{"markdown": "resumed text"}], "usage_info": {"pages_processed": 1}}},
    })
    captured = _run_mistral(env, task_id, {"resume_batch_job_id": MISTRAL_JOB_ID}, download_text=result_line)

    assert "upload_files" not in captured
    assert "batch_create_body" not in captured
    assert env.get_doc(doc_id).ocr_text == "resumed text"


# ═══════════════════════════════ Gemini batch OCR ═══════════════════════════════

GEMINI_UPLOAD_URL = "https://upload.example/put"
GEMINI_FILE_NAME = "files/abc123"
GEMINI_BATCH_JOB_NAME = "batches/999"
GEMINI_OUTPUT_FILE = "files/output-xyz"

GEMINI_POLL_DONE = {"done": True, "response": {"responsesFile": GEMINI_OUTPUT_FILE}}


def _mock_httpx_gemini(captured: dict, poll_response: dict, download_text: str):
    async def _post(url, **kwargs):
        if url == f"{GEMINI_BATCH_BASE}/upload/v1beta/files":
            resp = MagicMock(headers={"x-goog-upload-url": GEMINI_UPLOAD_URL})
            resp.raise_for_status = MagicMock()
            return resp
        if url == GEMINI_UPLOAD_URL:
            captured["jsonl_bytes"] = kwargs.get("content")
            resp = MagicMock()
            resp.json.return_value = {"file": {"name": GEMINI_FILE_NAME}}
            resp.raise_for_status = MagicMock()
            return resp
        if url.endswith(":batchGenerateContent"):
            captured["batch_create_body"] = kwargs.get("json")
            resp = MagicMock()
            resp.json.return_value = {"name": GEMINI_BATCH_JOB_NAME}
            resp.raise_for_status = MagicMock()
            return resp
        raise AssertionError(f"unexpected POST {url}")

    async def _get(url, **kwargs):
        if url == f"{GEMINI_BATCH_BASE}/v1beta/{GEMINI_BATCH_JOB_NAME}":
            resp = MagicMock()
            resp.json.return_value = poll_response
            resp.raise_for_status = MagicMock()
            return resp
        if url == f"{GEMINI_BATCH_BASE}/download/v1beta/{GEMINI_OUTPUT_FILE}:download":
            captured["download_called"] = True
            resp = MagicMock(text=download_text)
            resp.raise_for_status = MagicMock()
            return resp
        raise AssertionError(f"unexpected GET {url}")

    client = MagicMock()
    client.post = AsyncMock(side_effect=_post)
    client.get = AsyncMock(side_effect=_get)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _run_gemini(env, task_id, config, poll_response=None, download_text=""):
    captured: dict = {}
    with patch("httpx.AsyncClient", _mock_httpx_gemini(captured, poll_response or GEMINI_POLL_DONE, download_text)):
        asyncio.run(run_batch_ocr_gemini(task_id, config))
    return captured


def test_gemini_vision_request_shape_for_document_without_text(env):
    # Doc:  docs/batch-ocr.md — Gemini batch vision request
    # Rule: a document with no OCR text gets an inline_data image + VISION_FULL_PROMPT
    #       request with a 16384-token budget (no system_instruction).
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    captured = _run_gemini(env, task_id, {})

    lines = _jsonl_lines(captured["jsonl_bytes"])
    assert len(lines) == 1
    line = lines[0]
    assert line["key"] == str(doc_id)
    req = line["request"]
    assert "system_instruction" not in req
    parts = req["contents"][0]["parts"]
    assert parts[0]["inline_data"] == {"mime_type": "image/jpeg", "data": "ZmFrZS1qcGVnLWJ5dGVz"}
    assert parts[1]["text"] == batch_ocr_gemini.VISION_FULL_PROMPT
    assert req["generation_config"] == {"max_output_tokens": 16384}


def test_gemini_text_only_request_shape_for_document_with_existing_text(env):
    # Doc:  docs/batch-ocr.md — Gemini batch text-only request
    # Rule: a document that already has OCR text gets a text-only request with
    #       ANALYSIS_SYSTEM as system_instruction and a 1024-token budget.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text="existing ocr text", ocr_model="tesseract")

    # scope=2 includes local-engine (tesseract/easyocr) text in the batch scope.
    captured = _run_gemini(env, task_id, {"scope": 2})

    lines = _jsonl_lines(captured["jsonl_bytes"])
    line = lines[0]
    req = line["request"]
    assert req["system_instruction"] == {"parts": [{"text": batch_ocr_gemini.ANALYSIS_SYSTEM}]}
    assert req["contents"][0]["parts"][0]["text"] == "OCR Text:\nexisting ocr text"
    assert req["generation_config"] == {"max_output_tokens": 1024}


def test_gemini_batch_create_payload_references_uploaded_file(env):
    # Doc:  docs/batch-ocr.md — Gemini batch job creation
    # Rule: the batch job body references the uploaded file's name via
    #       input_config.file_name.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    env.add_doc(filename="a.pdf", ocr_text=None)

    captured = _run_gemini(env, task_id, {})

    assert captured["batch_create_body"]["batch"]["input_config"] == {"file_name": GEMINI_FILE_NAME}


def test_gemini_output_file_name_fallback_chain(env):
    # Doc:  docs/batch-ocr.md — Gemini batch result download
    # Rule: when responsesFile is absent, output file name falls back to
    #       response.dest.fileName (and ultimately job_data.dest.fileName).
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    poll = {"done": True, "response": {"dest": {"fileName": GEMINI_OUTPUT_FILE}}}
    captured = _run_gemini(env, task_id, {}, poll_response=poll)

    assert captured.get("download_called") is True


def test_gemini_poll_job_state_failed_finishes_error_without_download(env):
    # Doc:  docs/batch-ocr.md — Gemini batch status polling
    # Rule: a terminal JOB_STATE_FAILED status ends the task as "error" without
    #       downloading results.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    env.add_doc(filename="a.pdf", ocr_text=None)

    poll = {"metadata": {"state": "JOB_STATE_FAILED"}, "error": {"message": "internal error"}}
    captured = _run_gemini(env, task_id, {}, poll_response=poll)

    assert "download_called" not in captured
    assert env.get_task(task_id).status == "error"


def _gemini_result_line(key: str, text: str) -> str:
    return json.dumps({"key": key, "response": {"candidates": [{"content": {"parts": [{"text": text}]}}]}})


def test_gemini_vision_success_writes_ocr_and_analysis_fields(env):
    # Doc:  docs/batch-ocr.md — Gemini batch result saving (vision mode)
    # Rule: a successful vision-mode result writes both ocr_text (from the
    #       "text" field) and every analysis field, marking both statuses "done".
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    payload = json.dumps({"text": "verbatim transcription", "summary": "s", "document_type": "invoice"})
    _run_gemini(env, task_id, {}, download_text=_gemini_result_line(str(doc_id), payload))

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "verbatim transcription"
    assert doc.ocr_status == "done"
    assert doc.summary == "s"
    assert doc.document_type == "invoice"
    assert doc.analysis_status == "done"


def test_gemini_text_only_success_leaves_ocr_text_untouched(env):
    # Doc:  docs/batch-ocr.md — Gemini batch result saving (text-only mode)
    # Rule: a text-only result never touches ocr_text/ocr_status (OCR text
    #       already existed); only the analysis fields are written.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text="original ocr text", ocr_model="tesseract", ocr_status="done")

    payload = json.dumps({"summary": "s2", "document_type": "receipt"})
    _run_gemini(env, task_id, {"scope": 2}, download_text=_gemini_result_line(str(doc_id), payload))

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "original ocr text"     # untouched
    assert doc.ocr_model == "tesseract"             # untouched
    assert doc.summary == "s2"
    assert doc.document_type == "receipt"
    assert doc.analysis_status == "done"


def test_gemini_vision_error_line_marks_ocr_error(env):
    # Doc:  docs/batch-ocr.md — Gemini batch result saving
    # Rule: an error on a vision-mode request marks ocr_status="error" (OCR
    #       itself never completed for this document).
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    result_line = json.dumps({"key": str(doc_id), "error": {"message": "content blocked"}})
    _run_gemini(env, task_id, {}, download_text=result_line)

    doc = env.get_doc(doc_id)
    assert doc.ocr_status == "error"
    assert doc.ocr_error == "content blocked"


def test_gemini_text_only_error_line_does_not_touch_ocr_status(env):
    # Doc:  docs/batch-ocr.md — Gemini batch result saving
    # Rule: an error on a text-only request leaves ocr_status untouched (OCR
    #       text already existed and is not affected by an analysis failure).
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text="already have text", ocr_status="done")

    result_line = json.dumps({"key": str(doc_id), "error": {"message": "analysis failed"}})
    _run_gemini(env, task_id, {"scope": 2}, download_text=result_line)

    doc = env.get_doc(doc_id)
    assert doc.ocr_status == "done"
    assert doc.ocr_error is None


def test_gemini_vision_unparseable_response_falls_back_to_raw_ocr_only(env):
    # Doc:  docs/batch-ocr.md — Gemini batch result saving (fallback path)
    # Rule: when the vision response isn't valid JSON, the raw text is saved as
    #       ocr_text/ocr_status="done" and analysis is left pending rather than
    #       the whole result being dropped.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text=None)

    _run_gemini(env, task_id, {}, download_text=_gemini_result_line(str(doc_id), "not json at all"))

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "not json at all"
    assert doc.ocr_status == "done"
    assert doc.analysis_status == "pending"


def test_gemini_resume_job_id_skips_submission(env):
    # Doc:  docs/batch-ocr.md §Resume support
    # Rule: resume_batch_job_id skips document collection/upload/create — only
    #       the existing job is polled and downloaded, with mode recomputed
    #       per-document from current ocr_text state.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.pdf", ocr_text="already has text", ocr_status="done")

    payload = json.dumps({"summary": "resumed", "document_type": "invoice"})
    captured = _run_gemini(
        env, task_id, {"resume_batch_job_id": GEMINI_BATCH_JOB_NAME},
        download_text=_gemini_result_line(str(doc_id), payload),
    )

    assert "jsonl_bytes" not in captured
    assert "batch_create_body" not in captured
    assert env.get_doc(doc_id).summary == "resumed"


# ═══════════════════ .docx/.txt native-extraction routing ═══════════════════════

def _forbid_httpx():
    def _ctor(*a, **k):
        raise AssertionError("httpx.AsyncClient should not be called")
    return _ctor


def test_mistral_docx_extracted_natively_not_sent_to_mistral(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — .docx has no page image, Mistral OCR doesn't apply
    # Rule: a .docx document is extracted natively (ocr_model="native") and the
    #       task finishes "done" without ever calling the Mistral API.
    env.make_provider("mistral")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.docx", filepath="/lib/a.docx", ocr_text=None)
    monkeypatch.setattr(batch_ocr_mistral, "_extract_native_text", lambda path: "docx body text")

    with patch("httpx.AsyncClient", _forbid_httpx()):
        asyncio.run(run_batch_ocr_mistral(task_id, {}))

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "docx body text"
    assert doc.ocr_status == "done"
    assert doc.ocr_model == "native"
    assert doc.vision_status == "skipped"

    task = env.get_task(task_id)
    assert task.status == "done"
    assert task.result_summary["processed"] == 1
    assert task.result_summary["native"] == 1


def test_mistral_mixed_batch_docx_excluded_pdf_included(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — mixed-format batch scope
    # Rule: in a batch with both .docx and .pdf, only the .pdf is sent to
    #       Mistral; the .docx's native-extraction count folds into "processed".
    env.make_provider("mistral", model="mistral-ocr-latest")
    task_id = env.make_task("batch_ocr_mistral")
    docx_id = env.add_doc(filename="a.docx", filepath="/lib/a.docx", ocr_text=None)
    pdf_id = env.add_doc(filename="b.pdf", filepath="/lib/b.pdf", ocr_text=None)
    monkeypatch.setattr(batch_ocr_mistral, "_extract_native_text", lambda path: "docx body text")

    result_line = json.dumps({
        "custom_id": str(pdf_id),
        "response": {"body": {"pages": [{"markdown": "pdf text"}], "usage_info": {"pages_processed": 1}}},
    })
    captured = _run_mistral(env, task_id, {}, download_text=result_line)

    filename, content, content_type = captured["upload_files"]["file"]
    lines = _jsonl_lines(content)
    assert len(lines) == 1
    assert lines[0]["custom_id"] == str(pdf_id)

    assert env.get_doc(docx_id).ocr_model == "native"

    task = env.get_task(task_id)
    assert task.result_summary["processed"] == 2  # 1 native + 1 via Mistral


def test_mistral_docx_extraction_failure_marks_ocr_error(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — native docx extraction contract
    # Rule: a corrupt/unreadable .docx sets ocr_status="error" with the
    #       exception message, mirroring the OCR failure contract, and the
    #       task ends "error" when no document could be processed at all.
    env.make_provider("mistral")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.docx", filepath="/lib/a.docx", ocr_text=None)
    monkeypatch.setattr(batch_ocr_mistral, "_extract_native_text",
                         lambda path: (_ for _ in ()).throw(ValueError("corrupt file")))

    with patch("httpx.AsyncClient", _forbid_httpx()):
        asyncio.run(run_batch_ocr_mistral(task_id, {}))

    doc = env.get_doc(doc_id)
    assert doc.ocr_status == "error"
    assert doc.ocr_error == "corrupt file"
    assert env.get_task(task_id).status == "error"


def test_gemini_docx_routed_to_text_only_after_native_extraction(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — .docx has no page image; native extraction
    #       routes it into the existing text-only branch
    # Rule: a .docx document with no ocr_text yet is extracted natively first,
    #       then built as a text-only (not vision) request using that text.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.docx", filepath="/lib/a.docx", ocr_text=None)
    monkeypatch.setattr(batch_ocr_gemini, "_extract_native_text", lambda path: "docx body text")

    captured = _run_gemini(env, task_id, {})

    lines = _jsonl_lines(captured["jsonl_bytes"])
    assert len(lines) == 1
    req = lines[0]["request"]
    assert req["system_instruction"] == {"parts": [{"text": batch_ocr_gemini.ANALYSIS_SYSTEM}]}
    assert req["contents"][0]["parts"][0]["text"] == "OCR Text:\ndocx body text"

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "docx body text"
    assert doc.ocr_status == "done"
    assert doc.ocr_model == "native"
    assert doc.vision_status == "skipped"


def test_gemini_docx_extraction_failure_marks_ocr_error_and_excluded(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — native docx extraction contract
    # Rule: a failed native extraction sets ocr_status="error" and the document
    #       is excluded from the batch request entirely (not sent to Gemini).
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.docx", filepath="/lib/a.docx", ocr_text=None)
    monkeypatch.setattr(batch_ocr_gemini, "_extract_native_text",
                         lambda path: (_ for _ in ()).throw(ValueError("corrupt file")))

    asyncio.run(run_batch_ocr_gemini(task_id, {}))

    doc = env.get_doc(doc_id)
    assert doc.ocr_status == "error"
    assert doc.ocr_error == "corrupt file"
    assert env.get_task(task_id).status == "error"


def test_mistral_txt_extracted_natively_not_sent_to_mistral(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — .txt has no page image, same routing as .docx
    # Rule: a .txt document is extracted natively (ocr_model="native") and the
    #       task finishes "done" without ever calling the Mistral API.
    env.make_provider("mistral")
    task_id = env.make_task("batch_ocr_mistral")
    doc_id = env.add_doc(filename="a.txt", filepath="/lib/a.txt", ocr_text=None)
    monkeypatch.setattr(batch_ocr_mistral, "_extract_native_text", lambda path: "plain text body")

    with patch("httpx.AsyncClient", _forbid_httpx()):
        asyncio.run(run_batch_ocr_mistral(task_id, {}))

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "plain text body"
    assert doc.ocr_status == "done"
    assert doc.ocr_model == "native"
    assert doc.vision_status == "skipped"

    task = env.get_task(task_id)
    assert task.status == "done"
    assert task.result_summary["native"] == 1


def test_gemini_txt_routed_to_text_only_after_native_extraction(env, monkeypatch):
    # Doc:  docs/batch-ocr.md — .txt has no page image; same routing as .docx
    # Rule: a .txt document with no ocr_text yet is extracted natively first,
    #       then built as a text-only (not vision) request using that text.
    env.make_provider("gemini")
    task_id = env.make_task("batch_ocr_gemini")
    doc_id = env.add_doc(filename="a.txt", filepath="/lib/a.txt", ocr_text=None)
    monkeypatch.setattr(batch_ocr_gemini, "_extract_native_text", lambda path: "plain text body")

    captured = _run_gemini(env, task_id, {})

    lines = _jsonl_lines(captured["jsonl_bytes"])
    assert len(lines) == 1
    req = lines[0]["request"]
    assert req["system_instruction"] == {"parts": [{"text": batch_ocr_gemini.ANALYSIS_SYSTEM}]}
    assert req["contents"][0]["parts"][0]["text"] == "OCR Text:\nplain text body"

    doc = env.get_doc(doc_id)
    assert doc.ocr_text == "plain text body"
    assert doc.ocr_status == "done"
    assert doc.ocr_model == "native"
    assert doc.vision_status == "skipped"
