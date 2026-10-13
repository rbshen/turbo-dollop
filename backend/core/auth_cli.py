"""Account administration: the only way a login account is created or changed (there is no sign-up). Run from backend/:

    uv run python -m core.auth_cli create-user alice --role admin
    uv run python -m core.auth_cli set-password alice
    uv run python -m core.auth_cli disable alice | enable alice
    uv run python -m core.auth_cli list
    uv run python -m core.auth_cli revoke-sessions [alice]      (no name: every session)
    uv run python -m core.auth_cli prune-audit [--days N]       (delete audit rows older than N days; default AUDIT_RETENTION_DAYS, 180)

Passwords never come from the command line: an interactive prompt (typed twice) on a terminal, or one line on stdin when piped
(`printf '%s\\n' "$PW" | uv run python -m core.auth_cli create-user ...`). Nothing here prints a hash or a password. The three auth
tables are created if missing, so the first account can be made before the app has restarted on this code; init_db() never seeds a user
(cron jobs call it). Docs: docs/specs/auth.md, backend/OPS_RUNBOOK.md ("Login accounts")."""

import argparse
import getpass
import sys
from collections.abc import Sequence

from sqlmodel import Session, SQLModel, func, select

import core.auth as auth
from core.audit import prune_audit_log
from core.config import settings
from core.models import AuditLog, User, UserSession
from core.passwords import WeakPasswordError

_AUTH_TABLES = [User.__table__, UserSession.__table__, AuditLog.__table__]


def ensure_tables() -> None:
    SQLModel.metadata.create_all(auth.engine, tables=_AUTH_TABLES)


def read_password(confirm: bool = True) -> str:
    """The password from the terminal prompt (twice) or, when stdin is not a terminal, from its first line."""
    if sys.stdin.isatty():
        first = getpass.getpass("Password: ")
        if confirm and getpass.getpass("Repeat password: ") != first:
            raise ValueError("The two passwords differ.")
        return first
    line = sys.stdin.readline()
    if not line:
        raise ValueError("No password on stdin.")
    return line.rstrip("\r\n")


def _fmt(value) -> str:
    return "-" if value is None else value.strftime("%Y-%m-%d %H:%M") + "Z"


def cmd_create_user(args: argparse.Namespace) -> str:
    password = read_password()
    with Session(auth.engine) as session:
        user = auth.create_user(session, args.username, password, args.role)
        return f"Created {user.role} '{user.username}'."


def cmd_set_password(args: argparse.Namespace) -> str:
    with Session(auth.engine) as session:
        auth.get_user(session, args.username)  # fail on an unknown name before asking for a password
    password = read_password()
    with Session(auth.engine) as session:
        ended = auth.set_password(session, args.username, password)
    return f"Password changed for '{auth.normalize_username(args.username)}'; {ended} session(s) ended, login lock cleared."


def cmd_disable(args: argparse.Namespace) -> str:
    with Session(auth.engine) as session:
        ended = auth.set_active(session, args.username, False)
    return f"Disabled '{auth.normalize_username(args.username)}'; {ended} session(s) ended."


def cmd_enable(args: argparse.Namespace) -> str:
    with Session(auth.engine) as session:
        auth.set_active(session, args.username, True)
    return f"Enabled '{auth.normalize_username(args.username)}'."


def cmd_revoke_sessions(args: argparse.Namespace) -> str:
    with Session(auth.engine) as session:
        ended = auth.revoke_sessions(session, args.username)
    return f"{ended} session(s) ended for {'everyone' if args.username is None else repr(auth.normalize_username(args.username))}."


def cmd_prune_audit(args: argparse.Namespace) -> str:
    days = settings.audit_retention_days if args.days is None else args.days
    deleted = prune_audit_log(days)
    return f"Deleted {deleted} audit log row(s) older than {days} day(s). Users and sessions were not touched."


def cmd_list(_args: argparse.Namespace) -> str:
    with Session(auth.engine) as session:
        users = session.exec(select(User).order_by(User.username)).all()
        counts = dict(session.exec(select(UserSession.user_id, func.count()).group_by(UserSession.user_id)).all())
    if not users:
        return "No users."
    lines = [f"{'username':<24}{'role':<8}{'active':<8}{'sessions':<10}{'last login':<19}{'locked until':<19}created"]
    for u in users:
        lines.append(
            f"{u.username:<24}{u.role:<8}{'yes' if u.is_active else 'NO':<8}{counts.get(u.id, 0):<10}"
            f"{_fmt(u.last_login_at):<19}{_fmt(u.locked_until):<19}{_fmt(u.created_at)}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m core.auth_cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="create an account (password from the prompt or stdin)")
    create.add_argument("username")
    create.add_argument("--role", choices=auth.ROLES, required=True)
    create.set_defaults(func=cmd_create_user)
    for name, func_, help_ in (
        ("set-password", cmd_set_password, "change a password; ends the user's sessions and clears the login lock"),
        ("disable", cmd_disable, "block sign-in and end the user's sessions"),
        ("enable", cmd_enable, "allow sign-in again"),
    ):
        p = sub.add_parser(name, help=help_)
        p.add_argument("username")
        p.set_defaults(func=func_)
    revoke = sub.add_parser("revoke-sessions", help="end one user's sessions, or all of them")
    revoke.add_argument("username", nargs="?")
    revoke.set_defaults(func=cmd_revoke_sessions)
    prune = sub.add_parser("prune-audit", help="delete audit log rows older than N days (users and sessions are never touched)")
    prune.add_argument("--days", type=int, default=None, help="age in days (default: AUDIT_RETENTION_DAYS, 180); at least 1")
    prune.set_defaults(func=cmd_prune_audit)
    sub.add_parser("list", help="accounts, roles, last login, lock state").set_defaults(func=cmd_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ensure_tables()
        print(args.func(args))
    except (ValueError, LookupError, WeakPasswordError) as exc:  # WeakPasswordError is a ValueError; listed for the reader
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
