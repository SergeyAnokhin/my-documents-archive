"""Pins documented OCR worker contract — see docs/compute-worker.md §Endpoints
and docs/api.md (OCR Worker).

Each test carries:
  Doc:  which documented area it protects (or "none" for code-only behavior)
  Rule: the specific behavior it asserts
"""
import asyncio
import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app, _to_images

client = TestClient(app)


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_health_reports_status_and_engine_list():
    # Doc:  docs/compute-worker.md §Endpoints — GET /health → {status, engines[], languages}.
    # Rule: status is "ok" and engines is a list (possibly empty if no engine installed).
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["engines"], list)  # may be empty if no engine installed


def test_ocr_rejects_unreadable_file():
    # Doc:  docs/compute-worker.md §Endpoints — POST /ocr. Pins the "Could not load
    #       image" → HTTP 400 path for an undecodable upload.
    # Rule: bytes that are not a valid image/PDF return 400, not a 500.
    r = client.post(
        "/ocr",
        files={"file": ("junk.png", b"not-an-image", "image/png")},
    )
    assert r.status_code == 400


# ── Image loading (the helper behind the 400 path + multi-page handling) ────────

def test_to_images_returns_empty_for_junk_bytes():
    # Doc:  none in prose docs — `_to_images` is the internal that drives the
    #       documented /ocr 400 (above). General test pinning current behavior.
    # Rule: unreadable bytes → [] (which the endpoint turns into a 400).
    assert asyncio.run(_to_images(b"not-an-image", ".png")) == []


def test_to_images_loads_a_valid_png():
    # Doc:  none in prose docs — general test pinning `_to_images`.
    # Rule: a valid raster decodes to a single image, normalised to RGB mode.
    images = asyncio.run(_to_images(_png_bytes(), ".png"))
    assert len(images) == 1
    assert images[0].mode == "RGB"  # always normalised to RGB
