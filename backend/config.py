"""Application configuration."""
import os
from pathlib import Path

# Base directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DOCINTEL_DATA_DIR", PROJECT_ROOT / "data"))
DOCUMENTS_DIR = Path(os.getenv("DOCINTEL_DOCUMENTS_DIR", DATA_DIR / "documents"))

# Database
DB_DIR = DOCUMENTS_DIR / ".docintell"
DB_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_DIR / 'docintell.db'}"

# Thumbnails
THUMBNAILS_DIR = DB_DIR / "thumbnails"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

# Documents
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

# Supported formats
SUPPORTED_FORMATS = {
    ".pdf", ".jpg", ".jpeg", ".png",
    ".tiff", ".tif", ".heic", ".heif", ".webp"
}

# OCR
TESSERACT_LANGUAGES = "rus+fra+eng"
