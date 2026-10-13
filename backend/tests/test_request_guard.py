"""Host and cross-site protection (core/request_guard.py): TrustedHost-style Host check plus the Origin / custom
header rule on every write. conftest gives every TestClient the legitimate frontend defaults (Host localhost:8002,
X-Fathom-Request: 1); a test drops one with an explicit `base_url=` or `headers={"X-Fathom-Request": ""}`."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import main
from core.config import settings
from core.request_guard import RequestGuardMiddleware, host_allowed, split_host_header

GOOD_ORIGIN = "http://localhost:3100"
EVIL_ORIGIN = "https://evil.example"
NO_HEADER = {"X-Fathom-Request": ""}

# The body-less write endpoints a forged cross-site HTML form could hit.
BODYLESS_WRITES = [
    ("POST", "/api/config/score-weights/reset"),
    ("POST", "/api/screener/recompute"),
    ("POST", "/api/tickers/AAPL/refresh"),
    ("POST", "/api/tickers/AAPL/universe"),
    ("DELETE", "/api/tickers/AAPL/universe"),
    ("POST", "/api/tickers/AAPL/etf-watchlist"),
    ("POST", "/api/tickers/AAPL/custom-valuation/activate"),
    ("POST", "/api/tickers/AAPL/custom-valuation/deactivate"),
    ("POST", "/api/config/data-groups/fundamentals/retest"),
]


def _mini_app() -> FastAPI:
    """A minimal app behind the same middleware, with handlers that never touch the database."""
    app = FastAPI()
    app.add_middleware(RequestGuardMiddleware)

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    @app.api_route("/write", methods=["POST", "PUT", "PATCH", "DELETE"])
    def write() -> dict:
        return {"wrote": True}

    return app


@pytest.fixture
def mini():
    with TestClient(_mini_app()) as client:
        yield client


# --- Host header --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["localhost:8002", "127.0.0.1:8002", "[::1]:8002", "localhost:3100", "127.0.0.1:3100", "[::1]:3100", "LOCALHOST:8002"],
)
def test_allowed_hosts(host):
    assert host_allowed(host)


@pytest.mark.parametrize(
    "host",
    [
        "",
        "localhost",  # no port
        "localhost:9999",  # port not allowed
        "evil.example:8002",
        "localhost.evil.example:8002",
        "evil.example",
        "0.0.0.0:8002",
        "[::2]:8002",
        "::1:8002",  # unbracketed IPv6
        "[::1:8002",
        "localhost:80x",
        "localhost:",
        "localhost:8002@evil.example",
        "evil.example#localhost:8002",
    ],
)
def test_rejected_hosts(host):
    assert not host_allowed(host)


def test_split_host_header_ipv6():
    assert split_host_header("[::1]:8002") == ("[::1]", 8002)
    assert split_host_header("[::1]") == ("[::1]", None)


def test_unknown_host_is_400_on_a_get():
    with TestClient(_mini_app(), base_url="http://evil.example:8002") as client:
        response = client.get("/ping")
    assert response.status_code == 400


def test_dns_rebinding_host_is_400_on_the_real_app():
    with TestClient(main.app, base_url="http://attacker.example:8002") as client:
        assert client.get("/api/health").status_code == 400


def test_ipv6_loopback_host_is_served():
    # The TestClient cannot take an IPv6 base_url, so the Host header is set on the request instead.
    with TestClient(_mini_app()) as client:
        assert client.get("/ping", headers={"Host": "[::1]:8002"}).status_code == 200
        assert client.get("/ping", headers={"Host": "[::2]:8002"}).status_code == 400


def test_allowed_host_ports_are_configurable(monkeypatch):
    monkeypatch.setattr(settings, "allowed_host_ports", "9123")
    with TestClient(_mini_app(), base_url="http://localhost:9123") as client:
        assert client.get("/ping").status_code == 200
    with TestClient(_mini_app(), base_url="http://localhost:8002") as client:
        assert client.get("/ping").status_code == 400


# --- Safe methods -------------------------------------------------------------------------------------------------


def test_get_needs_no_origin_and_no_header(mini):
    assert mini.get("/ping", headers=NO_HEADER).status_code == 200


def test_get_with_a_foreign_origin_is_still_served(mini):
    # Reads are not forged writes; the browser's same-origin policy keeps the response from the other site.
    assert mini.get("/ping", headers={"Origin": EVIL_ORIGIN}).status_code == 200


def test_options_is_not_blocked_by_the_cross_site_check(mini):
    # No CORS middleware exists, so FastAPI answers 405; the point is that it is not our 403.
    assert mini.options("/write", headers={**NO_HEADER, "Origin": EVIL_ORIGIN}).status_code != 403


def test_health_is_public_and_get_only():
    with TestClient(main.app, headers=NO_HEADER) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.post("/api/health").status_code == 403  # a write with no Origin and no header
    with TestClient(main.app) as client:
        assert client.post("/api/health").status_code == 405


# --- Writes -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_with_the_custom_header_and_no_origin_passes(mini, method):
    assert mini.request(method, "/write").status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_with_no_origin_and_no_header_is_403(mini, method):
    assert mini.request(method, "/write", headers=NO_HEADER).status_code == 403


def test_write_with_an_allowed_origin_passes_without_the_header(mini):
    assert mini.post("/write", headers={**NO_HEADER, "Origin": GOOD_ORIGIN}).status_code == 200


def test_write_with_the_127_origin_passes(mini):
    assert mini.post("/write", headers={**NO_HEADER, "Origin": "http://127.0.0.1:3100"}).status_code == 200


@pytest.mark.parametrize(
    "origin",
    [
        EVIL_ORIGIN,
        "null",
        "http://localhost:3101",
        "https://localhost:3100",
        "http://localhost.evil.example:3100",
        "http://localhost:3100.evil.example",
        "",
    ],
)
def test_write_with_a_foreign_origin_is_403_even_with_the_header(mini, origin):
    assert mini.post("/write", headers={"Origin": origin}).status_code == 403


def test_forged_cross_site_form_post_is_403(mini):
    # What a browser sends for <form method=post action=http://localhost:8002/write> on another site: a form content
    # type, an Origin of that site, a Referer from it, and no custom header.
    response = mini.post(
        "/write",
        content="a=1",
        headers={
            **NO_HEADER,
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": EVIL_ORIGIN,
            "Referer": f"{EVIL_ORIGIN}/attack.html",
        },
    )
    assert response.status_code == 403


def test_form_post_with_origin_stripped_still_needs_the_header(mini):
    # Referrer-Policy: no-referrer on the attacking page can remove both Origin and Referer.
    response = mini.post("/write", content="a=1", headers={**NO_HEADER, "Content-Type": "text/plain"})
    assert response.status_code == 403


def test_foreign_referer_without_origin_is_403_even_with_the_header(mini):
    assert mini.post("/write", headers={"Referer": f"{EVIL_ORIGIN}/x"}).status_code == 403


def test_allowed_referer_without_origin_and_with_the_header_passes(mini):
    assert mini.post("/write", headers={"Referer": f"{GOOD_ORIGIN}/tickers/AAPL"}).status_code == 200


def test_allowed_origins_are_configurable(monkeypatch):
    monkeypatch.setattr(settings, "allowed_origins", "http://localhost:4000")
    with TestClient(_mini_app()) as client:
        assert client.post("/write", headers={**NO_HEADER, "Origin": "http://localhost:4000"}).status_code == 200
        assert client.post("/write", headers={**NO_HEADER, "Origin": GOOD_ORIGIN}).status_code == 403


def test_rejected_write_never_reaches_the_handler():
    calls = []
    app = FastAPI()
    app.add_middleware(RequestGuardMiddleware)

    @app.post("/write")
    def write() -> dict:
        calls.append(1)
        return {}

    with TestClient(app) as client:
        client.post("/write", headers={"Origin": EVIL_ORIGIN})
        client.post("/write", headers=NO_HEADER)
    assert calls == []


# --- The real app -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), BODYLESS_WRITES)
def test_forged_cross_site_post_to_each_bodyless_endpoint_is_403(method, path):
    with TestClient(main.app) as client:
        response = client.request(
            method,
            path,
            headers={**NO_HEADER, "Origin": EVIL_ORIGIN, "Referer": f"{EVIL_ORIGIN}/attack.html"},
        )
    assert response.status_code == 403
    assert "rejected" in response.json()["detail"]


@pytest.mark.parametrize(("method", "path"), BODYLESS_WRITES)
def test_bodyless_endpoint_with_no_origin_and_no_header_is_403(method, path):
    with TestClient(main.app, headers=NO_HEADER) as client:
        assert client.request(method, path).status_code == 403


def test_in_app_write_gets_past_the_guard_on_the_real_app():
    # An empty body fails validation (422) before the handler runs: 422, not the guard's 403, and no database write.
    with TestClient(main.app) as client:
        assert client.post("/api/watchlists", json={}).status_code == 422
    with TestClient(main.app, headers=NO_HEADER) as client:
        assert client.post("/api/watchlists", json={}, headers={"Origin": GOOD_ORIGIN}).status_code == 422
