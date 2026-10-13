import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// Content-Security-Policy. This is the loosest form that still gives real protection, chosen so the app and its
// charts keep working without a nonce pipeline:
//  - script-src needs 'unsafe-inline' because Next.js emits inline bootstrap/flight-data scripts, and 'unsafe-eval'
//    only under `next dev` (React's dev tooling). Everything is served from this origin: next/font self-hosts the
//    Google fonts at build time, and there are no remote scripts, images or analytics.
//  - style-src needs 'unsafe-inline' for the style attributes Recharts and lightweight-charts set on their elements.
//  - img-src allows data: and blob: for chart canvases/exports; connect-src is this origin only (every API call goes
//    through the /api rewrite), plus the dev server's websocket under `next dev`.
//  - frame-ancestors 'none' (with X-Frame-Options DENY), object-src 'none', base-uri and form-action 'self' close the
//    clickjacking, plugin, <base> and forged-form routes.
// Tighten later by moving to nonces (a proxy.ts + dynamic rendering) and dropping 'unsafe-inline' from script-src.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${isDev ? " ws://localhost:* ws://127.0.0.1:*" : ""}`,
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

// No Strict-Transport-Security: the app is served over plain http on localhost through an SSH tunnel.
const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()",
  },
];

const nextConfig: NextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8002/api/:path*",
      },
    ];
  },
};

export default nextConfig;
