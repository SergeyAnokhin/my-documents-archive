"""SQLAlchemy models for DocIntel."""

import enum
import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, Enum, Integer, Float, JSON
)
from sqlalchemy.orm import relationship

from backend.database import Base


def generate_uuid():
    return str(uuid.uuid4())


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class IndexingStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    skipped = "skipped"
    error = "error"


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    original_filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False, unique=True)
    file_hash = Column(String, nullable=False)
    file_size = Column(Integer, default=0)
    mime_type = Column(String, default="application/octet-stream")

    # Document metadata
    doc_date = Column(DateTime, nullable=True)
    doc_language = Column(String, default="")
    doc_type = Column(String, default="")

    # Indexing data
    ocr_text = Column(Text, default="")
    vision_description = Column(Text, default="")
    summary = Column(Text, default="")
    tags = Column(JSON, default=list)

    # Indexing statuses
    ocr_status = Column(
        Enum(IndexingStatus),
        default=IndexingStatus.pending
    )
    vision_status = Column(
        Enum(IndexingStatus),
        default=IndexingStatus.pending
    )
    analysis_status = Column(
        Enum(IndexingStatus),
        default=IndexingStatus.pending
    )

    # Timing
    created_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Thumbnail
    thumbnail_path = Column(String, default="")

    # Pages info (for PDFs)
    page_count = Column(Integer, default=1)

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "doc_date": self.doc_date.isoformat() if self.doc_date else None,
            "doc_language": self.doc_language,
            "doc_type": self.doc_type,
            "ocr_text": self.ocr_text,
            "vision_description": self.vision_description,
            "summary": self.summary,
            "tags": self.tags or [],
            "ocr_status": self.ocr_status.value if self.ocr_status else None,
            "vision_status": self.vision_status.value if self.vision_status else None,
            "analysis_status": self.analysis_status.value if self.analysis_status else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "thumbnail_path": self.thumbnail_path,
            "page_count": self.page_count,
        }
