"""Host and cross-site request protection for the live FastAPI app (installed in core/main.py).

The app is reached through an SSH tunnel at http://localhost:3100 and has no login, so the browser is the only
caller that matters and the two browser attacks to stop are DNS rebinding and cross-site request forgery:

* **Host check (every request).** The Host header must be one of ALLOWED_HOSTS (default localhost, 127.0.0.1, [::1])
  on one of ALLOWED_HOST_PORTS (default 8002 backend, 3100 frontend). A rebinding page reaches the loopback
  address under its own hostname, so its Host never matches. Starlette's TrustedHostMiddleware is not used because
  it splits the Host on the first ":" and so cannot match "[::1]:8002". 400 on a mismatch.
* **Cross-site check (every request except GET, HEAD, OPTIONS).** When the request carries an Origin, it must be in
  ALLOWED_ORIGINS (default http://localhost:3100 and http://127.0.0.1:3100); "null" never matches. When it carries
  no Origin it must carry a non-empty X-Fathom-Request header (set by frontend/lib/api/client.ts), and a Referer, if
  present, must also match. A cross-site HTML form cannot set a custom header, and a cross-site fetch that sets one
  needs a CORS preflight the app never answers, so both are stopped. 403 on a mismatch.

Settings are read on every request (not at import) so tests and a long-lived process see the same values the
environment holds. Cron jobs and scripts never go through the app, so none of this applies to them.
"""

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from core.config import settings

CUSTOM_HEADER = "x-fathom-request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _csv(value: str) -> list[str]:
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def split_host_header(value: str) -> tuple[str, int | None] | None:
    """'localhost:8002' -> ('localhost', 8002); '[::1]:8002' -> ('[::1]', 8002); no port -> (host, None).
    None when the value cannot be read as a host[:port]."""
    value = value.strip().lower()
    if not value:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None
        host, rest = value[: end + 1], value[end + 1 :]
        if rest == "":
            return host, None
        if not rest.startswith(":"):
            return None
        port_text = rest[1:]
    else:
        host, sep, port_text = value.partition(":")
        if not sep:
            return host, None
        if ":" in port_text:  # an unbracketed IPv6 literal is not a valid Host
            return None
    if not port_text.isascii() or not port_text.isdigit():
        return None
    return host, int(port_text)


def host_allowed(host_header: str) -> bool:
    parsed = split_host_header(host_header)
    if parsed is None:
        return False
    host, port = parsed
    if host not in _csv(settings.allowed_hosts):
        return False
    return port is not None and str(port) in _csv(settings.allowed_host_ports)


def _origin_of(url: str) -> str | None:
    """'http://localhost:3100/some/path?x=1' -> 'http://localhost:3100'; None if it has no scheme and host."""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def origin_allowed(origin: str) -> bool:
    normalized = origin.strip().lower().rstrip("/")
    return normalized in {o.rstrip("/") for o in _csv(settings.allowed_origins)}


def cross_site_rejection(method: str, headers: dict[str, str]) -> str | None:
    """The reason a non-safe request is rejected, or None when it may proceed."""
    if method.upper() in SAFE_METHODS:
        return None
    if "origin" in headers:
        if not origin_allowed(headers["origin"]):
            return "Cross-site request rejected: Origin is not allowed."
        return None
    if not headers.get(CUSTOM_HEADER, "").strip():
        return "Request rejected: no Origin and no X-Fathom-Request header."
    referer = headers.get("referer")
    if referer:
        referer_origin = _origin_of(referer)
        if referer_origin is None or not origin_allowed(referer_origin):
            return "Cross-site request rejected: Referer is not allowed."
    return None


async def _reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RequestGuardMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if not host_allowed(headers.get("host", "")):
            await _reject(send, 400, "Invalid host header.")
            return
        reason = cross_site_rejection(scope["method"], headers)
        if reason is not None:
            await _reject(send, 403, reason)
            return
        await self.app(scope, receive, send)
