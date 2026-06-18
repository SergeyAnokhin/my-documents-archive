"""OCR processing using Tesseract. Handles images and PDFs."""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

from backend.config import TESSERACT_LANGUAGES

logger = logging.getLogger(__name__)


def image_to_text(image_path: Path, lang: str = TESSERACT_LANGUAGES) -> str:
    """Extract text from a single image using Tesseract.

    Falls back gracefully if Tesseract is not installed."""
    if not _tesseract_available():
        return ""

    try:
        result = subprocess.run(
            [
                "tesseract", str(image_path), "stdout",
                "-l", lang,
                "--psm", "3",  # Auto page segmentation
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.warning("Tesseract error: %s", result.stderr)
            return ""
        return result.stdout.strip()
    except Exception as e:
        logger.warning("OCR failed for %s: %s", image_path, e)
        return ""


def pdf_to_text(pdf_path: Path) -> str:
    """Extract text from PDF by rendering pages as images and running OCR.

    Embedded text in PDFs often has broken font-to-Unicode mappings
    (especially for Cyrillic), so we always use the OCR path."""
    parts: list[str] = []

    try:
        doc = fitz.open(str(pdf_path))
        for i, page in enumerate(doc):
            # Render page to image for OCR (300 DPI)
            pix = page.get_pixmap(dpi=300)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(pix.tobytes("png"))
                tmp_path = Path(f.name)

            ocr_text = image_to_text(tmp_path)
            if ocr_text:
                parts.append(ocr_text)

            tmp_path.unlink(missing_ok=True)

        doc.close()
    except Exception as e:
        logger.warning("PDF OCR failed for %s: %s", pdf_path, e)

    return "\n\n".join(parts)


def process_document(file_path: Path) -> str:
    """Run OCR on a document. Detects PDF vs image, returns extracted text."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return pdf_to_text(file_path)
    elif suffix in {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".heif"}:
        # For images, try direct OCR first
        try:
            return image_to_text(file_path)
        except Exception:
            # For formats Tesseract might not handle natively (HEIC),
            # convert via Pillow first
            try:
                img = Image.open(file_path)
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    img.save(f, format="PNG")
                    tmp_path = Path(f.name)
                text = image_to_text(tmp_path)
                tmp_path.unlink(missing_ok=True)
                return text
            except Exception as e:
                logger.warning("Image OCR failed for %s: %s", file_path, e)
                return ""
    return ""


def _tesseract_available() -> bool:
    """Check if tesseract binary is installed."""
    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
