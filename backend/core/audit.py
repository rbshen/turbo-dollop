"""The audit log (docs/specs/auth.md): one `AuditLog` row per login event and per non-GET request outcome. It records who (user id and
name, or null), what (method, path without query string, status, event) and from where (source address). It never records a request body,
a password, a token, a hash or a header. A failed write is logged (without the row) and swallowed: the audit trail must never break the
request it describes. Uses `core.auth.engine`, so the test isolation of that one reference covers it."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

import core.auth as auth
from core.config import settings
from core.models import AuditLog

logger = logging.getLogger(__name__)

MAX_PATH_LENGTH = 200


def write_audit(
    *,
    event: str,
    method: str,
    path: str,
    status: int,
    ip: str | None,
    user_id: int | None = None,
    username: str | None = None,
) -> None:
    try:
        with Session(auth.engine) as session:
            session.add(
                AuditLog(
                    ts=auth.utcnow(),
                    user_id=user_id,
                    username=username,
                    method=method.upper()[:10],
                    path=path.split("?", 1)[0][:MAX_PATH_LENGTH],
                    status=status,
                    ip=(ip or None) and ip[:64],
                    event=event,
                )
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001 -- never break the request
        logger.warning("Audit write failed (%s); event=%s status=%s", type(exc).__name__, event, status)


def prune_audit_log(days: int | None = None, *, now: datetime | None = None) -> int:
    """Deletes `auditlog` rows older than `days` (default `settings.audit_retention_days`, 180) and returns how many. Only the audit table is
    touched: never a user, a session or any other table. `days` must be a whole number of at least 1 (0 would be "everything")."""
    days = settings.audit_retention_days if days is None else days
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("days must be a whole number of at least 1.")
    cutoff = (now or auth.utcnow()) - timedelta(days=days)
    with Session(auth.engine) as session:
        result = session.execute(delete(AuditLog).where(AuditLog.ts < cutoff))
        session.commit()
        return result.rowcount or 0


# ---- the request audit middleware ---------------------------------------------------------------------------------

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# The login and logout routes write their own, richer rows (login_ok, login_fail, lockout, ...).
SELF_AUDITED_PATHS = frozenset({"/api/auth/login", "/api/auth/logout"})


class AuditMiddleware:
    """Pure ASGI middleware, outside the request guard (so a request the guard refuses is recorded too): after the response is decided
    and sent, writes one `request` row for every non-GET request (method, path, status, who, source). The write runs in a worker thread
    (a locked database must not freeze the event loop) and can never change the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS or scope["path"] in SELF_AUDITED_PATHS:
            await self.app(scope, receive, send)
            return
        status = {"code": 500}  # what the server sends when the app raises

        async def capture(message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            principal = scope.get(auth.PRINCIPAL_SCOPE_KEY)
            client = scope.get("client")
            try:
                await run_in_threadpool(
                    write_audit,
                    event="request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status["code"],
                    ip=client[0] if client else None,
                    user_id=principal.user_id if principal else None,
                    username=principal.username if principal else None,
                )
            except Exception:  # noqa: BLE001 -- write_audit already swallows; this guards the thread hop itself
                logger.warning("Audit hand-off failed")
