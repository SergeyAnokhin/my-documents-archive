"""
DocIntel OCR Worker — external compute service.

Accepts image/PDF uploads over HTTP and returns recognized text.
Designed to run on a more powerful machine on the local network.

Usage:
    pip install -r requirements.txt
    uvicorn app.main:app --host 0.0.0.0 --port 8001
"""

import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

app = FastAPI(
    title="DocIntel OCR Worker",
    version="0.1.0",
    description="External OCR microservice for DocIntel",
)


OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "rus+fra+eng")


# ── Engine detection at startup ───────────────────────────────────────────────
# Run in a subprocess so a native DLL crash (e.g. bad CUDA build of torch)
# does not kill the main server process.

def _probe(module: str) -> bool:
    try:
        r = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            if err:
                print(f"[ocr-worker] {module} probe failed: {err[:300]}", flush=True)
            else:
                print(f"[ocr-worker] {module} probe exited with code {r.returncode}", flush=True)
        return r.returncode == 0
    except Exception as e:
        print(f"[ocr-worker] {module} probe error: {e}", flush=True)
        return False

_HAS_TESSERACT = False
try:
    import pytesseract
    pytesseract.get_tesseract_version()
    _HAS_TESSERACT = True
except Exception:
    pass

_HAS_EASYOCR = _probe("easyocr")

print(f"[ocr-worker] engines: tesseract={_HAS_TESSERACT}, easyocr={_HAS_EASYOCR}", flush=True)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    engines = []
    if _HAS_TESSERACT:
        engines.append("tesseract")
    if _HAS_EASYOCR:
        engines.append("easyocr")
    return {"status": "ok", "engines": engines, "languages": OCR_LANGUAGES}


# ── OCR endpoint ──────────────────────────────────────────────────────────────

@app.post("/ocr")
async def run_ocr(
    file: UploadFile = File(...),
    engine: Literal["tesseract", "easyocr", "auto"] = Query("auto"),
    languages: str = Query(""),
):
    """
    Accept an image or PDF, return recognized text.

    - engine: "tesseract" | "easyocr" | "auto" (tries easyocr first, falls back to tesseract)
    - languages: override language codes (e.g. "rus+fra+eng" for tesseract, "ru,fr,en" for easyocr)
    """
    content = await file.read()
    suffix = Path(file.filename or "file").suffix.lower()
    langs = languages or OCR_LANGUAGES

    images = await _to_images(content, suffix)
    if not images:
        raise HTTPException(status_code=400, detail="Could not load image from file")

    texts: list[str] = []
    for img in images:
        text = await _ocr_image(img, engine, langs)
        texts.append(text)

    return {"text": "\n\n".join(texts), "pages": len(images), "engine": engine}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _to_images(content: bytes, suffix: str) -> list[Image.Image]:
    if suffix == ".pdf":
        try:
            from pdf2image import convert_from_bytes
            return convert_from_bytes(content, dpi=200)
        except Exception:
            return []
    else:
        try:
            img = Image.open(io.BytesIO(content)).convert("RGB")
            return [img]
        except Exception:
            return []


async def _ocr_image(
    img: Image.Image,
    engine: str,
    langs: str,
) -> str:
    if engine == "easyocr" or engine == "auto":
        try:
            return _easyocr(img, langs)
        except Exception:
            if engine == "easyocr":
                raise
            # fall through to tesseract

    return _tesseract(img, langs)


def _tesseract(img: Image.Image, langs: str) -> str:
    import pytesseract
    # Tesseract uses "+" separator: "rus+fra+eng"
    tess_langs = langs.replace(",", "+")
    return pytesseract.image_to_string(img, lang=tess_langs)


def _easyocr(img: Image.Image, langs: str) -> str:
    import PIL.Image as _pil
    if not hasattr(_pil, "ANTIALIAS"):
        _pil.ANTIALIAS = _pil.LANCZOS  # Pillow ≥10 removed ANTIALIAS
    import easyocr
    import numpy as np
    # EasyOCR uses list of 2-letter codes: ["ru", "fr", "en"]
    lang_map = {"rus": "ru", "fra": "fr", "eng": "en"}
    lang_list = []
    for part in langs.replace("+", ",").split(","):
        part = part.strip()
        lang_list.append(lang_map.get(part, part))

    # Cyrillic model is only compatible with English — drop other Latin langs
    cyrillic_langs = {"ru", "rs_cyrillic", "be", "bg", "uk", "mn"}
    if any(l in cyrillic_langs for l in lang_list):
        lang_list = [l for l in lang_list if l in cyrillic_langs or l == "en"]

    reader = easyocr.Reader(lang_list, gpu=False, verbose=False)
    results = reader.readtext(np.array(img), detail=0)
    return " ".join(results)
