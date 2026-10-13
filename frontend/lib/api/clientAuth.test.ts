// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { useSWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ADMIN_REQUIRED_MESSAGE, ApiError, apiFetch, apiPost, apiPut, errorDetail, errorStatus } from "@/lib/api/client";
import { resetRedirectGuardForTests } from "@/lib/auth/session";

const h = vi.hoisted(() => ({ navigate: vi.fn() }));
vi.mock("@/lib/auth/navigate", () => ({ navigate: h.navigate }));

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  const fetchMock = vi.fn().mockImplementation(async () => ({
    ok: status < 400,
    status,
    headers: new Headers(headers),
    json: async () => body,
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

// Settles within a few ticks, or reports that it is still pending.
async function settled(p: Promise<unknown>): Promise<"pending" | "resolved" | "rejected"> {
  return Promise.race([
    p.then(
      () => "resolved" as const,
      () => "rejected" as const,
    ),
    new Promise<"pending">((r) => setTimeout(() => r("pending"), 20)),
  ]);
}

beforeEach(() => {
  h.navigate.mockReset();
  resetRedirectGuardForTests();
  window.history.pushState({}, "", "/screener?x=1");
});
afterEach(() => vi.unstubAllGlobals());

describe("401 from the API", () => {
  it("sends the visitor to /login?next=<this page> and settles nothing, so no error is shown", async () => {
    respond(401, { detail: "Not authenticated" });
    const p = apiFetch("/screener");
    expect(await settled(p)).toBe("pending");
    expect(h.navigate).toHaveBeenCalledTimes(1);
    expect(h.navigate).toHaveBeenCalledWith("/login?next=%2Fscreener%3Fx%3D1");
  });

  it("redirects once when several requests fail together", async () => {
    respond(401, { detail: "Not authenticated" });
    void apiFetch("/a");
    void apiFetch("/b");
    void apiPost("/c");
    await settled(apiFetch("/d"));
    expect(h.navigate).toHaveBeenCalledTimes(1);
  });

  it("does not redirect from /login (no loop): the caller gets the error", async () => {
    window.history.pushState({}, "", "/login?next=%2Fscreener");
    respond(401, { detail: "Not authenticated" });
    const e = await apiFetch("/auth/me").catch((err) => err);
    expect(e).toBeInstanceOf(ApiError);
    expect(errorStatus(e)).toBe(401);
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("does not redirect for the login call itself: a wrong password is an answer", async () => {
    respond(401, { detail: "Invalid credentials" });
    const e = await apiPost("/auth/login", { username: "a", password: "b" }).catch((err) => err);
    expect(errorStatus(e)).toBe(401);
    expect(errorDetail(e)).toBe("Invalid credentials");
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("does not redirect for the logout call", async () => {
    respond(401, { detail: "Not authenticated" });
    await apiPost("/auth/logout").catch(() => {});
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("clears the SWR cache on the way out", async () => {
    const { result } = renderHook(() => useSWRConfig());
    await result.current.mutate("/watchlists", [1], { revalidate: false });
    expect(result.current.cache.get("/watchlists")?.data).toEqual([1]);
    respond(401, {});
    await settled(apiFetch("/x"));
    expect(result.current.cache.get("/watchlists")?.data).toBeUndefined();
  });
});

describe("403 from the API", () => {
  it("shows a plain admin-access message through the usual error path", async () => {
    respond(403, { detail: "Admin access required" });
    const e = await apiPut("/config/moat", { narrow_moat_multiplier: 0.8 }).catch((err) => err);
    expect(errorStatus(e)).toBe(403);
    expect(errorDetail(e)).toBe(ADMIN_REQUIRED_MESSAGE);
    expect((e as Error).message).toContain("failed: 403");
    expect(h.navigate).not.toHaveBeenCalled();
  });

  it("leaves a different 403 (the request guard's) as the backend wrote it", async () => {
    respond(403, { detail: "Cross-site request refused" });
    const e = await apiPost("/x").catch((err) => err);
    expect(errorDetail(e)).toBe("Cross-site request refused");
  });
});

describe("other failures", () => {
  it("carries the status of a 404 for the viewer's not-available state", async () => {
    respond(404, { detail: "Not found" });
    const e = await apiFetch("/tickers/ZZZ/summary").catch((err) => err);
    expect(errorStatus(e)).toBe(404);
    expect(errorStatus(new Error("x"))).toBeUndefined();
  });

  it("reads Retry-After from a 429", async () => {
    respond(429, { detail: "Too many failed sign-in attempts. Try again later." }, { "Retry-After": "840" });
    const e = (await apiPost("/auth/login", {}).catch((err) => err)) as ApiError;
    expect(e.status).toBe(429);
    expect(e.retryAfter).toBe(840);
  });

  it("has no retryAfter when the header is absent or not a number", async () => {
    respond(429, {}, { "Retry-After": "soon" });
    expect(((await apiPost("/auth/login", {}).catch((err) => err)) as ApiError).retryAfter).toBeUndefined();
  });
});
