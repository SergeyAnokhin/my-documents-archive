export interface Document {
  id: number;
  filename: string;
  filepath: string;
  file_size?: number;
  mime_type?: string;
  document_date?: string;
  added_at?: string;
  indexed_at?: string;
  ocr_text?: string;
  vision_description?: string;
  summary?: string;
  document_type?: string;
  classification_confidence?: number;
  classification_source?: "auto" | "manual";
  manually_classified?: boolean;
  tags?: string[];
  language?: string;
  organization?: string;
  amount?: number;
  amount_currency?: string;
  person_first_name?: string;
  person_last_name?: string;
  thumbnail_path?: string;
  updated_at?: string;
  ocr_status: "pending" | "done" | "error" | "skipped";
  vision_status: "pending" | "done" | "error" | "skipped";
  analysis_status: "pending" | "done" | "error" | "skipped";
  ocr_error?: string;
  vision_error?: string;
  analysis_error?: string;
  api_cost_vision?: number;
  api_cost_analysis?: number;
  ocr_model?: string;
}

export interface SearchResult {
  document: Document;
  score: number;
  highlight?: string;
}

export interface SearchResponse {
  items: SearchResult[];
  total: number;
  page: number;
  page_size: number;
  mode: string;
}

export interface DocumentList {
  items: Document[];
  total: number;
  page: number;
  page_size: number;
}

export interface TypeSuggestion {
  type: string;
  confidence: number;
  reason: string;
}

export interface IndexingStats {
  total: number;
  indexed: number;
  analyzed: number;
  embedded: number;
  pending: number;
  errors: number;
  unclassified: number;
  api_cost_total: number;
  library_path?: string;
}

export interface WatchedFolder {
  id: number;
  path: string;
  enabled: boolean;
  added_at?: string;
  last_synced_at?: string;
}

export interface AIProvider {
  id: number;
  name: string;
  provider_type: string;
  task_type: "analysis" | "vision" | "both" | "premium";
  sort_order: number;
  key_name?: string;
  base_url?: string;
  model?: string;
  enabled: boolean;
  added_at?: string;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  extra_params?: Record<string, unknown>;
}

export interface ProviderModel {
  id: string;
  name: string;
  supports_vision: boolean;
  context_length?: number;
  price_in?: number;  // USD per 1M input tokens
  price_out?: number; // USD per 1M output tokens
  is_free: boolean;
}

export interface ArenaRating {
  text: number;    // 0-5 stars
  vision: number;  // 0-5 stars
  elo?: number;    // actual Elo score from Chatbot Arena (e.g. 1320)
}

export interface LogEntry {
  id: number;
  document_id?: number;
  filename?: string;
  step: string;
  status: string;
  message?: string;
  api_cost: number;
  level: string;
  created_at?: string;
}

// ── Lab extracted fields ───────────────────────────────────────────────────

export interface ExtractedFields {
  document_type?: string;
  document_date?: string;       // YYYY-MM-DD
  person_first_name?: string;
  person_last_name?: string;
  organization?: string;
  amount?: number;
  amount_currency?: string;
  language?: string;
}

// ── Lab (OCR calibration) ───────────────────────────────────────────────────

export interface LabMethods {
  ocr_methods: string[];
  worker_available: boolean;
  worker_reachable: boolean;
  worker_url: string;
}

export interface LabWorkerStatus {
  url: string;
  reachable: boolean;
  engines: string[];
  worker_available: boolean;
}

/** A single transcription result shown as a card in the lab. */
export interface LabResult {
  id: string;            // client-side unique key
  kind: "ocr" | "vision";
  label: string;         // method or provider name
  providerId?: number;   // for vision results
  providerModel?: string;// actual model id (e.g. "claude-haiku-4-5-20251001")
  text: string;
  ms: number;
  cost?: number;
  tokens_in?: number;
  tokens_out?: number;
  fields?: ExtractedFields; // extracted metadata (vision results only)
}

export interface LabRanking {
  label: string;
  score: number;
  comment: string;
}

export interface LabJudgeResult {
  rankings: LabRanking[];
  best: string;
  summary: string;
  corrected?: string;
  fields?: ExtractedFields; // extracted by the judge from its own analysis
  cost: number;
  ms: number;
  tokens_in?: number;
  tokens_out?: number;
}

export interface LabImageInfo {
  width: number;
  height: number;
  file_size: number;
  format: string;
  can_adjust_quality: boolean;
}

export interface LabTransformParams {
  crop?: { x: number; y: number; w: number; h: number };
  scale?: number;
  quality?: number;
}

export interface LabPreviewResult {
  image_b64: string;
  width: number;
  height: number;
  file_size: number;
}

export interface LabApplyResult {
  ok: boolean;
  doc_id: number;
  width: number;
  height: number;
  file_size: number;
}

export type ViewMode = "list" | "grid";
export type GridSize = "sm" | "md" | "lg" | "xl";
export type SearchMode = "search" | "ask";

// ── Tasks ─────────────────────────────────────────────────────────────────────

export type TaskStatus = "idle" | "running" | "done" | "error" | "stopped";
export type TaskType =
  | "index_unindexed"
  | "sync_library"
  | "reclassify_unclassified"
  | "reclassify_all"
  | "recluster"
  | "batch_ocr_mistral"
  | "batch_ocr_gemini"
  | "batch_analysis_gemini"
  | "cleanup_missing";

export interface Task {
  id: number;
  task_type: TaskType;
  title: string;
  status: TaskStatus;
  config?: Record<string, unknown>;
  sort_order: number;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  progress_current: number;
  progress_total: number;
  result_summary?: Record<string, unknown>;
}

export interface TaskLog {
  id: number;
  task_id: number;
  message: string;
  level: "info" | "warning" | "error";
  created_at?: string;
}

export interface AIAnswerResponse {
  answer: string;
  sources: Document[];
  cost: number;
  no_provider?: boolean;
  tokens_in?: number;
  tokens_out?: number;
  model_name?: string | null;
  docs_sent?: number;
  depth?: number;
}

export interface BackupInfo {
  name: string;
  size: number;
  modified: string;
}

// ── AI provider config export/import ────────────────────────────────────────────

export interface ProviderFull {
  name: string;
  provider_type: string;
  api_key: string;
  base_url?: string | null;
  model?: string | null;
  task_type: string;
  sort_order: number;
  key_name?: string | null;
  enabled: boolean;
  extra_params?: unknown;
}

export interface ProvidersExport {
  version: number;
  providers: ProviderFull[];
}

export interface ProvidersImport {
  providers: ProviderFull[];
  replace: boolean;
}

// ── AI usage ledger ─────────────────────────────────────────────────────────────

export interface UsageRow {
  id: number;
  created_at: string | null;
  usage_type: string;
  provider_type: string;
  provider_name?: string | null;
  model?: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_usd?: number | null;
  document_id?: number | null;
  status: string;
  detail?: string | null;
}

export interface UsageBreakdown {
  key: string;
  count: number;
  cost: number;
  tokens: number;
}

export interface UsageSummary {
  total_calls: number;
  total_cost: number;
  total_tokens_in: number;
  total_tokens_out: number;
  by_type: UsageBreakdown[];
  by_provider: UsageBreakdown[];
  by_model: UsageBreakdown[];
  by_day: UsageBreakdown[];
}

export interface UsagePivot {
  row: string;
  col: string;
  metric: string;
  row_keys: string[];
  col_keys: string[];
  matrix: number[][];
  row_totals: number[];
  col_totals: number[];
  grand_total: number;
}
