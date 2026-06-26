// Pins the fetch-wrapper contract.
// See docs/code-map.md line: "api/client.ts | Thin fetch wrapper (api.get/post/patch/
// delete/upload)". The DELETE-returns-204 and error-`detail` shapes are documented in
// docs/api.md (admin/document endpoints return 204; error bodies carry `detail`).
//
// Each test carries:
//   Doc:  which documented area it protects
//   Rule: the specific behavior it asserts
import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "./client";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("returns undefined on 204 No Content", async () => {
    // Doc:  docs/api.md — DELETE endpoints (e.g. /api/documents/{id}) return 204.
    // Rule: a 204 response resolves to undefined (no body parse attempted).
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 204 }));
    expect(await api.delete("/x")).toBeUndefined();
  });

  it("throws with server-provided detail on error response", async () => {
    // Doc:  docs/api.md — error responses carry a `detail` field (FastAPI convention).
    // Rule: a non-ok response throws an Error using the server's `detail` message.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        statusText: "Bad Request",
        json: async () => ({ detail: "boom" }),
      }),
    );
    await expect(api.get("/x")).rejects.toThrow("boom");
  });
});
