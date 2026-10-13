"""Item 2 of the auth work: sessions, the cookie, the three endpoints, the login throttle, expiry and the audit rows for them."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import core.auth as auth
import core.main as main
from core.config import settings
from core.models import AuditLog, User, UserSession

PW = "correct horse battery"

pytestmark = pytest.mark.auth("anonymous")  # these tests start from an empty auth database and sign in themselves


@pytest.fixture()
def client():
    return TestClient(main.app)


@pytest.fixture()
def clock(monkeypatch):
    """A movable clock for auth.utcnow."""

    class Clock:
        now = auth.utcnow()

        def advance(self, **kw):
            self.now += timedelta(**kw)

    c = Clock()
    monkeypatch.setattr(auth, "utcnow", lambda: c.now)
    return c


def make_user(name="alice", role="admin", password=PW, active=True):
    with Session(auth.engine) as s:
        user = auth.create_user(s, name, password, role)
        if not active:
            auth.set_active(s, name, False)
        return user.id


def login(client, name="alice", password=PW):
    return client.post("/api/auth/login", json={"username": name, "password": password})


def rows(model):
    with Session(auth.engine) as s:
        return s.exec(select(model)).all()


# ---- login, cookie, me, logout ---------------------------------------------------------------------------------------


def test_login_sets_an_httponly_lax_cookie_and_me_answers_with_username_and_role_only(client):
    make_user("Alice", "admin")
    response = login(client, " ALICE ")
    assert response.status_code == 200 and response.json() == {"username": "alice", "role": "admin"}
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{auth.COOKIE_NAME}=")
    low = cookie.lower()
    assert "httponly" in low and "samesite=lax" in low and "path=/" in low
    assert "secure" not in low.replace("samesite", "")  # default: no Secure (plain http://localhost)
    assert f"max-age={30 * 86400}" in low
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json() == {"username": "alice", "role": "admin"}


def test_secure_flag_follows_the_env_setting(client, monkeypatch):
    make_user()
    monkeypatch.setattr(settings, "session_cookie_secure", True)
    assert "secure" in login(client).headers["set-cookie"].lower().replace("samesite", "")


def test_only_a_hash_of_the_token_is_stored(client):
    make_user()
    token = login(client).cookies[auth.COOKIE_NAME]
    assert len(token) >= 43  # token_urlsafe(32)
    (row,) = rows(UserSession)
    assert row.token_hash == auth.hash_token(token) and token not in (row.token_hash, row.user_agent or "", row.ip or "")


def test_login_errors_are_generic_and_identical_for_wrong_password_unknown_and_inactive_users(client):
    make_user("alice")
    make_user("dora", active=False)
    bad = [login(client, "alice", "wrong password!!"), login(client, "nobody", PW), login(client, "dora", PW)]
    assert {(r.status_code, r.text) for r in bad} == {(401, '{"detail":"Invalid credentials"}')}
    assert all("set-cookie" not in r.headers for r in bad)
    assert rows(UserSession) == []


def test_an_unknown_user_still_pays_for_a_password_check(client, monkeypatch):
    spent = []
    monkeypatch.setattr(auth, "dummy_verify", lambda password: spent.append(password))
    login(client, "nobody", "whatever")
    assert spent == ["whatever"]


def test_logout_deletes_the_session_clears_the_cookie_and_ends_access(client):
    make_user()
    login(client)
    response = client.post("/api/auth/logout")
    assert response.status_code == 204
    assert f'{auth.COOKIE_NAME}=""' in response.headers["set-cookie"] or "max-age=0" in response.headers["set-cookie"].lower()
    assert rows(UserSession) == []
    assert client.get("/api/auth/me").status_code == 401


def test_me_and_logout_need_a_session(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/logout").status_code == 401
    client.cookies.set(auth.COOKIE_NAME, "not-a-real-token")
    assert client.get("/api/auth/me").status_code == 401


def test_the_token_rotates_on_login_and_the_old_session_dies(client):
    make_user()
    first = login(client).cookies[auth.COOKIE_NAME]
    second = login(client).cookies[auth.COOKIE_NAME]  # the client still sends `first` with this login
    assert first != second
    (row,) = rows(UserSession)
    assert row.token_hash == auth.hash_token(second)
    client.cookies.set(auth.COOKIE_NAME, first)
    assert client.get("/api/auth/me").status_code == 401


def test_login_validates_its_body(client):
    assert client.post("/api/auth/login", json={"username": "a" * 65, "password": "x"}).status_code == 422
    assert client.post("/api/auth/login", json={"username": "a"}).status_code == 422


# ---- expiry ----------------------------------------------------------------------------------------------------------


def test_idle_timeout_ends_a_session_and_use_within_it_extends_it(client, clock):
    make_user()
    login(client)
    for _ in range(3):  # 3 x 5 days: each gap is inside the 7-day idle window, so the session survives 15 days
        clock.advance(days=5)
        assert client.get("/api/auth/me").status_code == 200
    clock.advance(days=7, minutes=1)
    assert client.get("/api/auth/me").status_code == 401
    assert rows(UserSession) == []  # and the dead row is dropped


def test_absolute_lifetime_ends_a_session_that_is_used_all_the_time(client, clock):
    make_user()
    login(client)
    for _ in range(5):  # 25 days of daily-ish use
        clock.advance(days=5)
        assert client.get("/api/auth/me").status_code == 200
    clock.advance(days=5, minutes=1)  # day 30 and a bit
    assert client.get("/api/auth/me").status_code == 401


def test_timeouts_are_configurable(client, clock, monkeypatch):
    monkeypatch.setattr(settings, "session_idle_days", 1)
    monkeypatch.setattr(settings, "session_absolute_days", 2)
    make_user()
    login(client)
    clock.advance(hours=25)
    assert client.get("/api/auth/me").status_code == 401


def test_last_seen_is_written_at_most_once_per_touch_interval(client, clock):
    make_user()
    login(client)
    (before,) = rows(UserSession)
    clock.advance(seconds=auth.SESSION_TOUCH_SECONDS - 10)
    client.get("/api/auth/me")
    assert rows(UserSession)[0].last_seen_at == before.last_seen_at  # read-first: no write
    clock.advance(seconds=20)
    client.get("/api/auth/me")
    assert rows(UserSession)[0].last_seen_at == clock.now


def test_disabling_or_changing_the_password_ends_the_session_over_http(client):
    make_user()
    login(client)
    with Session(auth.engine) as s:
        auth.set_password(s, "alice", "a brand new password")
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, password="a brand new password").status_code == 200
    with Session(auth.engine) as s:
        auth.set_active(s, "alice", False)
    assert client.get("/api/auth/me").status_code == 401
    assert login(client, password="a brand new password").status_code == 401


def test_a_session_whose_user_was_disabled_without_deleting_sessions_is_still_refused(client):
    make_user()
    login(client)
    with Session(auth.engine) as s:  # foreign keys are off and a hand edit may skip the delete: the lookup checks is_active too
        user = s.exec(select(User)).one()
        user.is_active = False
        s.add(user)
        s.commit()
    assert client.get("/api/auth/me").status_code == 401


# ---- throttle --------------------------------------------------------------------------------------------------------


def test_lockout_after_max_failures_blocks_even_the_right_password_then_expires(client, clock):
    make_user()
    for _ in range(settings.login_max_failures - 1):
        assert login(client, password="wrong password!!").status_code == 401
    assert login(client, password="wrong password!!").status_code == 401  # the failure that triggers the lock is still the generic 401
    blocked = login(client)  # correct password, but locked
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    assert 0 < int(blocked.headers["Retry-After"]) <= settings.login_lockout_minutes * 60
    with Session(auth.engine) as s:
        assert s.exec(select(User)).one().locked_until is not None
    clock.advance(minutes=settings.login_lockout_minutes, seconds=1)
    assert login(client).status_code == 200  # temporary, and a success resets the counters
    with Session(auth.engine) as s:
        user = s.exec(select(User)).one()
        assert (user.failed_logins, user.locked_until) == (0, None) and user.last_login_at == clock.now


def test_a_success_resets_the_failure_count(client):
    make_user()
    for _ in range(settings.login_max_failures - 1):
        login(client, password="wrong password!!")
    assert login(client).status_code == 200
    for _ in range(settings.login_max_failures - 1):
        assert login(client, password="wrong password!!").status_code == 401  # would have been locked without the reset
    assert login(client).status_code == 200


def test_lockout_length_is_configurable_and_set_password_clears_it(client, clock, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 2)
    monkeypatch.setattr(settings, "login_lockout_minutes", 1)
    make_user()
    login(client, password="wrong password!!"), login(client, password="wrong password!!")
    assert login(client).status_code == 429
    clock.advance(seconds=61)
    assert login(client).status_code == 200
    login(client, password="wrong password!!"), login(client, password="wrong password!!")
    assert login(client).status_code == 429
    with Session(auth.engine) as s:
        auth.set_password(s, "alice", PW)
    assert login(client).status_code == 200


def test_an_unknown_name_is_throttled_the_same_way_so_lockouts_do_not_reveal_accounts(client):
    make_user("alice")
    for name in ("alice", "nobody"):
        statuses = [login(client, name, "wrong password!!").status_code for _ in range(settings.login_max_failures + 1)]
        assert statuses == [401] * settings.login_max_failures + [429]


def test_per_source_throttle_blocks_a_spray_across_usernames_and_frees_with_time(client, clock, monkeypatch):
    monkeypatch.setattr(settings, "login_source_max_failures", 6)
    make_user("alice")
    for i in range(6):
        assert login(client, f"user{i}", "wrong password!!").status_code == 401
    assert login(client, "alice").status_code == 429  # even a correct login from the flooded source
    clock.advance(minutes=settings.login_source_window_minutes, seconds=1)
    assert login(client, "alice").status_code == 200


# ---- audit -----------------------------------------------------------------------------------------------------------


def test_login_events_are_audited_without_secrets(client):
    make_user("alice")
    login(client, "alice", "wrong password!!")
    login(client, "ghost", "my-secret-typed-in-the-wrong-box")
    token = login(client).cookies[auth.COOKIE_NAME]
    client.post("/api/auth/logout")
    log = rows(AuditLog)
    assert [(r.event, r.status, r.username) for r in log] == [
        ("login_fail", 401, "alice"),
        ("login_fail", 401, None),  # an unknown name may be a password: never stored
        ("login_ok", 200, "alice"),
        ("logout", 204, "alice"),
    ]
    blob = " ".join(str(v) for r in log for v in r.model_dump().values())
    for secret in (PW, "wrong password!!", "my-secret-typed-in-the-wrong-box", token, auth.hash_token(token), "scrypt$"):
        assert secret not in blob
    assert all(r.method == "POST" and r.path.startswith("/api/auth/") for r in log)


def test_lockout_and_blocked_attempts_are_audited(client):
    make_user()
    for _ in range(settings.login_max_failures):
        login(client, password="wrong password!!")
    login(client)
    events = [r.event for r in rows(AuditLog)]
    assert events == ["login_fail"] * (settings.login_max_failures - 1) + ["lockout", "login_blocked"]


def test_a_failing_audit_write_never_breaks_login(client, monkeypatch):
    make_user()

    def boom(*a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr("core.audit.Session", boom)
    assert login(client).status_code == 200
