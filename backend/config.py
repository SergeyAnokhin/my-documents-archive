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

# AI Provider defaults
import json
AI_CONFIG_PATH = DB_DIR / "ai_config.json"


def get_ai_config() -> dict:
    """Load AI provider configuration. Uses defaults if no config file."""
    defaults = {
        "provider": "deepseek",
        "analysis_model": "deepseek-chat",
        "analysis_enabled": True,
        "vision_model": "",
        "vision_enabled": False,
    }
    if AI_CONFIG_PATH.exists():
        try:
            saved = json.loads(AI_CONFIG_PATH.read_text())
            defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return defaults


def save_ai_config(config: dict) -> None:
    """Save AI provider configuration."""
    AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_CONFIG_PATH.write_text(json.dumps(config, indent=2))
