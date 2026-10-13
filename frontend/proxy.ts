import { NextResponse, type NextRequest } from "next/server";

import { loginUrl } from "./lib/auth/safeNext";

// A CONVENIENCE, NOT A SECURITY CONTROL. This only checks that a `fathom_session` cookie is present, so a signed-out visitor
// lands on /login instead of on a page of 401s. It cannot tell a valid session from a made-up one (it never asks the
// backend), and /api is not matched at all. The enforcement is the backend: every /api route except GET /api/health and
// POST /api/auth/login needs a real session, and the viewer rules are applied there (docs/specs/auth.md). Never rely on this
// file to keep anything from anyone.
export const SESSION_COOKIE = "fathom_session";

/** Pages a signed-out visitor may load: the login form. (/api and the static assets are left out by `config.matcher`.) */
export function isPublicPath(pathname: string): boolean {
  return pathname === "/login" || pathname.startsWith("/login/");
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  if (isPublicPath(pathname) || request.cookies.has(SESSION_COOKIE)) return NextResponse.next();
  // A relative Location: the browser resolves it against the address it used (localhost through the SSH tunnel), whatever
  // host name Next itself was started with. NextResponse.redirect would need an absolute URL built from that host.
  return new NextResponse(null, {
    status: 307,
    headers: { Location: loginUrl(pathname + search), "Cache-Control": "no-store" },
  });
}

// Everything except /api, Next's own build output and image route, and the static files in public/ (matched by extension, so a
// ticker such as /tickers/BRK.B still goes through the check).
export const config = {
  matcher: ["/((?!api(?:/|$)|_next/|favicon\\.ico$|.*\\.(?:svg|png|jpe?g|gif|webp|ico|txt|xml|webmanifest|map|js|css|woff2?)$).*)"],
};
