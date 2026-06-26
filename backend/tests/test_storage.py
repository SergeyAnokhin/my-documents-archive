"""Pins documented storage rules — see docs/testing.md and docs/code-map.md (storage.py).

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
from pathlib import Path

from app.config import settings
from app.services import storage


def test_guess_mime_falls_back_by_extension():
    # Doc:  docs/code-map.md → services/storage.py ("MIME detection");
    #       docs/testing.md row: "MIME fallback by extension".
    # Rule: known extensions map to their MIME; unknown → application/octet-stream.
    assert storage.guess_mime(Path("scan.pdf")) == "application/pdf"
    assert storage.guess_mime(Path("photo.heic")) == "image/heic"
    assert storage.guess_mime(Path("mystery.xyz")) == "application/octet-stream"


def test_is_supported_checks_extension_case_insensitive():
    # Doc:  docs/testing.md row: "supported-extension check".
    # Rule: the supported-type gate is by extension, case-insensitive (.JPG == .jpg).
    assert storage.is_supported(Path("a.JPG")) is True
    assert storage.is_supported(Path("a.pdf")) is True
    assert storage.is_supported(Path("a.txt")) is False


def test_save_uploaded_file_avoids_name_collision(tmp_path, monkeypatch):
    # Doc:  docs/code-map.md → storage.py ("saving uploads to YYYY/MM/");
    #       docs/testing.md row: "upload name-collision (doc.png → doc_1.png)".
    # Rule: a colliding name gets a numeric suffix; both land in the same YYYY/MM/ folder.
    monkeypatch.setattr(settings, "library_path", str(tmp_path))
    src = tmp_path / "src.png"
    src.write_bytes(b"data")

    first = storage.save_uploaded_file(src, "doc.png")
    second = storage.save_uploaded_file(src, "doc.png")

    assert first.name == "doc.png"
    assert second.name == "doc_1.png"
    assert first.parent == second.parent  # same YYYY/MM/ folder
