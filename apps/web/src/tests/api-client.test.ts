import { describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { ApiConnectionError, ApiInvalidJsonError } from "../api/errors";
import { incidentDetail, response } from "./fixtures";

describe("API client safety", () => {
  it("URL-encodes report IDs before making requests", async () => {
    const fetchMock = vi.fn<typeof fetch>(() =>
      Promise.resolve(response(incidentDetail)),
    );
    vi.stubGlobal("fetch", fetchMock);
    await api.incident("id with/slash?");
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(String(fetchMock.mock.calls[0][0])).toContain(
      "id%20with%2Fslash%3F",
    );
  });

  it("turns connection failures into a useful safe error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("private network detail"))),
    );
    await expect(api.health()).rejects.toEqual(expect.any(ApiConnectionError));
    await expect(api.health()).rejects.toThrow(
      "Unable to connect to the Diagnosis Service.",
    );
  });

  it("distinguishes invalid JSON responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("not-json", { status: 200 }))),
    );
    await expect(api.health()).rejects.toEqual(expect.any(ApiInvalidJsonError));
  });
});
