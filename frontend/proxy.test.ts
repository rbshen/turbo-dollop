import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { config, proxy, SESSION_COOKIE } from "./proxy";

function req(path: string, cookie?: string) {
  return new NextRequest(`http://localhost:3100${path}`, cookie ? { headers: { cookie } } : undefined);
}

function matched(path: string): boolean {
  return config.matcher.some((m) => new RegExp(`^${m}$`).test(path));
}

describe("proxy: signed-out visitors go to /login", () => {
  it("redirects a page request without the session cookie, carrying the page as next", () => {
    const res = proxy(req("/screener?x=1"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("/login?next=%2Fscreener%3Fx%3D1");
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("redirects the root and a ticker with a dot in its symbol", () => {
    expect(proxy(req("/")).headers.get("location")).toBe("/login?next=%2F");
    expect(proxy(req("/tickers/BRK.B")).headers.get("location")).toBe("/login?next=%2Ftickers%2FBRK.B");
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
    expect(proxy(req("//evil.com/x")).headers.get("location")).toBe("/login");
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
