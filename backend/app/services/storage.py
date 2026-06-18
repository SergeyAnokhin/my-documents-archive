import hashlib
import mimetypes
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import settings

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/heic",
    "image/heif",
    "image/webp",
}

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif", ".webp"}


def get_library_path() -> Path:
    p = Path(settings.library_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        # Fallback by extension
        ext = path.suffix.lower()
        mapping = {
            ".pdf": "application/pdf",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".tiff": "image/tiff",
            ".tif": "image/tiff",
            ".heic": "image/heic",
            ".heif": "image/heif",
            ".webp": "image/webp",
        }
        mime = mapping.get(ext, "application/octet-stream")
    return mime


def save_uploaded_file(source_path: Path, original_filename: str) -> Path:
    """
    Copies an uploaded temp file into the library under YYYY/MM/ structure.
    Returns the final destination path.
    """
    now = datetime.now()
    dest_dir = get_library_path() / str(now.year) / f"{now.month:02d}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / original_filename
    # Avoid name collisions
    counter = 1
    while dest_path.exists():
        stem = Path(original_filename).stem
        suffix = Path(original_filename).suffix
        dest_path = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    shutil.copy2(source_path, dest_path)
    return dest_path


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def scan_library_for_new_files(known_paths: set[str]) -> list[Path]:
    """Walk the library directory and return paths not in known_paths."""
    library = get_library_path()
    new_files: list[Path] = []
    for p in library.rglob("*"):
        if p.is_file() and is_supported(p) and str(p) not in known_paths:
            new_files.append(p)
    return new_files
