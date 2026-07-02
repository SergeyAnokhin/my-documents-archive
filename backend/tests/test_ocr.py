"""Pins the external OCR worker request/response handling and the local-vs-
external fallback chain — see docs/code-map.md (services/ocr.py) and
docs/compute-worker.md.

`_external_ocr()` posts the document file to the external OCR worker (a
separate, potentially remote/paid-compute service) and parses back
(text, engine). `extract_text()` decides, per call, whether to use the
external worker or local Tesseract, with documented fallback behavior on
failure. All httpx calls are mocked (no network) so these tests run offline.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services import ocr as ocr_module
from app.services.ocr import _external_ocr, _mime_for, extract_text


def _mock_httpx_post(json_data: dict):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    client = MagicMock()
    client.post = AsyncMock(return_value=resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx), client


# ── _external_ocr: request construction ─────────────────────────────────────────

def test_external_ocr_posts_documented_url_params_and_file(tmp_path, monkeypatch):
    # Doc:  docs/compute-worker.md — POST /ocr accepts a file + engine/languages
    # Rule: the request targets "{external_ocr_url}/ocr" with engine=auto and
    #       the configured languages, uploading the file with the right mimetype.
    monkeypatch.setattr(settings, "external_ocr_url", "http://worker.example:8001")
    monkeypatch.setattr(settings, "ocr_languages", "rus+eng")
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-fake")

    ctor, client = _mock_httpx_post({"text": "hi", "engine": "easyocr"})
    with patch("httpx.AsyncClient", ctor):
        asyncio.run(_external_ocr(path))

    call = client.post.call_args
    assert call.args[0] == "http://worker.example:8001/ocr"
    assert call.kwargs["params"] == {"engine": "auto", "languages": "rus+eng"}
    filename, _fh, mimetype = call.kwargs["files"]["file"]
    assert filename == "scan.pdf"
    assert mimetype == "application/pdf"


def test_external_ocr_strips_trailing_slash_from_configured_url(tmp_path, monkeypatch):
    # Doc:  docs/compute-worker.md — worker URL configuration
    # Rule: a trailing slash on external_ocr_url doesn't produce a double slash.
    monkeypatch.setattr(settings, "external_ocr_url", "http://worker.example:8001/")
    path = tmp_path / "scan.png"
    path.write_bytes(b"fake")

    ctor, client = _mock_httpx_post({"text": "", "engine": "easyocr"})
    with patch("httpx.AsyncClient", ctor):
        asyncio.run(_external_ocr(path))

    assert client.post.call_args.args[0] == "http://worker.example:8001/ocr"


# ── _external_ocr: response parsing ─────────────────────────────────────────────

def test_external_ocr_returns_text_and_engine_from_response(tmp_path):
    # Doc:  docs/code-map.md — services/ocr.py extract_text() returns (text, engine)
    # Rule: the response's "text"/"engine" fields are returned verbatim.
    path = tmp_path / "a.png"
    path.write_bytes(b"fake")
    ctor, client = _mock_httpx_post({"text": "hello world", "engine": "easyocr"})
    with patch("httpx.AsyncClient", ctor):
        text, engine = asyncio.run(_external_ocr(path))
    assert (text, engine) == ("hello world", "easyocr")


def test_external_ocr_defaults_engine_to_easyocr_when_absent(tmp_path):
    # Doc:  docs/code-map.md — services/ocr.py; docs/compute-worker.md
    # Rule: if the worker response omits "engine", it defaults to "easyocr"
    #       (the worker predates per-engine attribution).
    path = tmp_path / "a.png"
    path.write_bytes(b"fake")
    ctor, client = _mock_httpx_post({"text": "hi"})
    with patch("httpx.AsyncClient", ctor):
        text, engine = asyncio.run(_external_ocr(path))
    assert engine == "easyocr"


def test_external_ocr_missing_text_defaults_to_empty_string(tmp_path):
    # Doc:  none — defensive default for a malformed/empty worker response
    # Rule: a response with no "text" key returns "" rather than raising.
    path = tmp_path / "a.png"
    path.write_bytes(b"fake")
    ctor, client = _mock_httpx_post({"engine": "tesseract"})
    with patch("httpx.AsyncClient", ctor):
        text, engine = asyncio.run(_external_ocr(path))
    assert text == ""


# ── _mime_for ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename,expected", [
    ("a.pdf", "application/pdf"),
    ("a.PDF", "application/pdf"),
    ("a.jpg", "image/jpeg"),
    ("a.jpeg", "image/jpeg"),
    ("a.png", "image/png"),
    ("a.tiff", "image/tiff"),
    ("a.heic", "image/heic"),
    ("a.webp", "image/webp"),
    ("a.xyz", "application/octet-stream"),
])
def test_mime_for_maps_known_extensions_case_insensitively(filename, expected):
    # Doc:  services/ocr.py — _mime_for
    # Rule: known extensions map to their documented MIME type (case-insensitive);
    #       anything unrecognised falls back to application/octet-stream.
    from pathlib import Path
    assert _mime_for(Path(filename)) == expected


# ── extract_text: fallback chain ─────────────────────────────────────────────────

def test_extract_text_legacy_external_engine_success(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py "Default priority (env-var based)"
    # Rule: with ocr_engine="external" and engines=None, a successful external
    #       call is returned as-is; local Tesseract is never invoked.
    monkeypatch.setattr(settings, "ocr_engine", "external")
    monkeypatch.setattr(ocr_module, "_external_ocr", AsyncMock(return_value=("ext text", "easyocr")))
    tesseract_mock = MagicMock(side_effect=AssertionError("tesseract should not run"))
    monkeypatch.setattr(ocr_module, "_local_tesseract", tesseract_mock)

    text, engine = asyncio.run(extract_text("/lib/a.pdf"))
    assert (text, engine) == ("ext text", "easyocr")


def test_extract_text_legacy_external_failure_falls_back_to_tesseract(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py "Default priority (env-var based)"
    # Rule: when the external worker raises, extract_text falls back to local
    #       Tesseract rather than propagating the error.
    monkeypatch.setattr(settings, "ocr_engine", "external")
    monkeypatch.setattr(ocr_module, "_external_ocr", AsyncMock(side_effect=RuntimeError("worker down")))
    monkeypatch.setattr(ocr_module, "_local_tesseract", MagicMock(return_value="fallback text"))

    text, engine = asyncio.run(extract_text("/lib/a.pdf"))
    assert (text, engine) == ("fallback text", "tesseract")


def test_extract_text_db_configured_engines_first_success_wins(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py "DB-configured priority"
    # Rule: with an explicit engines list, the first engine to succeed is
    #       returned without trying later engines in the list.
    monkeypatch.setattr(ocr_module, "_external_ocr", AsyncMock(return_value=("easyocr text", "easyocr")))
    tesseract_mock = MagicMock(side_effect=AssertionError("should not be reached"))
    monkeypatch.setattr(ocr_module, "_local_tesseract", tesseract_mock)

    text, engine = asyncio.run(extract_text("/lib/a.pdf", engines=["easyocr", "tesseract"]))
    assert (text, engine) == ("easyocr text", "easyocr")


def test_extract_text_db_configured_falls_through_on_failure(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py "DB-configured priority"
    # Rule: when the first engine in the list fails, the next one is tried.
    monkeypatch.setattr(ocr_module, "_external_ocr", AsyncMock(side_effect=RuntimeError("worker down")))
    monkeypatch.setattr(ocr_module, "_local_tesseract", MagicMock(return_value="tesseract text"))

    text, engine = asyncio.run(extract_text("/lib/a.pdf", engines=["easyocr", "tesseract"]))
    assert (text, engine) == ("tesseract text", "tesseract")


def test_extract_text_raises_last_exception_when_all_engines_fail(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py "DB-configured priority"
    # Rule: if every configured engine fails, the last exception is raised
    #       (not swallowed), so the caller can mark the document ocr_status=error.
    monkeypatch.setattr(ocr_module, "_external_ocr", AsyncMock(side_effect=RuntimeError("worker down")))
    monkeypatch.setattr(ocr_module, "_local_tesseract", MagicMock(side_effect=ValueError("cannot load image")))

    with pytest.raises(ValueError, match="cannot load image"):
        asyncio.run(extract_text("/lib/a.pdf", engines=["easyocr", "tesseract"]))


def test_extract_text_raises_when_no_engines_configured():
    # Doc:  docs/code-map.md — services/ocr.py "DB-configured priority"
    # Rule: an empty engines list raises rather than silently doing nothing.
    with pytest.raises(ValueError, match="No OCR engines configured"):
        asyncio.run(extract_text("/lib/a.pdf", engines=[]))


# ── extract_text: native PDF text-layer fast-path ─────────────────────────────

def test_extract_text_pdf_uses_native_text_layer_when_available(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py native PDF fast-path
    # Rule: for a .pdf with a usable embedded text layer, extract_text returns
    #       it as ("native") and never touches the OCR engines.
    monkeypatch.setattr(ocr_module, "extract_pdf_text", MagicMock(return_value="the full contract text"))
    tesseract_mock = MagicMock(side_effect=AssertionError("tesseract should not run"))
    monkeypatch.setattr(ocr_module, "_local_tesseract", tesseract_mock)

    text, engine = asyncio.run(extract_text("/lib/contract.pdf", engines=["tesseract"]))
    assert (text, engine) == ("the full contract text", "native")


def test_extract_text_pdf_falls_back_to_ocr_when_no_text_layer(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py native PDF fast-path
    # Rule: a scanned PDF (extract_pdf_text returns None) falls through to the
    #       normal OCR engine chain unchanged.
    monkeypatch.setattr(ocr_module, "extract_pdf_text", MagicMock(return_value=None))
    monkeypatch.setattr(ocr_module, "_local_tesseract", MagicMock(return_value="ocr text"))

    text, engine = asyncio.run(extract_text("/lib/scan.pdf", engines=["tesseract"]))
    assert (text, engine) == ("ocr text", "tesseract")


def test_extract_text_pdf_falls_back_to_ocr_when_native_extraction_raises(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py native PDF fast-path
    # Rule: a corrupt/encrypted PDF (extract_pdf_text raises) doesn't fail
    #       extract_text — it falls back to OCR instead of propagating.
    monkeypatch.setattr(ocr_module, "extract_pdf_text", MagicMock(side_effect=ValueError("corrupt")))
    monkeypatch.setattr(ocr_module, "_local_tesseract", MagicMock(return_value="ocr text"))

    text, engine = asyncio.run(extract_text("/lib/scan.pdf", engines=["tesseract"]))
    assert (text, engine) == ("ocr text", "tesseract")


def test_extract_text_non_pdf_skips_native_extraction(monkeypatch):
    # Doc:  docs/code-map.md — services/ocr.py native PDF fast-path
    # Rule: the native text-layer check only applies to .pdf files.
    called = MagicMock(return_value="should not be used")
    monkeypatch.setattr(ocr_module, "extract_pdf_text", called)
    monkeypatch.setattr(ocr_module, "_local_tesseract", MagicMock(return_value="ocr text"))

    text, engine = asyncio.run(extract_text("/lib/scan.png", engines=["tesseract"]))
    assert (text, engine) == ("ocr text", "tesseract")
    called.assert_not_called()
