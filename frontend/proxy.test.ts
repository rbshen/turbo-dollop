import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, proxy, SESSION_COOKIE } from "./proxy";

function req(path: string, cookie?: string) {
  return new NextRequest(`http://localhost:3100${path}`, cookie ? { headers: { cookie } } : undefined);
}

function matched(path: string): boolean {
  return config.matcher.some((m) => new RegExp(`^${m}$`).test(path));
}

// These run the real `proxy` on a real NextRequest and a real NextResponse (nothing mocked), so a redirect target Next
// itself would refuse (the relative "/login?..." that threw "Invalid URL" in production) fails here too.
function target(path: string, cookie?: string): URL {
  const res = proxy(req(path, cookie));
  expect([302, 307]).toContain(res.status);
  return new URL(res.headers.get("location")!); // throws on a relative Location
}

describe("proxy: signed-out visitors go to /login", () => {
  it.each(["/", "/watchlist", "/screener?x=1", "/tickers/BRK.B", "/screener?a=1&b=two%20words"])(
    "redirects %s to an absolute /login whose next is the original path and query",
    (path) => {
      const res = proxy(req(path));
      expect(res.status).toBe(307);
      expect(res.headers.get("cache-control")).toBe("no-store");
      const url = target(path);
      expect(url.pathname).toBe("/login");
      expect(url.searchParams.get("next")).toBe(path);
      expect(url.search).toBe(`?next=${encodeURIComponent(path)}`); // URL-encoded
    },
  );

  it("builds the target on the request's own origin (whatever request.url reports), never a made-up host", () => {
    // NextRequest reports the Host header's origin for request.url when one is sent; either way the target stays on it.
    const r = new NextRequest("http://127.0.0.1:3100/watchlist", { headers: { host: "localhost:3100" } });
    expect(new URL(proxy(r).headers.get("location")!).origin).toBe(new URL(r.url).origin);
  });

  it("lets a request with the cookie through (it does not check the value: the backend does)", () => {
    const res = proxy(req("/screener", `${SESSION_COOKIE}=anything`));
    expect(res.status).toBe(200);
    expect(res.headers.get("location")).toBeNull();
    expect(res.headers.get("x-middleware-next")).toBe("1");
  });

  it("ignores a differently named cookie", () => {
    expect(proxy(req("/screener", "session=abc")).status).toBe(307);
  });

  it.each(["/login", "/login?next=%2Fscreener", "/login/"])("never redirects %s (no loop)", (p) => {
    expect(proxy(req(p)).status).toBe(200);
  });

  it("does not echo an unsafe path into next", () => {
    const url = target("//evil.com/x");
    expect(url.pathname).toBe("/login");
    expect(url.search).toBe("");
    expect(url.origin).toBe("http://localhost:3100");
  });
});

describe("proxy matcher", () => {
  it.each(["/", "/screener", "/tickers/AAPL", "/tickers/BRK.B", "/settings", "/login", "/styleguide", "/breadth/XLK"])(
    "covers the page %s",
    (p) => expect(matched(p)).toBe(true),
  );

  it.each(["/api/health", "/api/auth/login", "/api/tickers/AAPL/summary", "/api", "/_next/static/chunks/a.js", "/_next/image", "/favicon.ico", "/globe.svg", "/next.svg"])(
    "skips %s",
    (p) => expect(matched(p)).toBe(false),
  );

  it("does not skip a page that merely starts with api", () => {
    expect(matched("/apiary")).toBe(true);
  });
});
