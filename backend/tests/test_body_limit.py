"""Request body size limit (core/body_limit.py): oversized Content-Length, oversized chunked body, a normal body, ordering against the guard."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

from core import main
from core.body_limit import TOO_LARGE_DETAIL, BodySizeLimitMiddleware
from core.config import settings
from core.request_guard import RequestGuardMiddleware

LIMIT = 1_000


class Payload(BaseModel):
    text: str


def _mini_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestGuardMiddleware)

    @app.post("/echo")
    def echo(body: Payload) -> dict:
        return {"n": len(body.text)}

    @app.post("/raw")
    async def raw(request: Request) -> dict:
        return {"n": len(await request.body())}

    return app


@pytest.fixture
def mini(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", LIMIT)
    with TestClient(_mini_app()) as client:
        yield client


def _chunks(total: int, size: int = 100):
    sent = 0
    while sent < total:
        n = min(size, total - sent)
        yield b"x" * n
        sent += n


def test_normal_body_passes(mini):
    response = mini.post("/echo", json={"text": "a" * 100})
    assert response.status_code == 200 and response.json() == {"n": 100}


def test_body_exactly_at_the_limit_passes(mini):
    response = mini.post("/raw", content=b"x" * LIMIT)
    assert response.status_code == 200 and response.json() == {"n": LIMIT}


def test_oversized_content_length_is_413(mini):
    response = mini.post("/echo", json={"text": "a" * (LIMIT * 2)})
    assert response.status_code == 413
    assert response.json() == {"detail": TOO_LARGE_DETAIL}
    assert str(LIMIT) not in response.text  # generic: no size or limit in the answer


def test_oversized_chunked_body_is_413(mini):
    response = mini.post("/raw", content=_chunks(LIMIT * 5))
    assert response.status_code == 413
    assert response.json() == {"detail": TOO_LARGE_DETAIL}


def test_oversized_chunked_json_body_is_413_not_400(mini):
    # FastAPI turns an exception raised from receive into a 400; the limit must answer before that.
    payload = json.dumps({"text": "a" * (LIMIT * 3)}).encode()
    response = mini.post("/echo", content=iter([payload[i : i + 200] for i in range(0, len(payload), 200)]), headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_chunked_body_under_the_limit_passes(mini):
    response = mini.post("/raw", content=_chunks(LIMIT - 1))
    assert response.status_code == 200 and response.json() == {"n": LIMIT - 1}


def test_a_lying_content_length_is_still_counted(mini):
    # Declares 10 bytes, sends more: h11 refuses the extra bytes in a real server; here the ASGI body is what is counted.
    from starlette.types import Message

    sent: list[Message] = []
    chunks = [{"type": "http.request", "body": b"x" * 600, "more_body": True}, {"type": "http.request", "body": b"x" * 600, "more_body": False}]

    async def receive() -> Message:
        return chunks.pop(0) if chunks else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    import asyncio

    scope = {
        "type": "http", "method": "POST", "path": "/raw", "headers": [(b"host", b"localhost:8002"), (b"content-length", b"10"), (b"x-fathom-request", b"1")],
        "query_string": b"", "raw_path": b"/raw", "root_path": "", "scheme": "http", "server": ("localhost", 8002), "client": ("127.0.0.1", 1), "http_version": "1.1",
    }
    asyncio.run(_mini_app()(scope, receive, send))
    assert sent[0]["status"] == 413
    assert sum(1 for m in sent if m["type"] == "http.response.start") == 1


def test_limit_off_when_zero(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 0)
    with TestClient(_mini_app()) as client:
        assert client.post("/raw", content=b"x" * 50_000).status_code == 200


def test_limit_is_read_on_every_request(monkeypatch):
    with TestClient(_mini_app()) as client:
        monkeypatch.setattr(settings, "max_request_body_bytes", 10)
        assert client.post("/raw", content=b"x" * 50).status_code == 413
        monkeypatch.setattr(settings, "max_request_body_bytes", 100)
        assert client.post("/raw", content=b"x" * 50).status_code == 200


def test_get_is_not_affected(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 10)
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200


# --- the real app: order against the guard and auth, and the default ----------------------------------------------


def test_default_limit_is_one_megabyte():
    assert settings.max_request_body_bytes == 1_048_576


def test_oversized_post_on_the_real_app_is_413(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 5_000)
    with TestClient(main.app) as client:
        response = client.post("/api/watchlists", json={"name": "a" * 20_000})
    assert response.status_code == 413


@pytest.mark.auth("anonymous")
def test_oversized_post_is_413_before_auth(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 5_000)
    with TestClient(main.app, headers={"X-Fathom-Request": "1"}) as client:
        assert client.post("/api/watchlists", json={"name": "a" * 20_000}).status_code == 413
        assert client.post("/api/watchlists", json={"name": "ok"}).status_code == 401


def test_forged_cross_site_oversized_post_is_still_403(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 5_000)
    with TestClient(main.app) as client:
        response = client.post("/api/watchlists", json={"name": "a" * 20_000}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_bad_host_oversized_post_is_still_400(monkeypatch):
    monkeypatch.setattr(settings, "max_request_body_bytes", 5_000)
    with TestClient(main.app, base_url="http://evil.example:8002") as client:
        assert client.post("/api/watchlists", json={"name": "a" * 20_000}).status_code == 400


def test_legitimate_bodies_are_far_below_the_default():
    from core.schemas import MAX_BULK_TICKERS, MAX_FILTERS_JSON_BYTES

    bulk = json.dumps({"tickers": ["BRK-B.XX"] * MAX_BULK_TICKERS, "opportunity_run_id": 123456})
    assert len(bulk) < settings.max_request_body_bytes / 100
    assert MAX_FILTERS_JSON_BYTES + 2_000 < settings.max_request_body_bytes / 10
