import json as _json
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from pathlib import Path
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
    classification_confidence: Optional[float] = None
    classification_source: Optional[str] = None
    manually_classified: bool = False
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
    ocr_model: Optional[str] = None
    updated_at: Optional[datetime] = None
    relative_path: Optional[str] = None

    @field_validator("tags", mode="before")
    @classmethod
    def parse_tags(cls, v):
        if isinstance(v, str):
            try:
                return _json.loads(v)
            except Exception:
                return []
        return v or []

    @model_validator(mode="after")
    def compute_relative_path(self) -> "DocumentOut":
        if self.filepath and self.relative_path is None:
            try:
                from .config import settings
                lib = Path(settings.library_path).resolve()
                self.relative_path = Path(self.filepath).relative_to(lib).as_posix()
            except (ValueError, Exception):
                pass
        return self

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
    found: int       # new files discovered on disk
    new_files: int   # documents added to the library
    removed: int = 0 # documents removed because the file is gone from disk
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
    supports_batch: bool = False

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


class AIProviderFull(BaseModel):
    """Full provider snapshot for export/import — includes the API key."""
    name: str
    provider_type: str
    api_key: str
    base_url: Optional[str] = None
    model: Optional[str] = None
    task_type: str = "both"
    sort_order: int = 0
    key_name: Optional[str] = None
    enabled: bool = True
    extra_params: Optional[Any] = None

    model_config = {"from_attributes": True}


class ProvidersExport(BaseModel):
    version: int = 1
    providers: List[AIProviderFull]


class ProvidersImport(BaseModel):
    providers: List[AIProviderFull]
    replace: bool = False  # True = wipe existing providers first; False = append


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


class TypeSuggestion(BaseModel):
    type: str
    confidence: float
    reason: str


class TypeSuggestionsResponse(BaseModel):
    suggestions: List[TypeSuggestion]
    existing_types: List[str]


class PatchTypeRequest(BaseModel):
    document_type: str


class PatchDateRequest(BaseModel):
    date: Optional[datetime] = None


class IndexingStats(BaseModel):
    total: int
    indexed: int
    analyzed: int
    embedded: int
    pending: int
    errors: int
    unclassified: int = 0
    api_cost_total: float
    library_path: str = ""


class LogEntry(BaseModel):
    id: int
    document_id: Optional[int] = None
    filename: Optional[str] = None
    step: str
    status: str
    message: Optional[str] = None
    api_cost: float
    level: str = "info"
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
    fields: Optional[Any] = None  # auto-analyzed metadata extracted from OCR text


class LabVisionRequest(BaseModel):
    doc_id: int
    provider_id: int


class LabVisionResult(BaseModel):
    provider_id: int
    name: str
    model_name: Optional[str] = None
    text: str
    cost: float
    ms: int
    tokens_in: int = 0
    tokens_out: int = 0
    fields: Optional[Any] = None  # ExtractedFields dict from combined vision+analysis prompt


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
    fields: Optional[Any] = None  # ExtractedFields dict from judge's own analysis
    cost: float = 0.0
    ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class LabSaveRequest(BaseModel):
    doc_id: int
    text: str
    fields: Optional[Any] = None  # ExtractedFields dict
    model_name: str               # human-readable "Provider (model)" for attribution


class LabSaveResult(BaseModel):
    ok: bool
    doc_id: int


class LabImageInfo(BaseModel):
    width: int
    height: int
    file_size: int
    format: str               # e.g. "JPEG", "PNG", "PDF"
    can_adjust_quality: bool  # True for JPEG/PNG/WEBP


class LabTransformRequest(BaseModel):
    crop: Optional[dict] = None     # {x, y, w, h} in original image pixels
    scale: Optional[float] = None   # 0.1 … 1.0 (downscale factor)
    quality: Optional[int] = None   # 10 … 95
    rotation: Optional[int] = None  # 0, 90, 180, 270 — clockwise degrees


class LabPreviewResult(BaseModel):
    image_b64: str  # base64 JPEG preview
    width: int
    height: int
    file_size: int  # bytes of the preview JPEG


class LabApplyResult(BaseModel):
    ok: bool
    doc_id: int
    width: int
    height: int
    file_size: int  # updated file size on disk


class AskDebugDoc(BaseModel):
    """One row of the /ask retrieval trace (debug mode only)."""
    rank: int                              # position in the semantic ranking (1 = closest)
    doc_id: int
    filename: str
    document_type: Optional[str] = None
    similarity: Optional[float] = None     # cosine similarity 1-distance; None = no embedding
    distance: Optional[float] = None       # raw cosine distance from ChromaDB
    in_fulltext: bool = False              # also matched the keyword (fulltext) branch
    retrieved: bool = False                # survived the n_retrieve cut
    sent: bool = False                     # actually sent to the LLM (in context)


class AskDebug(BaseModel):
    """Full per-request retrieval trace for the advanced-mode debug modal."""
    query: str
    query_variants: List[str]
    depth: int
    n_retrieve: int
    n_send: int
    ocr_chars: int
    embedded_count: int                    # docs with embeddings in ChromaDB
    total_docs: int                        # non-deleted docs in scope (after year/lang filters)
    fulltext_count: int
    fulltext_ids: List[int]
    semantic: List[AskDebugDoc]            # every embedded doc scored against the query
    retrieved_ids: List[int]
    sent_ids: List[int]
    fallback_newest: bool = False          # pool was empty → answered from newest docs
    context_chars: int = 0
    system_prompt: str = ""
    user_prompt: str = ""                  # full context block sent to the LLM
    semantic_ms: float = 0.0
    fulltext_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0
    provider_name: Optional[str] = None
    model_name: Optional[str] = None


class AIAnswerResponse(BaseModel):
    answer: str
    sources: List[DocumentOut]
    source_similarities: List[Optional[float]] = []  # cosine similarity (0-1) per source, None if no embedding
    cost: float = 0.0
    no_provider: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    model_name: Optional[str] = None
    docs_sent: int = 0
    depth: int = 2
    debug: Optional[AskDebug] = None


# ── Tasks ────────────────────────────────────────────────────────────────────

class TaskOut(BaseModel):
    id: int
    task_type: str
    title: str
    status: str
    config: Optional[Any] = None
    sort_order: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    progress_current: int = 0
    progress_total: int = 0
    result_summary: Optional[Any] = None

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    task_type: str
    title: str
    config: Optional[Any] = None
    sort_order: int = 0


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    config: Optional[Any] = None
    sort_order: Optional[int] = None


class TaskLogOut(BaseModel):
    id: int
    task_id: int
    message: str
    level: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BackupInfo(BaseModel):
    name: str
    size: int
    modified: str


class RestoreRequest(BaseModel):
    name: str
