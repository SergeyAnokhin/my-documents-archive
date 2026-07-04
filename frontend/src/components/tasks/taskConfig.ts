import type { TaskType } from "../../types";

// ── Duration formatter ────────────────────────────────────────────────────────

export function formatDuration(ms: number, h: string, m: string, s: string): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(sec / 3600);
  const mins = Math.floor((sec % 3600) / 60);
  const secs = sec % 60;
  if (hours > 0) return `${hours}${h} ${mins}${m}`;
  if (mins > 0) return `${mins}${m} ${secs}${s}`;
  return `${secs}${s}`;
}

// ── Task type short labels ────────────────────────────────────────────────────

export const TASK_LABELS: Record<TaskType, string> = {
  index_documents:         "INDEX",
  index_unindexed:         "OCR",
  sync_library:            "SYNC",
  reclassify_unclassified: "CLASSIFY",
  reclassify_all:          "RECLASSIFY",
  recluster:               "RECLUSTER",
  batch_ocr_mistral:       "BATCH OCR",
  batch_ocr_gemini:        "BATCH AI",
  embed_missing:           "EMBED",
  fix_quality:             "FIX",
  cleanup_missing:         "CLEANUP",
  compress_images:         "COMPRESS",
};

export const PRIMARY_TYPES: TaskType[] = [
  "index_documents",
  "sync_library",
  "reclassify_unclassified",
  "reclassify_all",
  "recluster",
  "cleanup_missing",
  "compress_images",
];

export const LEGACY_TYPES: TaskType[] = [
  "index_unindexed",
  "batch_ocr_mistral",
  "batch_ocr_gemini",
  "embed_missing",
];

export const ALL_TYPES: TaskType[] = [...PRIMARY_TYPES, ...LEGACY_TYPES];

export const TYPES_WITH_LIMIT: TaskType[] = [
  "index_documents",
  "index_unindexed",
  "reclassify_unclassified",
  "reclassify_all",
  "batch_ocr_mistral",
  "batch_ocr_gemini",
];

// Batch tasks that pick an async provider + poll interval, mapped to the
// provider_type they require.
export const BATCH_PROVIDER_TYPE: Partial<Record<TaskType, string>> = {
  reclassify_unclassified: "gemini",
  reclassify_all:          "gemini",
  batch_ocr_mistral:       "mistral",
  batch_ocr_gemini:        "gemini",
};

// Default poll interval (seconds) per provider type.
// Edit here to change the pre-filled value in the create form per provider.
export const BATCH_POLL_DEFAULTS: Record<string, number> = {
  mistral: 30,
  gemini:  30,
};

// Tasks that have a scope selector (cumulative level filter).
export const TYPES_WITH_SCOPE: TaskType[] = ["batch_ocr_mistral", "batch_ocr_gemini"];

// Tasks that expose a "force full recompute" checkbox.
export const TYPES_WITH_FORCE: TaskType[] = ["embed_missing"];

// External documentation links for task types that have official provider docs.
export const TASK_DOC_URLS: Partial<Record<TaskType, string>> = {
  reclassify_unclassified: "https://ai.google.dev/gemini-api/docs/batch-mode",
  reclassify_all:          "https://ai.google.dev/gemini-api/docs/batch-mode",
  batch_ocr_mistral:       "https://docs.mistral.ai/capabilities/batch/",
  batch_ocr_gemini:        "https://ai.google.dev/gemini-api/docs/batch-mode",
};

// Links to provider batch consoles — shown while the task is running.
export const BATCH_CONSOLE_URLS: Partial<Record<TaskType, string>> = {
  batch_ocr_mistral: "https://console.mistral.ai/build/batches",
};

// Batch task types that have a remote job and can be monitored / resumed
export const BATCH_TASK_TYPES: TaskType[] = [
  "index_documents",
  "reclassify_unclassified", "reclassify_all",
  "batch_ocr_mistral", "batch_ocr_gemini",
];
