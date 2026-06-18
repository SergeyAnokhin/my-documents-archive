import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "./client";

afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("returns undefined on 204 No Content", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 204 }));
    expect(await api.delete("/x")).toBeUndefined();
  });

  it("throws with server-provided detail on error response", async () => {
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
