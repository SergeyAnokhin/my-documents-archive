from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "DocIntel"
    app_version: str = "0.1.0"

    # Document library root — the folder containing .docintell/ and user files
    library_path: str = "./library"

    # Derived paths (computed from library_path)
    @property
    def docintell_dir(self) -> Path:
        return Path(self.library_path) / ".docintell"

    @property
    def db_path(self) -> str:
        return str(self.docintell_dir / "docintell.db")

    @property
    def thumbnails_dir(self) -> Path:
        return self.docintell_dir / "thumbnails"

    @property
    def chroma_dir(self) -> Path:
        return self.docintell_dir / "chroma"

    # OCR config
    ocr_engine: str = "tesseract"  # "tesseract" | "external"
    external_ocr_url: str = "http://localhost:8001"
    ocr_languages: str = "rus+fra+eng"

    # AI providers (populated via admin UI — stored in DB, not env)
    # These are fallback env overrides
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""
    openrouter_api_key: str = ""
    mistral_api_key: str = ""

    # Indexing defaults
    enable_ai_vision: bool = False
    enable_ai_analysis: bool = False
    ai_analysis_model: str = ""
    ai_vision_model: str = ""

    # Celery / Redis
    redis_url: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
