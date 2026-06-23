import { api } from "./client";
import type {
  Document,
  DocumentList,
  SearchResponse,
  IndexingStats,
  WatchedFolder,
  AIProvider,
  ArenaRating,
  ProviderModel,
  LogEntry,
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
export const fetchProviderModels = (body: {
  provider_type: string;
  api_key: string;
  base_url?: string;
}) => api.post<ProviderModel[]>("/admin/providers/models", body);

export const getArenaRatings = () =>
  api.get<Record<string, ArenaRating>>("/admin/arena-ratings");

export const refreshArenaRatings = () =>
  api.post<{ updated: number; ratings: Record<string, ArenaRating> }>("/admin/arena-ratings/refresh");

export const reclassifyAll = () => api.post("/admin/reclassify-all");

export const getAppSettings = () => api.get<Record<string, string>>("/admin/settings");
export const updateAppSettings = (body: Record<string, string>) =>
  api.patch<Record<string, string>>("/admin/settings", body);

export const getLog = (limit = 100) => api.get<LogEntry[]>(`/admin/log?limit=${limit}`);

// ── Indexing (per-document) ───────────────────────────────────────────────────

export const reclassifyDocument = (id: number) =>
  api.post(`/indexing/reclassify/${id}`);

export const reindexDocument = (id: number) =>
  api.post(`/indexing/document/${id}`);
