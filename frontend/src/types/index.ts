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
  tags?: string[];
  language?: string;
  organization?: string;
  amount?: number;
  amount_currency?: string;
  thumbnail_path?: string;
  ocr_status: "pending" | "done" | "error" | "skipped";
  vision_status: "pending" | "done" | "error" | "skipped";
  analysis_status: "pending" | "done" | "error" | "skipped";
  ocr_error?: string;
  vision_error?: string;
  analysis_error?: string;
  api_cost_vision?: number;
  api_cost_analysis?: number;
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

export interface IndexingStats {
  total: number;
  indexed: number;
  analyzed: number;
  embedded: number;
  pending: number;
  errors: number;
  api_cost_total: number;
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
  base_url?: string;
  model?: string;
  enabled: boolean;
  added_at?: string;
}

export interface LogEntry {
  id: number;
  document_id?: number;
  filename?: string;
  step: string;
  status: string;
  message?: string;
  api_cost: number;
  created_at?: string;
}

export type ViewMode = "list" | "grid";
export type GridSize = "sm" | "md" | "lg" | "xl";
export type SearchMode = "fulltext" | "semantic" | "hybrid";
