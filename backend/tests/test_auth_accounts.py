"""Item 1 of the auth work: password hashing, the account functions, and the CLI. In-memory auth database per test (conftest)."""

import io
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

import core.auth as auth
import core.auth_cli as cli
import core.passwords as passwords
from core.models import User, UserSession

PW = "correct horse battery"


def _session():
    return Session(auth.engine)


# ---- passwords ----------------------------------------------------------------------------------------------------


def test_hash_has_a_scheme_parameters_and_a_random_salt_and_verifies():
    a, b = passwords.hash_password(PW), passwords.hash_password(PW)
    assert a != b  # per-password salt
    scheme, n, r, p, salt, key = a.split("$")
    assert (scheme, int(n), int(r), int(p)) == ("scrypt", passwords.SCRYPT_N, passwords.SCRYPT_R, passwords.SCRYPT_P)
    assert PW not in a
    assert passwords.verify_password(PW, a) and passwords.verify_password(PW, b)
    assert not passwords.verify_password(PW + "x", a)


def test_verify_never_raises_on_a_corrupt_hash():
    for bad in (None, "", "plain", "scrypt$x$1$1$a$b", "scrypt$16$1$1$!!$!!", "md5$1$2$3$4$5", "scrypt$3$1$1$aa$bb", f"scrypt${2**30}$8$1$aa$bb"):
        assert passwords.verify_password(PW, bad) is False


def test_parameters_in_the_string_win_over_the_current_ones_and_a_weaker_hash_asks_for_a_rehash(monkeypatch):
    old = passwords.hash_password(PW)  # made with the (cheap) test parameters
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**5)
    assert passwords.verify_password(PW, old)
    assert passwords.needs_rehash(old)
    assert not passwords.needs_rehash(passwords.hash_password(PW))


def test_default_parameters_are_the_strong_ones():
    import importlib

    fresh = importlib.reload(passwords)  # the conftest patch is on the old module attributes; a reload shows the shipped values
    try:
        assert (fresh.SCRYPT_N, fresh.SCRYPT_R, fresh.SCRYPT_P) == (2**15, 8, 1)
        assert fresh.MIN_PASSWORD_LENGTH == 12
    finally:
        importlib.reload(passwords)


def test_password_policy():
    passwords.validate_password_policy("x" * 12)
    with pytest.raises(passwords.WeakPasswordError):
        passwords.validate_password_policy("x" * 11)
    with pytest.raises(passwords.WeakPasswordError):
        passwords.validate_password_policy("x" * 257)


# ---- accounts -----------------------------------------------------------------------------------------------------


def test_create_user_normalizes_the_name_and_rejects_a_case_variant():
    with _session() as s:
        user = auth.create_user(s, "  Alice ", PW, "admin")
        assert (user.username, user.role, user.is_active, user.failed_logins, user.locked_until) == ("alice", "admin", True, 0, None)
        assert user.password_hash.startswith("scrypt$") and PW not in user.password_hash
        with pytest.raises(ValueError, match="already exists"):
            auth.create_user(s, "ALICE", PW, "viewer")


def test_the_database_itself_rejects_a_duplicate_username():
    with _session() as s:
        auth.create_user(s, "alice", PW, "viewer")
        s.add(User(username="alice", password_hash="x", role="viewer", created_at=auth.utcnow()))
        with pytest.raises(IntegrityError):
            s.commit()


@pytest.mark.parametrize("name", ["", " ", "a b", "-lead", "x" * 65, "al/ice", "ünï"])
def test_bad_usernames_are_refused(name):
    with _session() as s, pytest.raises(ValueError):
        auth.create_user(s, name, PW, "viewer")


def test_bad_role_and_short_password_are_refused():
    with _session() as s:
        with pytest.raises(ValueError, match="role"):
            auth.create_user(s, "bob", PW, "owner")
        with pytest.raises(ValueError, match="at least 12"):
            auth.create_user(s, "bob", "short", "viewer")
        assert s.exec(select(User)).all() == []


def _with_session(s, user):
    return auth.create_session(s, user, "127.0.0.1", "pytest")[0]


