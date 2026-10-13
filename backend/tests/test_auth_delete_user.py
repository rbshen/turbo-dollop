"""`core.auth_cli delete-user`: removes the account and its sessions in one transaction, keeps audit rows, refuses the last active admin.
In-memory auth database per test (conftest)."""

import io

import pytest
from sqlmodel import Session, select

import core.auth as auth
import core.auth_cli as cli
from core.models import AuditLog, User, UserSession

PW = "correct horse battery"


def _stdin(monkeypatch, text):
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(text))


def _make(name, role="admin"):
    with Session(auth.engine) as s:
        user = auth.create_user(s, name, PW, role)
        token, _ = auth.create_session(s, user, "127.0.0.1", "pytest")
        auth.create_session(s, user, "127.0.0.1", "pytest")
        return user.id, token


def _rows(model):
    with Session(auth.engine) as s:
        return s.exec(select(model)).all()


def _seed_audit(user_id, name):
    with Session(auth.engine) as s:
        s.add(AuditLog(ts=auth.utcnow(), user_id=user_id, username=name, method="PUT", path="/api/x", status=200, event="request"))
        s.commit()


def test_delete_removes_user_and_sessions_keeps_audit_and_adds_a_deletion_row(capsys):
    _make("root")
    bob_id, _ = _make("bob", "viewer")
    other_id, _ = _make("carol", "viewer")
    _seed_audit(bob_id, "bob")
    before = {r.id for r in _rows(AuditLog)}

    assert cli.main(["delete-user", "Bob", "--yes"]) == 0
    assert "2 session(s) ended" in capsys.readouterr().out

    assert [u.username for u in _rows(User)] == ["root", "carol"]
    assert {r.user_id for r in _rows(UserSession)} == {_rows(User)[0].id, other_id}  # bob's sessions gone, others untouched
    audit = _rows(AuditLog)
    assert before <= {r.id for r in audit}  # old rows kept
    assert any(r.username == "bob" and r.event == "request" for r in audit)
    deleted = [r for r in audit if r.event == "user_deleted"]
    assert len(deleted) == 1 and deleted[0].username == "bob" and deleted[0].user_id == bob_id
    assert deleted[0].method == "CLI" and deleted[0].ip is None
    assert "scrypt" not in repr(deleted[0]) and PW not in repr(deleted[0])


def test_deleting_a_viewer_works_even_with_one_admin(capsys):
    _make("root")
    _make("vic", "viewer")
    assert cli.main(["delete-user", "vic", "--yes"]) == 0
    assert [u.username for u in _rows(User)] == ["root"]


def test_refuses_the_last_active_admin_and_changes_nothing(capsys):
    root_id, _ = _make("root")
    _make("vic", "viewer")
    assert cli.main(["delete-user", "root", "--yes"]) == 1
    assert "last active admin" in capsys.readouterr().err
    assert len(_rows(User)) == 2 and len(_rows(UserSession)) == 4
    assert not [r for r in _rows(AuditLog) if r.event == "user_deleted"]


def test_a_disabled_admin_does_not_count_as_the_last_active_admin(capsys):
    _make("root")
    _make("old", "admin")
    with Session(auth.engine) as s:
        auth.set_active(s, "root", False)
    assert cli.main(["delete-user", "root", "--yes"]) == 0  # 'old' remains active
    assert cli.main(["delete-user", "old", "--yes"]) == 1  # now 'old' is the last active admin


def test_deleting_an_admin_is_allowed_when_another_active_admin_exists():
    _make("a")
    _make("b")
    assert cli.main(["delete-user", "a", "--yes"]) == 0
    assert [u.username for u in _rows(User)] == ["b"]


def test_unknown_user_exits_nonzero_with_a_message(capsys):
    _make("root")
    assert cli.main(["delete-user", "ghost", "--yes"]) == 1
    assert "No user named 'ghost'" in capsys.readouterr().err
    assert cli.main(["delete-user", "ghost"]) == 1  # also without --yes, before any prompt


def test_confirmation_is_required_without_yes(monkeypatch, capsys):
    _make("root")
    _make("vic", "viewer")
    _stdin(monkeypatch, "")
    assert cli.main(["delete-user", "vic"]) == 1
    _stdin(monkeypatch, "someone-else\n")
    assert cli.main(["delete-user", "vic"]) == 1
    assert "nothing was deleted" in capsys.readouterr().err
    assert len(_rows(User)) == 2
    _stdin(monkeypatch, "vic\n")
    assert cli.main(["delete-user", "vic"]) == 0
    assert [u.username for u in _rows(User)] == ["root"]


def test_username_is_reusable_and_the_new_account_is_a_new_user_with_no_old_sessions():
    _make("root")
    old_id, old_token = _make("vic", "viewer")
    assert cli.main(["delete-user", "vic", "--yes"]) == 0  # vic held the highest id: the case SQLite would reuse
    with Session(auth.engine) as s:
        new = auth.create_user(s, "vic", PW, "viewer")
        assert new.id != old_id and new.id > old_id
        assert s.exec(select(UserSession).where(UserSession.user_id == new.id)).all() == []
    assert auth.resolve_session(old_token) is None  # the old cookie does not become the new account's session


def test_a_deleted_users_session_token_no_longer_authenticates():
    _make("root")
    _, token = _make("vic", "viewer")
    assert auth.resolve_session(token) is not None
    assert cli.main(["delete-user", "vic", "--yes"]) == 0
    assert auth.resolve_session(token) is None


def test_deletion_is_one_transaction(monkeypatch):
    _make("root")
    _make("vic", "viewer")
    real_add = Session.add

    def boom(self, obj, *a, **k):
        if isinstance(obj, AuditLog) and obj.event == "user_deleted":
            raise RuntimeError("audit write failed")
        return real_add(self, obj, *a, **k)

    with monkeypatch.context() as m:  # scoped: a bare undo() would also drop the conftest engine isolation
        m.setattr(Session, "add", boom)
        with pytest.raises(RuntimeError), Session(auth.engine) as s:
            auth.delete_user(s, "vic")
    assert [u.username for u in _rows(User)] == ["root", "vic"]
    assert len(_rows(UserSession)) == 4  # sessions came back with the rollback


def test_help_lists_the_command(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "delete-user" in capsys.readouterr().out
