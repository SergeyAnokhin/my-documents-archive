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
  Task,
  TaskLog,
  BackupInfo,
  ProvidersExport,
  ProvidersImport,
  UsageSummary,
  UsagePivot,
  UsageRow,
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

export const clearDocumentDate = (id: number) =>
  api.patch<Document>(`/documents/${id}/date`, { date: null });

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

export const askDocuments = (
  query: string,
  language: string,
  year?: string | null,
  filterLanguage?: string | null,
  depth?: number,
  debug?: boolean,
) => {
  const params: Record<string, string> = { query, language };
  if (year) params.year = year;
  if (filterLanguage) params.filter_language = filterLanguage;
  if (depth) params.depth = String(depth);
  if (debug) params.debug = "true";
  return api.get<AIAnswerResponse>(`/search/ask?${new URLSearchParams(params).toString()}`);
};

// ── Admin ─────────────────────────────────────────────────────────────────────

export const getStats = () => api.get<IndexingStats>("/admin/stats");

export const syncLibrary = () =>
  api.post<{ found: number; new_files: number; removed: number; message: string }>("/admin/sync");

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

export const exportProviders = () =>
  api.get<ProvidersExport>("/admin/providers/export");
export const importProviders = (body: ProvidersImport) =>
  api.post<{ imported: number; replaced: boolean }>("/admin/providers/import", body);

// ── AI usage ledger (super-user screen) ─────────────────────────────────────────

export const getUsageSummary = (params: { since?: string; until?: string } = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v).map(([k, v]) => [k, String(v)])
  ).toString();
  return api.get<UsageSummary>(`/admin/usage/summary${qs ? `?${qs}` : ""}`);
};

export const getUsagePivot = (params: {
  row: string; col: string; metric: string; since?: string; until?: string;
}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v).map(([k, v]) => [k, String(v)])
  ).toString();
  return api.get<UsagePivot>(`/admin/usage/pivot?${qs}`);
};

export const listUsage = (params: {
  usage_type?: string; provider_type?: string; limit?: number;
} = {}) => {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)])
  ).toString();
  return api.get<UsageRow[]>(`/admin/usage${qs ? `?${qs}` : ""}`);
};

export const clearUsage = () => api.delete<{ deleted: number }>("/admin/usage");

export const getArenaRatings = () =>
  api.get<Record<string, ArenaRating>>("/admin/arena-ratings");

export const refreshArenaRatings = () =>
  api.post<{ updated: number; ratings: Record<string, ArenaRating> }>("/admin/arena-ratings/refresh");

export const reclassifyAll = () => api.post("/admin/reclassify-all");
export const reclassifyUnclassified = () => api.post("/admin/reclassify-unclassified");
export const recluster = () => api.post("/admin/recluster");

export const getAppSettings = () => api.get<Record<string, string>>("/admin/settings");
export const updateAppSettings = (body: Record<string, string>) =>
  api.patch<Record<string, string>>("/admin/settings", body);

export const getLog = (limit = 100, minLevel = "info") =>
  api.get<LogEntry[]>(`/admin/log?limit=${limit}&min_level=${minLevel}`);

export const getCustomTypeIcons = () =>
  api.get<Record<string, string>>("/admin/type-icons");

export const updateTypeIcons = () =>
  api.post<{ updated: number; icons: Record<string, string> }>("/admin/update-type-icons");

export const listBackups = () => api.get<BackupInfo[]>("/admin/backups");
export const restoreBackup = (name: string) =>
  api.post<{ restored: string }>("/admin/backups/restore", { name });

// ── Indexing (per-document) ───────────────────────────────────────────────────

export const reclassifyDocument = (id: number) =>
  api.post(`/indexing/reclassify/${id}`);

export const reindexDocument = (id: number) =>
  api.post(`/indexing/document/${id}`);

// ── Lab (OCR calibration) ─────────────────────────────────────────────────────

export const getLabMethods = () => api.get<LabMethods>("/lab/methods");
export const getWorkerStatus = () => api.get<LabWorkerStatus>("/lab/worker-status");

export const runLabOcr = (doc_id: number, method: string) =>
  api.post<{ method: string; text: string; ms: number; fields: import("../types").ExtractedFields | null }>("/lab/ocr", { doc_id, method });

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

// ── Tasks ─────────────────────────────────────────────────────────────────────

export const listTasks = () => api.get<Task[]>("/tasks");

export const createTask = (body: {
  task_type: string;
  title: string;
  config?: Record<string, unknown>;
  sort_order?: number;
}) => api.post<Task>("/tasks", body);

export const updateTask = (id: number, body: {
  title?: string;
  config?: Record<string, unknown>;
  sort_order?: number;
}) => api.patch<Task>(`/tasks/${id}`, body);

export const deleteTask = (id: number) => api.delete(`/tasks/${id}`);

export const runTask = (id: number) => api.post<{ message: string }>(`/tasks/${id}/run`);

export const stopTask = (id: number) => api.post<{ message: string }>(`/tasks/${id}/stop`);

export const stopAllTasks = () => api.post<{ message: string }>("/tasks/stop-all");

export const getTaskLogs = (id: number) => api.get<TaskLog[]>(`/tasks/${id}/logs`);

export const getTaskCandidates = () =>
  api.get<Record<string, number | null>>("/tasks/candidates");

export const getScopeCount = (taskType: string, scope: number) =>
  api.get<{ count: number }>(`/tasks/candidates/scope?task_type=${taskType}&scope=${scope}`);

export const getCompressCandidates = (threshold: number) =>
  api.get<{ count: number; total_images: number }>(`/tasks/candidates/compress?threshold=${threshold}`);

export const resumeBatchTask = (id: number) =>
  api.post<{ message: string }>(`/tasks/${id}/resume-batch`);

export const getBatchResultUrl = (id: number) =>
  `/api/tasks/${id}/batch-result`;
