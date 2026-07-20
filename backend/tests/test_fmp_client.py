import asyncio
import time

import httpx
import pytest

import fmp_client as fmp_client_module
from fmp_client import FMPClient


def _install_mock_transport(monkeypatch, handler):
    """Wires FMPClient.get's internally-constructed httpx.AsyncClient to a
    MockTransport instead of the real network -- no actual HTTP call ever
    leaves the process in these tests."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient  # capture before patching -- patching the module attribute in place would make this factory recurse into itself

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)


def test_no_pacing_by_default(monkeypatch):
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
    client = FMPClient(api_key="x")  # min_request_interval defaults to 0.0

    start = time.monotonic()
    asyncio.run(_two_calls(client))
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # no throttling should ever make two trivial calls take this long


async def _two_calls(client):
    await client.get("/profile", {"symbol": "AAPL"})
    await client.get("/profile", {"symbol": "MSFT"})


def test_pacing_enforces_minimum_interval_between_requests(monkeypatch):
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
    client = FMPClient(api_key="x", min_request_interval=0.3)

    start = time.monotonic()
    asyncio.run(_two_calls(client))
    elapsed = time.monotonic() - start

    # Second call must wait out the remaining interval after the first.
    assert elapsed >= 0.3


def test_request_count_increments_per_real_http_call(monkeypatch):
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))
    client = FMPClient(api_key="x")

    asyncio.run(_two_calls(client))

    assert client.request_count == 2


def test_429_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(fmp_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.01)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"Error Message": "Limit Reach"})
        return httpx.Response(200, json={"symbol": "AAPL"})

    _install_mock_transport(monkeypatch, handler)
    client = FMPClient(api_key="x")

    result = asyncio.run(client.get("/profile", {"symbol": "AAPL"}))

    assert result == {"symbol": "AAPL"}
    assert calls["n"] == 3
    assert client.request_count == 3


def test_429_exhausts_retries_and_raises(monkeypatch):
    monkeypatch.setattr(fmp_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.01)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(429, json={"Error Message": "Limit Reach"})

    _install_mock_transport(monkeypatch, handler)
    client = FMPClient(api_key="x")

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.get("/profile", {"symbol": "AAPL"}))

    # RATE_LIMIT_MAX_RETRIES retries + the original attempt.
    assert calls["n"] == fmp_client_module.RATE_LIMIT_MAX_RETRIES + 1
    assert client.request_count == fmp_client_module.RATE_LIMIT_MAX_RETRIES + 1