def test_disable_and_set_password_delete_that_users_sessions_and_only_theirs():
    with _session() as s:
        a, b = auth.create_user(s, "alice", PW, "admin"), auth.create_user(s, "bob", PW, "viewer")
        _with_session(s, a), _with_session(s, a), _with_session(s, b)
        a.failed_logins, a.locked_until = 3, auth.utcnow() + timedelta(minutes=5)
        s.add(a)
        s.commit()

        assert auth.set_password(s, "alice", "another long password") == 2
        s.refresh(a)
        assert (a.failed_logins, a.locked_until) == (0, None)  # a new password clears the throttle
        assert passwords.verify_password("another long password", a.password_hash)
        assert [r.user_id for r in s.exec(select(UserSession)).all()] == [b.id]

        _with_session(s, a)
        assert auth.set_active(s, "alice", False) == 1
        assert [r.user_id for r in s.exec(select(UserSession)).all()] == [b.id]
        assert auth.set_active(s, "alice", True) == 0
        assert auth.revoke_sessions(s) == 1 and s.exec(select(UserSession)).all() == []


def test_unknown_user_is_a_lookup_error():
    with _session() as s, pytest.raises(LookupError):
        auth.set_active(s, "ghost", False)


# ---- CLI ----------------------------------------------------------------------------------------------------------


def _stdin(monkeypatch, text):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(text))  # StringIO.isatty() is False: the piped-password path


def test_cli_create_list_disable_enable_revoke(monkeypatch, capsys):
    _stdin(monkeypatch, PW + "\n")
    assert cli.main(["create-user", "Alice", "--role", "admin"]) == 0
    _stdin(monkeypatch, PW + "\n")
    assert cli.main(["create-user", "bob", "--role", "viewer"]) == 0
    with _session() as s:
        _with_session(s, auth.get_user(s, "bob"))
    capsys.readouterr()

    assert cli.main(["list"]) == 0
    listing = capsys.readouterr().out
    assert "alice" in listing and "admin" in listing and "bob" in listing and "viewer" in listing
    assert "scrypt" not in listing and PW not in listing  # no hash, no password

    assert cli.main(["disable", "bob"]) == 0
    assert "1 session(s) ended" in capsys.readouterr().out
    with _session() as s:
        assert auth.get_user(s, "bob").is_active is False
    assert cli.main(["enable", "bob"]) == 0
    assert cli.main(["revoke-sessions", "bob"]) == 0 and cli.main(["revoke-sessions"]) == 0


def test_cli_set_password_reads_stdin_and_the_password_is_never_in_argv_or_output(monkeypatch, capsys):
    _stdin(monkeypatch, PW + "\n")
    cli.main(["create-user", "alice", "--role", "admin"])
    _stdin(monkeypatch, "a second long password\n")
    assert cli.main(["set-password", "alice"]) == 0
    out = capsys.readouterr()
    assert "second long" not in out.out + out.err
    with _session() as s:
        assert passwords.verify_password("a second long password", auth.get_user(s, "alice").password_hash)


def test_cli_errors_exit_nonzero_with_a_message(monkeypatch, capsys):
    _stdin(monkeypatch, "short\n")
    assert cli.main(["create-user", "alice", "--role", "admin"]) == 1
    assert "at least 12" in capsys.readouterr().err
    assert cli.main(["disable", "ghost"]) == 1
    _stdin(monkeypatch, "")
    assert cli.main(["create-user", "alice", "--role", "admin"]) == 1  # nothing on stdin
    with pytest.raises(SystemExit):
        cli.main(["create-user", "alice", "--role", "root"])  # argparse rejects the role


def test_cli_has_no_password_argument():
    parser = cli.build_parser()
    for sub in parser._subparsers._group_actions[0].choices.values():
        assert not any("password" in "".join(a.option_strings) for a in sub._actions)


def test_cli_creates_the_tables_when_they_are_missing(monkeypatch):
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.pool import StaticPool

    bare = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(auth, "engine", bare)
    _stdin(monkeypatch, PW + "\n")
    assert cli.main(["create-user", "alice", "--role", "admin"]) == 0
    assert {"user", "usersession", "auditlog"} <= set(inspect(bare).get_table_names())
