"""
Native .txt text extraction — no OCR involved (the file already IS the text).

Mirrors docx_extract.py's role in the pipeline: the indexer treats plain-text
files as an OCR-equivalent step, storing the result with ocr_model="native".
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def extract_text_file(filepath: str) -> str:
    """Return the plain-text file's content, decoded as UTF-8 (falling back to latin-1).

    Raises on unreadable files — caller (indexer) is responsible for catching
    and marking ocr_status=error, same contract as ocr.py::extract_text().
    """
    data = Path(filepath).read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    # Normalise CRLF/CR line endings to LF (raw byte read skips Python's usual
    # universal-newline translation) — Windows-authored .txt files are CRLF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()
