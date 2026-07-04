// Pins the OCR Lab duration/size formatters at their unit boundaries.
// See docs/code-map.md line: "pages/lab/labUtils.ts | formatMs, formatFileSize,
// uid".
//
// Doc:  code-map.md lists these as labUtils.ts responsibilities, but the exact unit
//       thresholds are not specified in any prose doc — these are general tests that
//       pin the current formatter behavior (the boundaries the Lab UI relies on).
// Rule: each test asserts the output string at a specific unit boundary.
import { describe, it, expect } from "vitest";
import { formatMs, formatFileSize } from "./labUtils";

describe("formatMs", () => {
  it("shows raw milliseconds under one second", () => {
    // Rule: < 1000 ms → "<n> ms".
    expect(formatMs(0)).toBe("0 ms");
    expect(formatMs(999)).toBe("999 ms");
  });

  it("shows seconds with one decimal under a minute", () => {
    // Rule: 1 s … <60 s → "<n.n> s".
    expect(formatMs(1000)).toBe("1.0 s");
    expect(formatMs(1500)).toBe("1.5 s");
  });

  it("shows minutes and seconds at or above a minute", () => {
    // Rule: ≥ 60 s → "<m> min <s> s".
    expect(formatMs(60000)).toBe("1 min 0 s");
    expect(formatMs(90000)).toBe("1 min 30 s");
  });
});

describe("formatFileSize", () => {
  it("shows bytes under 1 KB", () => {
    // Rule: < 1024 → "<n> B".
    expect(formatFileSize(0)).toBe("0 B");
    expect(formatFileSize(1023)).toBe("1023 B");
  });

  it("shows KB under 1 MB", () => {
    // Rule: 1 KB … <1 MB → "<n.n> KB".
    expect(formatFileSize(1024)).toBe("1.0 KB");
    expect(formatFileSize(1536)).toBe("1.5 KB");
  });

  it("shows MB at or above 1 MB", () => {
    // Rule: ≥ 1 MB → "<n.n> MB".
    expect(formatFileSize(1024 * 1024)).toBe("1.0 MB");
    expect(formatFileSize(1024 * 1024 * 2.5)).toBe("2.5 MB");
  });
});
