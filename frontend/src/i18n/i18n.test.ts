// Pins i18n key-set parity across all three languages.
// See docs/code-map.md i18n entries: en.ts is the "source of the Translations type",
// with ru.ts and fr.ts as the Russian/French translations.
//
// Each test carries:
//   Doc:  which documented area it protects
//   Rule: the specific behavior it asserts
import { describe, it, expect } from "vitest";
import { en, ru, fr } from "./index";

function keyPaths(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    return v && typeof v === "object" && !Array.isArray(v)
      ? keyPaths(v as Record<string, unknown>, path)
      : [path];
  });
}

describe("i18n", () => {
  const enKeys = keyPaths(en).sort();

  it("ru and en expose an identical set of keys", () => {
    // Doc:  code-map.md — ru.ts must implement the same Translations shape as en.ts.
    // Rule: no key in en.ts is missing from (or extra in) ru.ts.
    expect(keyPaths(ru).sort()).toEqual(enKeys);
  });

  it("fr and en expose an identical set of keys", () => {
    // Doc:  code-map.md — fr.ts must implement the same Translations shape as en.ts.
    // Rule: no key in en.ts is missing from (or extra in) fr.ts.
    expect(keyPaths(fr).sort()).toEqual(enKeys);
  });
});
