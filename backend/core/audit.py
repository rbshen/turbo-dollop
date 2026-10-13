"""The audit log (docs/specs/auth.md): one `AuditLog` row per login event and per non-GET request outcome. It records who (user id and
name, or null), what (method, path without query string, status, event) and from where (source address). It never records a request body,
a password, a token, a hash or a header. A failed write is logged (without the row) and swallowed: the audit trail must never break the
request it describes. Uses `core.auth.engine`, so the test isolation of that one reference covers it."""

import logging

from sqlmodel import Session

import core.auth as auth
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
