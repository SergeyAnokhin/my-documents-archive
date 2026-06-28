// Pins imgSrc resolution logic used by DocumentViewer.
// See docs/code-map.md: "components/documents/imgSrc.ts | Resolves the <img src>
// value from an optional edit preview and a nullable raw URL."
//
// Each test carries:
//   Doc:  which documented area it protects
//   Rule: the specific behavior it asserts
import { describe, it, expect } from "vitest";
import { resolveImgSrc } from "./imgSrc";

describe("resolveImgSrc", () => {
  it("returns undefined (not null) when rawSrc is null and no preview", () => {
    // Doc:  code-map.md → imgSrc.ts
    // Rule: <img src> accepts string | undefined, not null. When the document
    //       has no thumbnail and no preview, src must be undefined, never null.
    expect(resolveImgSrc(null, null)).toBeUndefined();
  });

  it("returns rawSrc when there is no preview", () => {
    // Doc:  code-map.md → imgSrc.ts
    // Rule: without an active edit preview, the raw URL (thumbnail or docUrl) is used.
    expect(resolveImgSrc(null, "/thumbnails/foo.jpg")).toBe("/thumbnails/foo.jpg");
    expect(resolveImgSrc(undefined, "/thumbnails/foo.jpg")).toBe("/thumbnails/foo.jpg");
  });

  it("returns a data URL when preview b64 is provided", () => {
    // Doc:  code-map.md → imgSrc.ts
    // Rule: an active edit preview takes precedence over rawSrc.
    expect(resolveImgSrc("abc123", null)).toBe("data:image/jpeg;base64,abc123");
    expect(resolveImgSrc("abc123", "/thumbnails/foo.jpg")).toBe("data:image/jpeg;base64,abc123");
  });
});
