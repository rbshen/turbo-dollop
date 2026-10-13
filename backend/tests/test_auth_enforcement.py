"""Item 3 of the auth work: the app-level dependency (401 / 403), its order against the request guard, and the audit middleware."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

import core.auth as auth
import core.main as main
from core.models import AuditLog
from core.route_roles import ROUTE_ROLES

PATH_VALUES = {"{ticker}": "AAPL", "{watchlist_id}": "1", "{as_of_date}": "2026-01-02", "{name}": "view", "{group}": "fmp"}


def concrete(path: str) -> str:
    for key, value in PATH_VALUES.items():
        path = path.replace(key, value)
    return path


def call(client, method: str, path: str):
    return client.request(method, concrete(path), json={} if method in ("POST", "PUT", "PATCH") else None)


@pytest.fixture()
def app_db(monkeypatch):
    """The app's own database for a test that makes a real write (conftest's guard refuses the real file)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def audit_rows():
    with Session(auth.engine) as s:
        return s.exec(select(AuditLog).order_by(AuditLog.id)).all()


NON_PUBLIC = sorted(k for k, role in ROUTE_ROLES.items() if role != "public")
ADMIN_ONLY = sorted(k for k, role in ROUTE_ROLES.items() if role == "admin")


# ---- 401 / 403 ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", NON_PUBLIC)
def test_every_non_public_route_answers_401_without_a_session(client_for, method, path):
    response = call(client_for("anonymous"), method, path)
    assert response.status_code == 401 and response.json() == {"detail": "Not authenticated"}


@pytest.mark.parametrize("method,path", ADMIN_ONLY)
def test_every_admin_route_answers_403_to_a_viewer(client_for, method, path):
    response = call(client_for("viewer"), method, path)
    assert response.status_code == 403 and response.json() == {"detail": "Admin access required"}


def test_health_and_login_are_reachable_without_a_session(client_for):
    anonymous = client_for("anonymous")
    assert anonymous.get("/api/health").json() == {"status": "ok"}
    assert anonymous.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 401  # reached the handler
    assert anonymous.post("/api/health").status_code == 405  # health stays GET-only


def test_a_viewer_may_read_and_use_the_pure_calculation(client_for):
    viewer = client_for("viewer")
    assert viewer.get("/api/auth/me").json()["role"] == "viewer"
    assert viewer.get("/api/screener/meta").status_code == 200
    assert viewer.get("/api/config/moat").status_code == 200
    body = {"method": "dcf", "current_value": 1.0, "growth_yr_1_5": 5, "growth_yr_6_10": 4, "growth_yr_11_20": 3, "discount_rate": 9,
            "shares_outstanding": 1.0, "total_debt": 0.0, "cash_and_st_investments": 0.0, "last_close": 10.0}
    assert viewer.post("/api/tickers/AAPL/step3/manual", json=body).status_code != 403


def test_an_admin_passes_the_dependency_on_admin_routes(client_for):
    assert client_for("admin").get("/api/config/cron-health").status_code == 200


def test_a_bad_cookie_is_401_and_not_a_server_error(client_for):
    client = client_for("anonymous")
    client.cookies.set(auth.COOKIE_NAME, "x" * 500)
    assert client.get("/api/screener/meta").status_code == 401


def test_a_disabled_user_loses_access_at_once(client_for):
    viewer = client_for("viewer")
    assert viewer.get("/api/screener/meta").status_code == 200
    with Session(auth.engine) as s:
        auth.set_active(s, "test-viewer", False)
    assert viewer.get("/api/screener/meta").status_code == 401


def test_authentication_comes_before_validation_and_lookup(client_for):
    anonymous = client_for("anonymous")
    assert anonymous.get("/api/tickers/NOT A TICKER/summary").status_code == 401  # not 422
    assert anonymous.get("/api/watchlists/999/rows").status_code == 401  # not 404
    assert anonymous.get("/api/opportunities/not-a-date").status_code == 401  # not 422


# ---- order against the request guard ------------------------------------------------------------------------------------


def test_the_host_check_runs_before_authentication(client_for):
    from starlette.testclient import TestClient

    rebinding = TestClient(main.app, base_url="http://evil.example:8002", cookies={})
    assert rebinding.get("/api/screener/meta").status_code == 400  # not 401


def test_the_cross_site_check_runs_before_authentication(client_for):
    anonymous = client_for("anonymous")
    response = anonymous.put("/api/config/moat", json={}, headers={"Origin": "http://evil.example"})
    assert response.status_code == 403 and "Cross-site" in response.json()["detail"]
    no_header = anonymous.put("/api/config/moat", json={}, headers={"X-Fathom-Request": ""})
    assert no_header.status_code == 403 and "X-Fathom-Request" in no_header.json()["detail"]


# ---- audit --------------------------------------------------------------------------------------------------------------


def test_non_get_requests_are_audited_with_who_what_and_outcome(client_for, app_db):
    secret = "a-secret-value-in-a-body"
    admin, viewer, anonymous = client_for("admin"), client_for("viewer"), client_for("anonymous")
    admin.get("/api/screener/meta")  # a read: not audited
    admin.put("/api/config/reit-dividend-yield?token=in-the-query", json={"threshold_pct": 4.5, "note": secret})
    viewer.put("/api/config/moat", json={"narrow_moat_multiplier": 0.9})
    anonymous.delete("/api/screener/filters/x")
    rows = audit_rows()
    assert [(r.event, r.method, r.path, r.status, r.username) for r in rows] == [
        ("request", "PUT", "/api/config/reit-dividend-yield", 200, "test-admin"),
        ("request", "PUT", "/api/config/moat", 403, "test-viewer"),
        ("request", "DELETE", "/api/screener/filters/x", 401, None),
    ]
    assert rows[0].user_id is not None and rows[2].user_id is None
    blob = " ".join(str(v) for r in rows for v in r.model_dump().values())
    assert secret not in blob and "in-the-query" not in blob and "scrypt" not in blob


def test_a_request_the_guard_refuses_is_audited_too(client_for):
    client_for("anonymous").put("/api/config/moat", json={}, headers={"Origin": "http://evil.example"})
    (row,) = audit_rows()
    assert (row.event, row.status, row.username) == ("request", 403, None)


def test_login_and_logout_are_not_double_audited(client_for):
    anonymous = client_for("anonymous")
    anonymous.post("/api/auth/login", json={"username": "x", "password": "y"})
    assert [r.event for r in audit_rows()] == ["login_fail"]


def test_a_failing_audit_write_never_changes_the_response(client_for, app_db, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("core.audit.Session", boom)
    admin = client_for("admin")
    assert admin.put("/api/config/reit-dividend-yield", json={"threshold_pct": 4.5}).status_code == 200
