"""Pins native .txt text extraction — see docs/code-map.md (services/text_extract.py).

extract_text_file() is the .txt equivalent of docx_extract.py::extract_docx_text —
the file already IS the text, so this just reads and normalises it.
"""
from app.services.text_extract import extract_text_file


def test_extract_text_file_reads_utf8_content(tmp_path):
    # Rule: plain UTF-8 content is read back verbatim (aside from stripping).
    path = tmp_path / "a.txt"
    path.write_text("Hello, world.\nSecond line.", encoding="utf-8")
    assert extract_text_file(str(path)) == "Hello, world.\nSecond line."


def test_extract_text_file_strips_bom(tmp_path):
    # Rule: a UTF-8 BOM (common from Windows Notepad "UTF-8" saves) is not
    # leaked into the extracted text.
    path = tmp_path / "b.txt"
    path.write_bytes("Bonjour".encode("utf-8-sig"))
    assert extract_text_file(str(path)) == "Bonjour"


def test_extract_text_file_falls_back_to_latin1(tmp_path):
    # Rule: bytes that are not valid UTF-8 (legacy Windows-1252/latin-1 saves)
    # are decoded as latin-1 rather than raising, so an oddly-encoded file
    # still gets indexed instead of erroring the whole pipeline.
    path = tmp_path / "c.txt"
    path.write_bytes("café".encode("latin-1"))
    assert extract_text_file(str(path)) == "café"


def test_extract_text_file_strips_surrounding_whitespace(tmp_path):
    # Rule: leading/trailing whitespace is trimmed, matching docx_extract's
    # per-block stripping convention.
    path = tmp_path / "d.txt"
    path.write_text("\n\n  padded text  \n\n", encoding="utf-8")
    assert extract_text_file(str(path)) == "padded text"
