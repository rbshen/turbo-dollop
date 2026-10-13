"""Accounts, sessions and login throttling (docs/specs/auth.md).

* **Accounts** are created by an admin with `python -m core.auth_cli` only. `User.username` is stored normalized (stripped,
  lowercase). Roles: "admin" (everything) and "viewer" (read-only, tracked tickers only, cache only).
* **Sessions** are an opaque random token (`secrets.token_urlsafe(32)`, 256 bits) in an httpOnly cookie; only its SHA-256 is stored.
  A session ends at the first of: the idle timeout (`session_idle_days` since `last_seen_at`), the absolute lifetime
  (`session_absolute_days` since login), logout, a disable, a password change, or `revoke-sessions`. Foreign keys are off in this
  database, so every one of those deletes the user's `UserSession` rows explicitly. `last_seen_at` is refreshed at most once every
  SESSION_TOUCH_SECONDS and read first (the pattern of data/tracked_universe.py::record_ticker_view), so a page of requests is not a
  page of writes; the idle timeout is therefore accurate to that many seconds.
* **Login throttling** has three layers, all temporary: a per-user lockout in the DB (`failed_logins`, `locked_until`; survives a
  restart; a successful login resets it), the same counter in memory for names that do not exist (so a lockout cannot be used to tell
  which usernames exist), and a per-source window (`login_source_max_failures` in `login_source_window_minutes`). Behind the SSH
  tunnel every request arrives from 127.0.0.1, so the per-source layer is in effect one global limit. No layer is permanent: the
  longest block is `login_lockout_minutes` (default 15) or the source window, and the CLI (`set-password`) clears a user's lock.
* Unknown, inactive and locked accounts all pay for one dummy password check, and every refusal reads "Invalid credentials" (401) or
  the same "Too many failed sign-in attempts" (429), so neither the answer nor the timing names an existing account.

All timestamps are naive UTC (`utcnow`; tests patch it). This module owns its `engine` reference (patched per test in conftest)."""

import hashlib
import logging
import re
import secrets
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import delete, update
from sqlmodel import Session, func, select

from core.config import settings
from core.db import engine
from core.models import AuditLog, User, UserSession
from core.passwords import dummy_verify, hash_password, needs_rehash, validate_password_policy, verify_password
from core.route_roles import role_for

logger = logging.getLogger(__name__)

ROLES = ("admin", "viewer")
COOKIE_NAME = "fathom_session"
SESSION_TOUCH_SECONDS = 300
USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
MAX_USERNAME_LENGTH = 64
TOO_MANY_DETAIL = "Too many failed sign-in attempts. Try again later."
INVALID_DETAIL = "Invalid credentials"
_MAX_TRACKED_KEYS = 5000


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


# --- accounts ---------------------------------------------------------------------------------------------------


def normalize_username(raw: str) -> str:
    return (raw or "").strip().lower()


def validate_username(name: str) -> str:
    """The normalized name, or ValueError when it is not 1-64 characters of a-z, 0-9, '.', '_' or '-' starting with a letter or digit."""
    name = normalize_username(name)
    if not USERNAME_PATTERN.fullmatch(name):
        raise ValueError("A username is 1-64 characters: letters, digits, '.', '_' or '-', starting with a letter or digit.")
    return name


def _user(session: Session, username: str) -> User | None:
    return session.exec(select(User).where(User.username == normalize_username(username))).first()


def get_user(session: Session, username: str) -> User:
    user = _user(session, username)
    if user is None:
        raise LookupError(f"No user named '{normalize_username(username)}'.")
    return user


def create_user(session: Session, username: str, password: str, role: str, *, hasher=hash_password) -> User:
    name = validate_username(username)
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}.")
    validate_password_policy(password)
    if _user(session, name) is not None:
        raise ValueError(f"A user named '{name}' already exists.")
    # SQLite reuses the largest rowid after its row is deleted; keep an id that an audit row or session still names from coming back.
    top = max(
        session.exec(select(func.max(User.id))).one() or 0,
        session.exec(select(func.max(AuditLog.user_id))).one() or 0,
        session.exec(select(func.max(UserSession.user_id))).one() or 0,
    )
    user = User(id=top + 1, username=name, password_hash=hasher(password), role=role, is_active=True, created_at=utcnow())
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def delete_user_sessions(session: Session, user_id: int) -> int:
    count = session.execute(delete(UserSession).where(UserSession.user_id == user_id)).rowcount
    return count or 0


