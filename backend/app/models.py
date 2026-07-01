from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float, JSON
from sqlalchemy.sql import func
from .database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(512), nullable=False)
    filepath = Column(String(1024), nullable=False, unique=True)
    file_hash = Column(String(64), index=True)
    file_size = Column(Integer)
    mime_type = Column(String(128))

    # Dates
    document_date = Column(DateTime, nullable=True)  # date extracted from content
    added_at = Column(DateTime, server_default=func.now())
    indexed_at = Column(DateTime, nullable=True)

    # Content
    ocr_text = Column(Text, nullable=True)
    vision_description = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    title = Column(String(150), nullable=True)  # short AI-generated display title, a few words

    # Classification
    document_type = Column(String(128), nullable=True)
    classification_confidence = Column(Float, nullable=True)
    classification_source = Column(String(16), nullable=True)  # 'auto' | 'manual'
    manually_classified = Column(Boolean, default=False)
    tags = Column(JSON, default=list)
    language = Column(String(32), nullable=True)

    # Extracted fields
    organization = Column(String(256), nullable=True)
    amount = Column(Float, nullable=True)
    amount_currency = Column(String(8), nullable=True)
    person_first_name = Column(String(128), nullable=True)
    person_last_name = Column(String(128), nullable=True)

    # Thumbnail
    thumbnail_path = Column(String(1024), nullable=True)

    # Step statuses: "pending" | "done" | "skipped" | "error"
    ocr_status = Column(String(16), default="pending")
    vision_status = Column(String(16), default="pending")
    analysis_status = Column(String(16), default="pending")

    ocr_error = Column(Text, nullable=True)
    vision_error = Column(Text, nullable=True)
    analysis_error = Column(Text, nullable=True)

    # API cost tracking (USD)
    api_cost_vision = Column(Float, default=0.0)
    api_cost_analysis = Column(Float, default=0.0)

    # Which model produced the stored ocr_text (set from the OCR Lab "save" action)
    ocr_model = Column(String(256), nullable=True)

    # How the document entered the library: "upload" (via UI) | "sync" (folder scan)
    source = Column(String(16), default="sync")

    is_deleted = Column(Boolean, default=False)


class WatchedFolder(Base):
    __tablename__ = "watched_folders"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String(1024), nullable=False, unique=True)
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime, server_default=func.now())
    last_synced_at = Column(DateTime, nullable=True)


class IndexingLog(Base):
    __tablename__ = "indexing_log"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, nullable=True)
    filename = Column(String(512), nullable=True)
    step = Column(String(32))          # "ocr" | "vision" | "analysis" | "sync"
    status = Column(String(16))        # "started" | "done" | "error" | "skipped"
    message = Column(Text, nullable=True)
    api_cost = Column(Float, default=0.0)
    level = Column(String(16), default="info")  # "trace"|"debug"|"info"|"warning"|"error"
    created_at = Column(DateTime, server_default=func.now())


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    provider_type = Column(String(32), nullable=False)  # "openai"|"gemini"|"deepseek"|"openrouter"|"mistral"
    api_key = Column(String(512), nullable=False)
    base_url = Column(String(512), nullable=True)    # custom OpenAI-compatible endpoint
    model = Column(String(128), nullable=True)       # override default model
    task_type = Column(String(16), default="both")   # "analysis" | "vision" | "both"
    sort_order = Column(Integer, default=0)          # lower = higher priority; tried first in failover chain
    key_name = Column(String(64), nullable=True)     # optional label for the API key (e.g. "Personal", "Work")
    enabled = Column(Boolean, default=True)
    added_at = Column(DateTime, server_default=func.now())
    # Cumulative usage stats
    total_tokens_in = Column(Integer, default=0)
    total_tokens_out = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    # Provider-specific fine-tuning options (e.g. image_policy for Mistral, temperature for chat)
    extra_params = Column(JSON, nullable=True)

    @property
    def supports_batch(self) -> bool:
        """True when this provider has a batch API (50% discount, async processing)."""
        return self.provider_type in {"gemini", "mistral"}


class AppSettings(Base):
    """Key-value store for application settings."""
    __tablename__ = "app_settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    status = Column(String(16), default="idle")  # idle|running|done|error|stopped
    config = Column(JSON, nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, default=0)
    result_summary = Column(JSON, nullable=True)


class TaskLog(Base):
    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, nullable=False, index=True)
    message = Column(Text, nullable=False)
    level = Column(String(16), default="info")  # info|warning|error
    created_at = Column(DateTime, server_default=func.now())


class AIUsage(Base):
    """One row per call to an AI provider / OCR engine — the paid (and free) usage ledger.

    Powers the super-user usage screen (stats, charts, pivot). Written by
    services/usage.py:record_usage() from every model call site.
    """
    __tablename__ = "ai_usage"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    # What the call was for: analysis|vision|ocr|qa|suggest_types|icon_suggest|
    #                        batch_analysis|batch_ocr|embedding|judge
    usage_type = Column(String(32), index=True)
    provider_type = Column(String(32), index=True)  # openai|gemini|mistral|deepseek|openrouter|local|worker
    provider_name = Column(String(64), nullable=True)  # AIProvider.name when known
    model = Column(String(128), nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Float, nullable=True)  # optional — null when price unknown
    document_id = Column(Integer, nullable=True)
    status = Column(String(16), default="ok")  # ok|error
    detail = Column(String(256), nullable=True)
