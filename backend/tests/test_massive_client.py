import asyncio
from datetime import date

import httpx
import pytest

import clients.massive_client as massive_client_module
from clients.massive_client import MassiveClient


def _install_mock_transport(monkeypatch, handler):
    """Same MockTransport-swap convention as tests/test_fmp_client.py --
    no actual HTTP call ever leaves the process in these tests."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(**kwargs)

    monkeypatch.setattr(massive_client_module.httpx, "AsyncClient", factory)


def _bar(t_ms: int, o=100.0, h=101.0, l=99.0, c=100.5, v=1000) -> dict:
    return {"t": t_ms, "o": o, "h": h, "l": l, "c": c, "v": v}


# 2026-09-22 00:00 America/New_York (EDT, UTC-4), expressed as Unix ms UTC (04:00 UTC).
_SEPT_22_MS = 1790049600000


def test_get_daily_bars_returns_lowercase_columns_and_naive_index(monkeypatch):
    def handler(request):
        assert "apiKey=" in str(request.url)
        return httpx.Response(200, json={"results": [_bar(_SEPT_22_MS)], "resultsCount": 1})

    _install_mock_transport(monkeypatch, handler)
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    df = asyncio.run(client.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 22)))

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is None
    assert df.iloc[0]["close"] == 100.5
    assert df.index[0].date() == date(2026, 9, 22)


def test_get_daily_bars_empty_result_returns_empty_frame_not_an_error(monkeypatch):
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(200, json={"results": [], "resultsCount": 0}))
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    df = asyncio.run(client.get_daily_bars("BRK-B", date(2026, 9, 1), date(2026, 9, 22)))

    assert df.empty


def test_get_daily_bars_404_returns_empty_frame(monkeypatch):
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(404, json={"error": "not found"}))
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    df = asyncio.run(client.get_daily_bars("ZZZZINVALID", date(2026, 9, 1), date(2026, 9, 22)))

    assert df.empty


def test_pagination_follows_next_url_until_exhausted(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            assert "apiKey=" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "results": [_bar(_SEPT_22_MS)],
                    "next_url": "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2026-09-01/2026-09-22?cursor=abc",
                },
            )
        if calls["n"] == 2:
            # next_url must carry the apiKey re-added by _get, not just whatever's baked into the cursor URL.
            assert "apiKey=" in str(request.url)
            return httpx.Response(200, json={"results": [_bar(_SEPT_22_MS - 86_400_000)]})
        raise AssertionError("should not be called a third time")

    _install_mock_transport(monkeypatch, handler)
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    df = asyncio.run(client.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 22)))

    assert calls["n"] == 2
    assert len(df) == 2


def test_429_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(massive_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.01)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"status": "ERROR", "error": "exceeded max requests per minute"})
        return httpx.Response(200, json={"results": [_bar(_SEPT_22_MS)]})

    _install_mock_transport(monkeypatch, handler)
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    df = asyncio.run(client.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 22)))

    assert calls["n"] == 2
    assert len(df) == 1


def test_server_error_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(massive_client_module, "SERVER_ERROR_RETRY_BACKOFF_SECONDS", 0.01)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, json={"status": "ERROR"})
        return httpx.Response(200, json={"results": [_bar(_SEPT_22_MS)]})

    _install_mock_transport(monkeypatch, handler)
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    df = asyncio.run(client.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 22)))

    assert calls["n"] == 2
    assert len(df) == 1


def test_429_exhausted_retries_raises(monkeypatch):
    monkeypatch.setattr(massive_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.01)
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(429, json={"status": "ERROR"}))
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.get_daily_bars("AAPL", date(2026, 9, 1), date(2026, 9, 22)))


def test_get_grouped_daily_maps_massive_symbols_to_frames(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "results": [
                    {**_bar(_SEPT_22_MS), "T": "AAPL"},
                    {**_bar(_SEPT_22_MS, c=210.0), "T": "BRK.B"},
                ]
            },
        )

    _install_mock_transport(monkeypatch, handler)
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    result = asyncio.run(client.get_grouped_daily(date(2026, 9, 22)))

    assert set(result) == {"AAPL", "BRK.B"}
    assert result["BRK.B"].iloc[0]["close"] == 210.0


def test_get_recent_splits_paginates_and_returns_raw_rows(monkeypatch):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "results": [{"ticker": "SMCI", "execution_date": "2026-09-01", "split_from": 1, "split_to": 10}],
                    "next_url": "https://api.polygon.io/v3/reference/splits?cursor=abc",
                },
            )
        return httpx.Response(
            200, json={"results": [{"ticker": "NVDA", "execution_date": "2026-09-05", "split_from": 1, "split_to": 10}]}
        )

    _install_mock_transport(monkeypatch, handler)
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    splits = asyncio.run(client.get_recent_splits(date(2026, 8, 1)))

    assert calls["n"] == 2
    assert {s["ticker"] for s in splits} == {"SMCI", "NVDA"}


def test_get_snapshot_returns_ticker_payload(monkeypatch):
    _install_mock_transport(
        monkeypatch, lambda request: httpx.Response(200, json={"ticker": {"day": {"c": 340.5}, "prevDay": {"c": 339.0}}})
    )
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    snapshot = asyncio.run(client.get_snapshot("AAPL"))

    assert snapshot == {"day": {"c": 340.5}, "prevDay": {"c": 339.0}}


def test_get_snapshot_404_returns_none(monkeypatch):
    _install_mock_transport(monkeypatch, lambda request: httpx.Response(404, json={"status": "NOT_FOUND"}))
    client = MassiveClient(base_url="https://api.polygon.io", api_key="x")

    assert asyncio.run(client.get_snapshot("ZZZZINVALID")) is None
