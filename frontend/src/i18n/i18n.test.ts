import { describe, it, expect } from "vitest";
import { en, ru } from "./index";

function keyPaths(obj: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const path = prefix ? `${prefix}.${k}` : k;
    return v && typeof v === "object" && !Array.isArray(v)
      ? keyPaths(v as Record<string, unknown>, path)
      : [path];
  });
}

describe("i18n", () => {
  it("ru and en expose an identical set of keys", () => {
    expect(keyPaths(ru).sort()).toEqual(keyPaths(en).sort());
  });
});
