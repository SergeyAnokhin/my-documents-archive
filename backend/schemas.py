"""Pydantic schemas for API request/response validation."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: str
    filename: str
    original_filename: str
    file_path: str
    file_size: int
    mime_type: str
    doc_date: Optional[str] = None
    doc_language: str = ""
    doc_type: str = ""
    ocr_text: str = ""
    vision_description: str = ""
    summary: str = ""
    tags: list[str] = []
    ocr_status: Optional[str] = None
    vision_status: Optional[str] = None
    analysis_status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    thumbnail_path: str = ""
    page_count: int = 1

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    documents: list[DocumentOut]
    total: int


class StatsOut(BaseModel):
    total: int
    indexed: int
    pending: int
    errors: int
