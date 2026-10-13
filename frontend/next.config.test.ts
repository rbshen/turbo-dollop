import { describe, expect, it } from "vitest";

import nextConfig from "./next.config";

async function headerMap(): Promise<Record<string, string>> {
  const rules = await nextConfig.headers!();
  const all = rules.find((r) => r.source === "/:path*");
  expect(all).toBeDefined();
  return Object.fromEntries(all!.headers.map((h) => [h.key, h.value]));
}

describe("next.config security headers", () => {
  it("sends the fixed headers on every route and no HSTS", async () => {
    const h = await headerMap();
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["Referrer-Policy"]).toBe("same-origin");
    expect(h["Permissions-Policy"]).toContain("camera=()");
    expect(h["Permissions-Policy"]).toContain("geolocation=()");
    expect(h).not.toHaveProperty("Strict-Transport-Security");
  });

  it("has a CSP that keeps the app working and shuts the dangerous routes", async () => {
    const csp = (await headerMap())["Content-Security-Policy"];
    const directive = (name: string) => csp.split("; ").find((d) => d.startsWith(`${name} `));
    expect(directive("default-src")).toBe("default-src 'self'");
    expect(directive("script-src")).toContain("'unsafe-inline'"); // Next's inline bootstrap scripts
    expect(directive("script-src")).not.toContain("'unsafe-eval'"); // test runs with NODE_ENV=test, not development
    expect(directive("style-src")).toContain("'unsafe-inline'"); // Recharts / lightweight-charts style attributes
    expect(directive("frame-ancestors")).toBe("frame-ancestors 'none'");
    expect(directive("object-src")).toBe("object-src 'none'");
    expect(directive("base-uri")).toBe("base-uri 'self'");
    expect(directive("form-action")).toBe("form-action 'self'");
    expect(directive("connect-src")).toBe("connect-src 'self'");
    expect(csp).not.toMatch(/https?:\/\//); // no remote origin is allowed anywhere
  });

  it("hides X-Powered-By and still proxies /api to the loopback backend", async () => {
    expect(nextConfig.poweredByHeader).toBe(false);
    const rewrites = (await nextConfig.rewrites!()) as { source: string; destination: string }[];
    expect(rewrites).toEqual([{ source: "/api/:path*", destination: "http://localhost:8002/api/:path*" }]);
  });
});
