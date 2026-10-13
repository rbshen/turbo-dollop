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
  // Next 16 rejects a relative redirect target from a proxy ("TypeError: Invalid URL", a 500 on every signed-out page), so the
  // target is built as an absolute URL from the incoming request. `request.url` carries Next's own bind address
  // (http://127.0.0.1:3100, not the Host the browser sent through the SSH tunnel), and that is fine: Next rewrites a
  // Location on the request's own origin to a path-only one before it is sent (router-utils/resolve-routes.js,
  // getRelativeURL), so the browser resolves it against the address it actually used. No host name is read or trusted here.
  const target = new URL(loginUrl(pathname + search), request.url);
  return NextResponse.redirect(target, { status: 307, headers: { "Cache-Control": "no-store" } });
}

// Everything except /api, Next's own build output and image route, and the static files in public/ (matched by extension, so a
// ticker such as /tickers/BRK.B still goes through the check).
export const config = {
  matcher: ["/((?!api(?:/|$)|_next/|favicon\\.ico$|.*\\.(?:svg|png|jpe?g|gif|webp|ico|txt|xml|webmanifest|map|js|css|woff2?)$).*)"],
};
