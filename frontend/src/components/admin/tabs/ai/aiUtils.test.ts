// Pins the AI-tab formatters and the model-rating lookup fallback chain.
// See docs/code-map.md line: "components/admin/tabs/ai/aiUtils.ts | Constants +
// formatters (fmtTokens, blendedPrice, …) + lookupModelRating + add-form name helpers".
//
// Each test carries:
//   Doc:  which documented area it protects (or "none" for code-only behavior)
//   Rule: the specific behavior it asserts
import { describe, it, expect } from "vitest";
import { blendedPrice, fmtTokens, lookupModelRating } from "./aiUtils";
import type { ArenaRating } from "../../../../types";

describe("fmtTokens", () => {
  it("formats zero, thousands, and millions", () => {
    // Doc:  docs/code-map.md lists fmtTokens as an aiUtils.ts formatter. No prose
    //       rule on the exact thresholds — general test pinning the K/M rounding.
    // Rule: 0 → "0", ≥1K → "<n>K", ≥1M → "<n.n>M", else the raw number.
    expect(fmtTokens(0)).toBe("0");
    expect(fmtTokens(5_000)).toBe("5K");
    expect(fmtTokens(2_000_000)).toBe("2.0M");
    expect(fmtTokens(500)).toBe("500");
  });
});

describe("blendedPrice", () => {
  it("returns '?' when input price is unknown", () => {
    // Doc:  docs/code-map.md (aiUtils.ts formatter). Behavior defined in the
    //       function's own comment "Cost for analysis tasks: 75% input + 25% output".
    // Rule: a null/undefined input price renders as "?".
    expect(blendedPrice(null)).toBe("?");
    expect(blendedPrice(undefined)).toBe("?");
  });

  it("returns 'free' for a zero input price", () => {
    // Doc:  as above — pins the aiUtils blendedPrice comment.
    // Rule: a zero input price renders as "free".
    expect(blendedPrice(0)).toBe("free");
  });

  it("blends 75% input + 25% output", () => {
    // Doc:  as above — the 75/25 split is the documented analysis-cost heuristic.
    // Rule: blended = price_in*0.75 + price_out*0.25  (1*0.75 + 3*0.25 = 1.5).
    expect(blendedPrice(1, 3)).toBe("$1.50");
  });

  it("falls back to input price when output price is absent", () => {
    // Doc:  as above.
    // Rule: missing price_out defaults to price_in (2*0.75 + 2*0.25 = 2).
    expect(blendedPrice(2)).toBe("$2.00");
  });

  it("uses 4 decimals for sub-cent prices", () => {
    // Doc:  none — general test pinning the display-precision branch.
    // Rule: values < $0.01 show 4 decimals instead of 2.
    expect(blendedPrice(0.004, 0.004)).toBe("$0.0040");
  });
});

describe("lookupModelRating", () => {
  // Doc:  docs/code-map.md lists lookupModelRating as an aiUtils.ts responsibility.
  //       The 5-tier fallback chain is documented in the function's own JSDoc
  //       ("exact → strip provider prefix → strip date/preview suffix → Gemini family").
  //       No prose doc beyond that — these tests pin each documented tier.
  const ratings: Record<string, ArenaRating> = {
    "gpt-4o": { text: 4, vision: 3, elo: 1300 },
    "gemini-2.5-flash": { text: 5, vision: 4, elo: 1320 },
  };

  it("matches exactly (case-insensitive)", () => {
    // Rule: tier 1 — exact id match, lower-cased.
    expect(lookupModelRating(ratings, "GPT-4o", false)).toEqual({ stars: 4, elo: 1300 });
  });

  it("strips a provider prefix", () => {
    // Rule: tier 2 — "openai/gpt-4o" → "gpt-4o".
    expect(lookupModelRating(ratings, "openai/gpt-4o", false).stars).toBe(4);
  });

  it("strips a date suffix", () => {
    // Rule: tier 3 — "gpt-4o-2024-11-20" → "gpt-4o".
    expect(lookupModelRating(ratings, "gpt-4o-2024-11-20", false).stars).toBe(4);
  });

  it("strips a preview suffix", () => {
    // Rule: tier 4 — "gpt-4o-preview" → "gpt-4o".
    expect(lookupModelRating(ratings, "gpt-4o-preview", false).stars).toBe(4);
  });

  it("falls back to the Gemini family prefix", () => {
    // Rule: tier 5 — unknown Gemini id resolves to its family ("…flash…" → gemini-2.5-flash).
    expect(lookupModelRating(ratings, "gemini-3.1-flash-preview", false).stars).toBe(5);
  });

  it("returns the vision star count when forVision is true", () => {
    // Rule: forVision selects ArenaRating.vision instead of .text.
    expect(lookupModelRating(ratings, "gpt-4o", true).stars).toBe(3);
  });

  it("returns zero stars and null elo on a miss", () => {
    // Rule: no tier matches → neutral {stars: 0, elo: null}.
    expect(lookupModelRating(ratings, "totally-unknown-model", false)).toEqual({
      stars: 0,
      elo: null,
    });
  });
});
