"""Pins documented storage rules — see docs/testing.md and docs/code-map.md (storage.py)."""
from pathlib import Path

from app.config import settings
from app.services import storage


def test_guess_mime_falls_back_by_extension():
    assert storage.guess_mime(Path("scan.pdf")) == "application/pdf"
    assert storage.guess_mime(Path("photo.heic")) == "image/heic"
    assert storage.guess_mime(Path("mystery.xyz")) == "application/octet-stream"


def test_is_supported_checks_extension_case_insensitive():
    assert storage.is_supported(Path("a.JPG")) is True
    assert storage.is_supported(Path("a.pdf")) is True
    assert storage.is_supported(Path("a.txt")) is False


def test_save_uploaded_file_avoids_name_collision(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"data")

    first = storage.save_uploaded_file(src, "doc.png")
    second = storage.save_uploaded_file(src, "doc.png")

    assert first.name == "doc.png"
    assert second.name == "doc_1.png"
    assert first.parent == second.parent  # same YYYY/MM/ folder
