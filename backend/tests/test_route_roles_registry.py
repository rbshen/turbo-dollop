"""Every route of the app declares its role in core/route_roles.py -- modelled on test_data_groups_registry.py. A new route that is not
registered, a write registered as viewer, or a {ticker} route without the ticker guard fails here, before it can ship open."""

import pytest
from fastapi.routing import APIRoute

import core.main as main
from core.main import _validated_ticker_path
from core.route_roles import ROUTE_ROLES, VIEWER_ALLOWED_WRITES, WRITE_METHODS, role_for


def _routes():
    return [(method, route.path, route) for route in main.app.routes if isinstance(route, APIRoute) for method in sorted(route.methods)]


def _dependency_calls(dependant):
    seen = set()
    stack = [dependant]
    while stack:
        node = stack.pop()
        for sub in node.dependencies:
            if sub.call not in seen:
                seen.add(sub.call)
                stack.append(sub)
    return seen


def test_the_app_has_only_api_routes_and_they_are_found():
    assert len(_routes()) > 80  # the scan itself works
    assert all(isinstance(r, APIRoute) for r in main.app.routes), "a non-APIRoute (mount, static, websocket) bypasses the dependency"


def test_every_route_declares_a_role():
    missing = sorted((m, p) for m, p, _ in _routes() if (m, p) not in ROUTE_ROLES)
    assert not missing, f"add these to core/route_roles.ROUTE_ROLES: {missing}"


def test_no_stale_registry_entries():
    live = {(m, p) for m, p, _ in _routes()}
    assert sorted(set(ROUTE_ROLES) - live) == []


def test_roles_are_valid_and_only_health_and_login_are_public():
    assert set(ROUTE_ROLES.values()) <= {"public", "viewer", "admin"}
    assert {k for k, v in ROUTE_ROLES.items() if v == "public"} == {("GET", "/api/health"), ("POST", "/api/auth/login")}


def test_health_is_get_only():
    assert [m for m, p, _ in _routes() if p == "/api/health"] == ["GET"]


def test_a_write_method_is_never_registered_as_viewer_unless_listed():
    offenders = [k for k, role in ROUTE_ROLES.items() if k[0] in WRITE_METHODS and role == "viewer" and k not in VIEWER_ALLOWED_WRITES]
    assert not offenders, offenders
    assert VIEWER_ALLOWED_WRITES <= set(ROUTE_ROLES)
    assert all(ROUTE_ROLES[k] == "viewer" for k in VIEWER_ALLOWED_WRITES)


# Config reads only the Settings page uses (a viewer cannot open Settings). moat and score-weights are NOT here: ticker pages and the Screener read them.
SETTINGS_ONLY_READS = [
    ("GET", f"/api/config/{n}") for n in ("discount-rate", "discount-rates", "liquidity-zones", "reit-dividend-yield", "weinstein")
]


def test_shared_config_reads_stay_open_to_a_viewer():
    for n in ("moat", "score-weights"):
        assert ROUTE_ROLES[("GET", f"/api/config/{n}")] == "viewer", n


def test_operational_detail_and_spend_reads_are_admin_only():
    for key in (
        ("GET", "/api/config/cron-health"),
        ("GET", "/api/config/data-source-health"),
        ("GET", "/api/config/data-groups"),
        *SETTINGS_ONLY_READS,
        ("GET", "/api/tickers/{ticker}/financials/cash-flow-cell-check"),
    ):
        assert ROUTE_ROLES[key] == "admin", key


def test_an_unregistered_route_is_treated_as_admin_only():
    assert role_for("GET", "/api/brand-new") == "admin"
    assert role_for("get", "/api/health") == "public"


@pytest.mark.parametrize("method,path,route", _routes(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_route_runs_the_authorize_dependency(method, path, route):
    assert main.authorize in _dependency_calls(route.dependant)


def test_every_ticker_route_carries_the_ticker_guard():
    """The {ticker} path parameter must go through core/main.py::TickerPath: it validates the symbol and, for a viewer, answers 404 for
    anything outside the tracked universe. A new {ticker} route with a plain `ticker: str` would skip both."""
    offenders = [
        (m, p) for m, p, route in _routes() if "{ticker}" in p and _validated_ticker_path not in _dependency_calls(route.dependant)
    ]
    assert not offenders, offenders
