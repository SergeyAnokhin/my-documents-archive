from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Any


class DocumentBase(BaseModel):
    filename: str
    filepath: str


class DocumentOut(BaseModel):
    id: int
    filename: str
    filepath: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    document_date: Optional[datetime] = None
    added_at: Optional[datetime] = None
    indexed_at: Optional[datetime] = None
    ocr_text: Optional[str] = None
    vision_description: Optional[str] = None
    summary: Optional[str] = None
    document_type: Optional[str] = None
    tags: Optional[List[str]] = []
    language: Optional[str] = None
    organization: Optional[str] = None
    amount: Optional[float] = None
    amount_currency: Optional[str] = None
    person_first_name: Optional[str] = None
    person_last_name: Optional[str] = None
    thumbnail_path: Optional[str] = None
    ocr_status: str = "pending"
    vision_status: str = "pending"
    analysis_status: str = "pending"
    ocr_error: Optional[str] = None
    vision_error: Optional[str] = None
    analysis_error: Optional[str] = None
    api_cost_vision: float = 0.0
    api_cost_analysis: float = 0.0

    model_config = {"from_attributes": True}


class DocumentList(BaseModel):
    items: List[DocumentOut]
    total: int
    page: int
    page_size: int


class SearchQuery(BaseModel):
    query: str = ""
    mode: str = "fulltext"       # "fulltext" | "semantic" | "hybrid"
    year: Optional[int] = None
    month: Optional[int] = None
    document_type: Optional[str] = None
    tag: Optional[str] = None
    language: Optional[str] = None
    ocr_status: Optional[str] = None
    page: int = 1
    page_size: int = 24


class SearchResult(BaseModel):
    document: DocumentOut
    score: float = 1.0
    highlight: Optional[str] = None


class SearchResponse(BaseModel):
    items: List[SearchResult]
    total: int
    page: int
    page_size: int
    mode: str


class UploadResponse(BaseModel):
    document_id: int
    filename: str
    message: str


class SyncResponse(BaseModel):
    found: int
    new_files: int
    message: str


class WatchedFolderOut(BaseModel):
    id: int
    path: str
    enabled: bool
    added_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WatchedFolderCreate(BaseModel):
    path: str


class AIProviderOut(BaseModel):
    id: int
    name: str
    provider_type: str
    task_type: str = "both"
    sort_order: int = 0
    key_name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    enabled: bool
    added_at: Optional[datetime] = None
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    extra_params: Optional[Any] = None

    model_config = {"from_attributes": True}


class AIProviderCreate(BaseModel):
    name: str = ""
    provider_type: str
    api_key: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    task_type: str = "both"
    sort_order: int = 0
    key_name: Optional[str] = None
    extra_params: Optional[Any] = None


class ProviderModelInfo(BaseModel):
    id: str
    name: str
    supports_vision: bool = False
    context_length: Optional[int] = None
    price_in: Optional[float] = None   # USD per 1M input tokens
    price_out: Optional[float] = None  # USD per 1M output tokens
    is_free: bool = False


class FetchModelsRequest(BaseModel):
    provider_type: str
    api_key: str
    base_url: Optional[str] = None


class IndexingStats(BaseModel):
    total: int
    indexed: int
    analyzed: int
    embedded: int
    pending: int
    errors: int
    api_cost_total: float


class LogEntry(BaseModel):
    id: int
    document_id: Optional[int] = None
    filename: Optional[str] = None
    step: str
    status: str
    message: Optional[str] = None
    api_cost: float
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── Lab (OCR calibration screen) ────────────────────────────────────────────────

class LabMethods(BaseModel):
    ocr_methods: List[str]          # local engines available, e.g. ["tesseract", "easyocr"]
    worker_available: bool          # reachable AND easyocr installed
    worker_reachable: bool = False  # service responds to /health (even without easyocr)
    worker_url: str = ""            # url that was probed


class LabWorkerStatus(BaseModel):
    url: str
    reachable: bool
    engines: List[str]
    worker_available: bool


class LabOcrRequest(BaseModel):
    doc_id: int
    method: str                     # "tesseract" | "easyocr"


class LabOcrResult(BaseModel):
    method: str
    text: str
    ms: int


class LabVisionRequest(BaseModel):
    doc_id: int
    provider_id: int


class LabVisionResult(BaseModel):
    provider_id: int
    name: str
    text: str
    cost: float
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0


class LabCandidate(BaseModel):
    label: str
    text: str


class LabJudgeRequest(BaseModel):
    doc_id: int
    provider_id: int
    use_image: bool = True
    language: str = "en"
    candidates: List[LabCandidate]


class LabRanking(BaseModel):
    label: str
    score: int = 0
    comment: str = ""


class LabJudgeResult(BaseModel):
    rankings: List[LabRanking] = []
    best: str = ""
    summary: str = ""
    corrected: str = ""
    cost: float = 0.0
    ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
