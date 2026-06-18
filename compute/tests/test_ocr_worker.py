"""Pins documented OCR worker contract — see docs/api.md (OCR Worker)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_status_and_engine_list():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["engines"], list)  # may be empty if no engine installed


def test_ocr_rejects_unreadable_file():
    r = client.post(
        "/ocr",
        files={"file": ("junk.png", b"not-an-image", "image/png")},
    )
    assert r.status_code == 400