def delete_user(session: Session, username: str) -> int:
    """Deletes the account and all its `usersession` rows (explicitly: foreign keys are off) and writes one `user_deleted` audit row,
    in ONE transaction. Existing `auditlog` rows are kept (they carry the username as text). Refuses (ValueError, nothing changed) to
    delete the last active admin. Returns the number of sessions ended. The username is free again afterwards; a recreated account gets a
    new id (`create_user` never hands out an id an audit row still names)."""
    user = get_user(session, username)
    if user.role == "admin" and user.is_active:
        others = session.exec(select(func.count()).select_from(User).where(User.role == "admin", User.is_active == True, User.id != user.id)).one()  # noqa: E712
        if not others:
            raise ValueError(f"'{user.username}' is the last active admin; create or enable another admin first.")
    user_id, name = user.id, user.username
    try:
        ended = delete_user_sessions(session, user_id)
        session.execute(delete(User).where(User.id == user_id))
        session.add(AuditLog(ts=utcnow(), user_id=user_id, username=name, method="CLI", path="core.auth_cli delete-user", status=200, event="user_deleted"))
        session.commit()
    except Exception:
        session.rollback()
        raise
    return ended


def set_password(session: Session, username: str, password: str, *, hasher=hash_password) -> int:
    """Sets a new password, ends the user's sessions and clears the login throttle. Returns the number of sessions ended."""
    user = get_user(session, username)
    validate_password_policy(password)
    user.password_hash = hasher(password)
    user.failed_logins = 0
    user.locked_until = None
    session.add(user)
    ended = delete_user_sessions(session, user.id)
    session.commit()
    return ended


def set_active(session: Session, username: str, active: bool) -> int:
    """Enable or disable. A disable ends the user's sessions (returns how many); an enable returns 0."""
    user = get_user(session, username)
    user.is_active = active
    session.add(user)
    ended = 0 if active else delete_user_sessions(session, user.id)
    session.commit()
    return ended


def revoke_sessions(session: Session, username: str | None = None) -> int:
    """Ends one user's sessions, or every session when `username` is None."""
    if username is None:
        ended = session.execute(delete(UserSession)).rowcount or 0
    else:
        ended = delete_user_sessions(session, get_user(session, username).id)
    session.commit()
    return ended


# --- sessions ---------------------------------------------------------------------------------------------------


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def idle_timeout() -> timedelta:
    return timedelta(days=settings.session_idle_days)


def absolute_lifetime() -> timedelta:
    return timedelta(days=settings.session_absolute_days)


def create_session(session: Session, user: User, ip: str | None, user_agent: str | None) -> tuple[str, UserSession]:
    """A new session for `user`: returns (the raw token for the cookie, the stored row). Also drops every expired session (housekeeping)."""
    now = utcnow()
    session.execute(delete(UserSession).where(UserSession.expires_at <= now))
    token = secrets.token_urlsafe(32)
    row = UserSession(
        token_hash=hash_token(token),
        user_id=user.id,
        created_at=now,
        expires_at=now + absolute_lifetime(),
        last_seen_at=now,
        ip=(ip or None) and ip[:64],
        user_agent=(user_agent or None) and user_agent[:200],
    )
    session.add(row)
    session.commit()
    return token, row


def delete_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(UserSession).where(UserSession.token_hash == hash_token(token)))
        session.commit()


def resolve_session(token: str | None) -> Principal | None:
    """The signed-in user for a cookie token, or None (unknown, expired, idle too long, or the user is disabled). Reads first; writes
    only to drop a dead session or to refresh `last_seen_at` once per SESSION_TOUCH_SECONDS, and never fails the request over it."""
    if not token or len(token) > 200:
        return None
    now = utcnow()
    with Session(engine) as session:
        row = session.get(UserSession, hash_token(token))
        if row is None:
            return None
        user = session.get(User, row.user_id)
        if row.expires_at <= now or row.last_seen_at + idle_timeout() <= now or user is None or not user.is_active:
            _best_effort(session, lambda: session.delete(row))
            return None
        if now - row.last_seen_at >= timedelta(seconds=SESSION_TOUCH_SECONDS):
            row.last_seen_at = now
            _best_effort(session, lambda: session.add(row))
        return Principal(user_id=user.id, username=user.username, role=user.role)


def _best_effort(session: Session, change) -> None:
    try:
        change()
        session.commit()
    except Exception:  # noqa: BLE001 -- a session housekeeping write must never fail the request
        session.rollback()
        logger.warning("Session housekeeping write failed", exc_info=True)


# --- login throttle ---------------------------------------------------------------------------------------------


class LoginRejected(Exception):
    """A refused login. `status` is 401 (wrong/unknown/inactive) or 429 (throttled); `event` is the audit event; `username` is set
    only for an existing account (a typed name that matches none may be a password in the wrong box, so it is never logged)."""

    def __init__(self, status: int, detail: str, event: str, retry_after: int | None = None, username: str | None = None):
        super().__init__(detail)
        self.status, self.detail, self.event, self.retry_after, self.username = status, detail, event, retry_after, username


