// Shared formatters and constants for the OCR Lab page.

export function formatMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const min = Math.floor(ms / 60000);
  const sec = Math.round((ms % 60000) / 1000);
  return `${min} min ${sec} s`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Provider types that can run as vision/image judges. */
export const VISION_CAPABLE = ["anthropic", "openai", "gemini", "openrouter", "mistral"];

export function uid() {
  return Math.random().toString(36).slice(2);
}
