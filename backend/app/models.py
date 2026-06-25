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

    # Classification
    document_type = Column(String(128), nullable=True)
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
    created_at = Column(DateTime, server_default=func.now())


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False)
    provider_type = Column(String(32), nullable=False)  # "anthropic"|"openai"|"gemini"|"deepseek"|"openrouter"
    api_key = Column(String(512), nullable=False)
    base_url = Column(String(512), nullable=True)    # custom OpenAI-compatible endpoint
    model = Column(String(128), nullable=True)       # override default model (e.g. "claude-opus-4-8")
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


class AppSettings(Base):
    """Key-value store for application settings."""
    __tablename__ = "app_settings"

    key = Column(String(128), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
