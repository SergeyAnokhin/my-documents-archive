// Shared constants, formatters, and rating lookup for the AI providers tab.
import type { ArenaRating } from "../../../../types";

// ── Constants ─────────────────────────────────────────────────────────────────

export const PROVIDER_TYPES = [
  { value: "openai",     label: "OpenAI" },
  { value: "openai_web", label: "ChatGPT Web" },
  { value: "gemini",     label: "Google Gemini" },
  { value: "deepseek",   label: "DeepSeek" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "mistral",    label: "Mistral" },
];

export const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";

// ── Formatters ────────────────────────────────────────────────────────────────

export function fmtTokens(n: number): string {
  if (n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

export function fmtCtx(n?: number | null): string {
  if (!n) return "";
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

/** Cost for analysis tasks: 75% input + 25% output (typical chat distribution). */
export function blendedPrice(price_in?: number | null, price_out?: number | null): string {
  if (price_in == null) return "?";
  if (price_in === 0) return "free";
  const blended = price_in * 0.75 + (price_out ?? price_in) * 0.25;
  return `$${blended < 0.01 ? blended.toFixed(4) : blended.toFixed(2)}`;
}

/** Cost for vision tasks: show input price (image tokens are input-heavy). */
export function inputPrice(price_in?: number | null): string {
  if (price_in == null) return "?";
  if (price_in === 0) return "free";
  return `$${price_in < 0.01 ? price_in.toFixed(4) : price_in.toFixed(2)}`;
}

// ── Rating lookup ─────────────────────────────────────────────────────────────

export interface ModelRating {
  stars: number;      // 0-5 for quick visual fallback
  elo: number | null; // actual Elo score when available (e.g. 1320)
}

/**
 * Lookup rating by model id.
 * Tries: exact → strip provider prefix → strip date/preview suffix → Gemini family prefix.
 */
export function lookupModelRating(
  ratings: Record<string, ArenaRating>,
  modelId: string,
  forVision: boolean,
): ModelRating {
  const pickRating = (r: ArenaRating): ModelRating => ({
    stars: forVision ? r.vision : r.text,
    elo: r.elo ?? null,
  });

  const normalised = modelId.toLowerCase();

  // 1. Exact match
  if (ratings[normalised]) return pickRating(ratings[normalised]);

  // 2. Strip provider prefix: "openai/gpt-4o" → "gpt-4o"
  const short = normalised.split("/").pop() ?? "";
  if (short !== normalised && ratings[short]) return pickRating(ratings[short]);

  // 3. Strip date suffix: "gpt-4o-2024-11-20" → "gpt-4o"
  const withoutDate = normalised.replace(/-\d{4}-\d{2}(-\d{2})?$/, "");
  if (withoutDate !== normalised) {
    if (ratings[withoutDate]) return pickRating(ratings[withoutDate]);
    const shortDate = withoutDate.split("/").pop() ?? "";
    if (shortDate !== withoutDate && ratings[shortDate]) return pickRating(ratings[shortDate]);
  }

  // 4. Strip preview/exp/latest suffix: "gemini-3.1-flash-preview" → "gemini-3.1-flash"
  const withoutSuffix = normalised.replace(/-(preview|exp|latest|snapshot|experimental)(-\S+)?$/, "");
  if (withoutSuffix !== normalised && ratings[withoutSuffix]) return pickRating(ratings[withoutSuffix]);

  // 5. Gemini family prefix match: "gemini-3.1-flash-lite-preview" → "gemini-2.5-flash-lite"
  if (normalised.startsWith("gemini-")) {
    const isProModel = normalised.includes("-pro");
    const isFlashLite = normalised.includes("flash-lite") || normalised.includes("flash-8b");
    const isFlash = normalised.includes("flash") && !isFlashLite;
    const family = isProModel ? "gemini-2.5-pro" : isFlashLite ? "gemini-2.5-flash-lite" : isFlash ? "gemini-2.5-flash" : null;
    if (family && ratings[family]) return pickRating(ratings[family]);
  }

  return { stars: 0, elo: null };
}

// ── Add-provider form helpers ─────────────────────────────────────────────────

export function autoName(providerType: string, modelId: string, keyName: string): string {
  const base = modelId ? `${providerType}/${modelId}` : providerType;
  return keyName ? `${base} [${keyName}]` : base;
}

export function defaultKeyName(apiKey: string): string {
  return apiKey.length >= 5 ? `…${apiKey.slice(-5)}` : apiKey;
}