class _Throttle:
    """In-memory counters: failures per source in a sliding window, and failures per name that matches no account."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._source: dict[str, deque[datetime]] = {}
        self._names: dict[str, tuple[int, datetime | None]] = {}

    def reset(self) -> None:
        with self._lock:
            self._source.clear()
            self._names.clear()

    def source_retry_after(self, source: str, now: datetime) -> int | None:
        window = timedelta(minutes=settings.login_source_window_minutes)
        with self._lock:
            failures = self._source.get(source)
            if not failures:
                return None
            while failures and now - failures[0] >= window:
                failures.popleft()
            if len(failures) < settings.login_source_max_failures:
                return None
            return max(1, int((failures[0] + window - now).total_seconds()))

    def record_source_failure(self, source: str, now: datetime) -> None:
        with self._lock:
            if len(self._source) >= _MAX_TRACKED_KEYS and source not in self._source:
                self._source.clear()
            self._source.setdefault(source, deque()).append(now)

    def name_retry_after(self, name: str, now: datetime) -> int | None:
        with self._lock:
            count, locked_until = self._names.get(name, (0, None))
            if locked_until is not None and locked_until > now:
                return max(1, int((locked_until - now).total_seconds()))
            return None

    def record_name_failure(self, name: str, now: datetime) -> bool:
        """Counts a failure for a name with no account; True when this one reached the lockout threshold."""
        with self._lock:
            if len(self._names) >= _MAX_TRACKED_KEYS and name not in self._names:
                self._names.clear()
            count, locked_until = self._names.get(name, (0, None))
            if locked_until is not None and locked_until <= now:
                count, locked_until = 0, None
            count += 1
            if count >= settings.login_max_failures:
                self._names[name] = (0, now + timedelta(minutes=settings.login_lockout_minutes))
                return True
            self._names[name] = (count, locked_until)
            return False


throttle = _Throttle()


def authenticate(raw_username: str, password: str, ip: str | None) -> User:
    """The user for a correct username + password, or raises LoginRejected. A success resets the user's counters and may upgrade the
    stored hash; every failure counts against the source and (existing or not) the name."""
    now = utcnow()
    source = ip or "unknown"
    name = normalize_username(raw_username)[:MAX_USERNAME_LENGTH]

    retry = throttle.source_retry_after(source, now)
    if retry is not None:
        dummy_verify(password)
        raise LoginRejected(429, TOO_MANY_DETAIL, "login_blocked", retry)

    with Session(engine) as session:
        user = _user(session, name) if name else None
        if user is None:
            dummy_verify(password)
            retry = throttle.name_retry_after(name, now)
            if retry is not None:
                throttle.record_source_failure(source, now)
                raise LoginRejected(429, TOO_MANY_DETAIL, "login_blocked", retry)
            throttle.record_source_failure(source, now)
            locked = throttle.record_name_failure(name, now)
            raise LoginRejected(401, INVALID_DETAIL, "lockout" if locked else "login_fail")

        if user.locked_until is not None and user.locked_until > now:
            dummy_verify(password)
            throttle.record_source_failure(source, now)
            raise LoginRejected(
                429, TOO_MANY_DETAIL, "login_blocked", max(1, int((user.locked_until - now).total_seconds())), username=user.username
            )

        if not user.is_active:
            dummy_verify(password)
            throttle.record_source_failure(source, now)
            raise LoginRejected(401, INVALID_DETAIL, "login_fail", username=user.username)

        if verify_password(password, user.password_hash):
            user.failed_logins = 0
            user.locked_until = None
            user.last_login_at = now
            if needs_rehash(user.password_hash):
                user.password_hash = hash_password(password)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

        throttle.record_source_failure(source, now)
        # An atomic increment (two simultaneous wrong guesses both count), then the lockout check on the stored value.
        session.execute(update(User).where(User.id == user.id).values(failed_logins=User.failed_logins + 1))
        failed = session.exec(select(User.failed_logins).where(User.id == user.id)).one()
        locked = failed >= settings.login_max_failures
        if locked:
            session.execute(
                update(User)
                .where(User.id == user.id)
                .values(failed_logins=0, locked_until=now + timedelta(minutes=settings.login_lockout_minutes))
            )
        session.commit()
        raise LoginRejected(401, INVALID_DETAIL, "lockout" if locked else "login_fail", username=user.username)


# --- request authorization --------------------------------------------------------------------------------------

PRINCIPAL_SCOPE_KEY = "fathom.principal"


def session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def current_principal(request: Request) -> Principal | None:
    """The principal `authorize` attached to this request (None on a public route)."""
    return request.scope.get(PRINCIPAL_SCOPE_KEY)


def is_restricted(principal: Principal | None) -> bool:
    """True for anyone who is not a signed-in admin: no live fetch, no write, tracked tickers only. A missing principal counts as
    restricted, so a route that somehow skipped `authorize` fails closed."""
    return principal is None or not principal.is_admin


def authorize(request: Request) -> Principal | None:
    """The app-level dependency: every route needs a valid session unless core/route_roles.py declares it "public", and an "admin"
    route needs an admin (403 for a viewer). A route missing from the registry is treated as admin-only (the registry test also
    fails). Runs after the Host/Origin guard middleware."""
    route = request.scope.get("route")
    role = role_for(request.method, getattr(route, "path", None))
    if role == "public":
        return None
    principal = resolve_session(session_token(request))
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    request.scope[PRINCIPAL_SCOPE_KEY] = principal  # before the role check, so the audit row of a 403 still names who tried
    if role != "viewer" and not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return principal
