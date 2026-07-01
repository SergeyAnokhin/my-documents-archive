import hashlib
import mimetypes
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import settings

# Matches [2024-03] style
_BRACKET_DATE = re.compile(r"\[(\d{4})-(\d{2})\]")
# Matches 2024/03/ or 2024\03\ (slash-separated sub-dirs)
_SLASH_DATE   = re.compile(r"[/\\](\d{4})[/\\](\d{2})(?:[/\\]|$)")
# Matches 2024-03 as a standalone path component (dir named YYYY-MM)
_DASH_DIR     = re.compile(r"[/\\](\d{4})-(\d{2})(?:[/\\]|$)")

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/heic",
    "image/heif",
    "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif", ".webp", ".docx"}


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
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
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


def extract_folder_date(path: Path) -> Optional[datetime]:
    """Return the 1st of the month encoded in the path.

    Recognises: [YYYY-MM], YYYY/MM/, YYYY\\MM\\, and YYYY-MM/ (bare dir name).
    """
    s = str(path)
    for pattern in (_BRACKET_DATE, _SLASH_DATE, _DASH_DIR):
        m = pattern.search(s)
        if m:
            try:
                return datetime(int(m.group(1)), int(m.group(2)), 1)
            except ValueError:
                pass
    return None


def infer_document_date(path: Path) -> Optional[datetime]:
    """Best-guess document date from path and file metadata.

    Priority (highest to lowest):
      1. Folder date encoded in path (YYYY-MM, [YYYY-MM], YYYY/MM)
      2. File creation time — only when it differs from today (copy artefacts ignored)
    Returns None when nothing meaningful is found; UI then falls back to added_at.
    """
    folder_date = extract_folder_date(path)
    if folder_date:
        return folder_date
    try:
        ctime = datetime.fromtimestamp(path.stat().st_ctime)
        if ctime.date() < datetime.now().date():
            return ctime
    except OSError:
        pass
    return None


def check_library_accessible(library: Path) -> bool:
    """True when the library disk is mounted and the .docintell sentinel dir exists.

    .docintell is created at first backend startup on the same disk as user
    documents. If it is absent the disk is either offline or the library was
    never initialised — both cases should block a destructive sync operation.
    """
    try:
        return (library / ".docintell").is_dir()
    except OSError:
        return False


def scan_library_for_new_files(known_paths: set[str]) -> list[Path]:
    """Walk the library directory and return supported file paths not in known_paths.

    Skips the .docintell sub-directory (thumbnails, DB, Chroma) and any other
    dot-prefixed hidden directory so they are never mistaken for user documents.
    """
    library = get_library_path()
    docintell_dir = library / ".docintell"
    new_files: list[Path] = []
    for p in library.rglob("*"):
        # Skip anything inside .docintell or other hidden dirs
        if any(part.startswith(".") for part in p.parts[len(library.parts):]):
            continue
        if p.is_file() and is_supported(p) and str(p) not in known_paths:
            new_files.append(p)
    return new_files
