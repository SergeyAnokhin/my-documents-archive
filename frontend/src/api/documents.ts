import { api } from "./client";
import type {
  Document,
  DocumentList,
  SearchResponse,
  AIAnswerResponse,
  IndexingStats,
  TypeSuggestion,
  WatchedFolder,
  AIProvider,
  ArenaRating,
  ProviderModel,
  LogEntry,
  LabMethods,
  LabWorkerStatus,
  LabJudgeResult,
  ExtractedFields,
  LabImageInfo,
  LabTransformParams,
  LabPreviewResult,
  LabApplyResult,
} from "../types";

// ── Documents ─────────────────────────────────────────────────────────────────

export const listDocuments = (params: Record<string, unknown> = {}) => {
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return api.get<DocumentList>(`/documents?${qs}`);
};

export const getDocument = (id: number) => api.get<Document>(`/documents/${id}`);

export const deleteDocument = (id: number) => api.delete(`/documents/${id}`);

export const updateTags = (id: number, tags: string[]) =>
  api.patch<Document>(`/documents/${id}/tags`, tags);

export const patchDocumentType = (id: number, document_type: string) =>
  api.patch<Document>(`/documents/${id}/type`, { document_type });

export const suggestDocumentTypes = (id: number) =>
  api.post<{ suggestions: TypeSuggestion[]; existing_types: string[] }>(`/indexing/suggest-type/${id}`);

// ── Upload ────────────────────────────────────────────────────────────────────

export const uploadDocument = (file: File) =>
  api.upload<{ document_id: number; filename: string; message: string }>("/upload", file);

// ── Search ────────────────────────────────────────────────────────────────────

export const searchDocuments = (params: Record<string, unknown> = {}) => {
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params)
        .filter(([, v]) => v !== undefined && v !== null && v !== "")
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return api.get<SearchResponse>(`/search?${qs}`);
};

export const askDocuments = (query: string, language: string) =>
  api.get<AIAnswerResponse>(
    `/search/ask?${new URLSearchParams({ query, language }).toString()}`
  );

// ── Admin ─────────────────────────────────────────────────────────────────────

export const getStats = () => api.get<IndexingStats>("/admin/stats");

export const syncLibrary = () =>
  api.post<{ found: number; new_files: number; message: string }>("/admin/sync");

export const listFolders = () => api.get<WatchedFolder[]>("/admin/folders");
export const addFolder = (path: string) => api.post<WatchedFolder>("/admin/folders", { path });
export const removeFolder = (id: number) => api.delete(`/admin/folders/${id}`);
export const toggleFolder = (id: number) => api.patch<WatchedFolder>(`/admin/folders/${id}/toggle`);

export const listProviders = () => api.get<AIProvider[]>("/admin/providers");
export const addProvider = (body: {
  name?: string;
  provider_type: string;
  api_key: string;
  base_url?: string;
  model?: string;
  task_type?: string;
  sort_order?: number;
  key_name?: string;
}) => api.post<AIProvider>("/admin/providers", body);
export const toggleProvider = (id: number) => api.patch<AIProvider>(`/admin/providers/${id}/toggle`);
export const removeProvider = (id: number) => api.delete(`/admin/providers/${id}`);
export const updateProviderOrder = (id: number, sort_order: number) =>
  api.patch<AIProvider>(`/admin/providers/${id}/order`, { sort_order });
export const updateProviderModel = (id: number, model: string) =>
  api.patch<AIProvider>(`/admin/providers/${id}/model`, { model });
export const updateProviderSettings = (id: number, params: Record<string, unknown>) =>
  api.patch<AIProvider>(`/admin/providers/${id}/settings`, params);
export const fetchProviderModels = (body: {
  provider_type: string;
  api_key: string;
  base_url?: string;
}) => api.post<ProviderModel[]>("/admin/providers/models", body);
export const fetchProviderModelsById = (id: number) =>
  api.post<ProviderModel[]>(`/admin/providers/${id}/models`);

export const getArenaRatings = () =>
  api.get<Record<string, ArenaRating>>("/admin/arena-ratings");

export const refreshArenaRatings = () =>
  api.post<{ updated: number; ratings: Record<string, ArenaRating> }>("/admin/arena-ratings/refresh");

export const reclassifyAll = () => api.post("/admin/reclassify-all");
export const reclassifyUnclassified = () => api.post("/admin/reclassify-unclassified");

export const getAppSettings = () => api.get<Record<string, string>>("/admin/settings");
export const updateAppSettings = (body: Record<string, string>) =>
  api.patch<Record<string, string>>("/admin/settings", body);

export const getLog = (limit = 100) => api.get<LogEntry[]>(`/admin/log?limit=${limit}`);

// ── Indexing (per-document) ───────────────────────────────────────────────────

export const reclassifyDocument = (id: number) =>
  api.post(`/indexing/reclassify/${id}`);

export const reindexDocument = (id: number) =>
  api.post(`/indexing/document/${id}`);

// ── Lab (OCR calibration) ─────────────────────────────────────────────────────

export const getLabMethods = () => api.get<LabMethods>("/lab/methods");
export const getWorkerStatus = () => api.get<LabWorkerStatus>("/lab/worker-status");

export const runLabOcr = (doc_id: number, method: string) =>
  api.post<{ method: string; text: string; ms: number }>("/lab/ocr", { doc_id, method });

export const runLabVision = (doc_id: number, provider_id: number) =>
  api.post<{
    provider_id: number; name: string; model_name: string | null;
    text: string; cost: number; ms: number; tokens_in: number; tokens_out: number;
    fields: import("../types").ExtractedFields | null;
  }>("/lab/vision", { doc_id, provider_id });

export const runLabJudge = (body: {
  doc_id: number;
  provider_id: number;
  use_image: boolean;
  language: string;
  candidates: { label: string; text: string }[];
}) => api.post<LabJudgeResult>("/lab/judge", body);

export const saveLabResult = (body: {
  doc_id: number;
  text: string;
  fields?: ExtractedFields;
  model_name: string;
}) => api.post<{ ok: boolean; doc_id: number }>("/lab/save", body);

export const getLabImageInfo = (docId: number) =>
  api.get<LabImageInfo>(`/lab/${docId}/image-info`);

export const previewLabTransform = (docId: number, params: LabTransformParams) =>
  api.post<LabPreviewResult>(`/lab/${docId}/preview-transform`, params);

export const applyLabTransform = (docId: number, params: LabTransformParams) =>
  api.post<LabApplyResult>(`/lab/${docId}/apply-transform`, params);
