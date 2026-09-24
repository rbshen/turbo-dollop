import core.data_groups as _dg
import asyncio
import time

import httpx
import pytest

import clients.fmp_client as fmp_client_module
from clients.fmp_client import FMPClient, FMPDisabledError


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


def test_disabled_raises_without_ever_touching_the_network(monkeypatch):
    def fail_if_called(request):
        raise AssertionError("must not attempt a network call while FMP_ENABLED is False")

    _install_mock_transport(monkeypatch, fail_if_called)
    _dg.set_master(False)
    client = FMPClient(api_key="x")

    with pytest.raises(FMPDisabledError):
        asyncio.run(client.get("/profile", {"symbol": "AAPL"}))

    assert client.request_count == 0


def test_get_sp500_constituents_hits_expected_endpoint(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"symbol": "AAPL", "name": "Apple Inc."}])

    _install_mock_transport(monkeypatch, handler)
    client = FMPClient(api_key="x")

    result = asyncio.run(client.get_sp500_constituents())

    assert result == [{"symbol": "AAPL", "name": "Apple Inc."}]
    assert "/sp500-constituent" in seen["url"]
    assert "apikey=x" in seen["url"]


def test_get_dowjones_constituents_hits_expected_endpoint(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"symbol": "AAPL", "name": "Apple Inc."}])

    _install_mock_transport(monkeypatch, handler)
    client = FMPClient(api_key="x")

    result = asyncio.run(client.get_dowjones_constituents())

    assert result == [{"symbol": "AAPL", "name": "Apple Inc."}]
    assert "/dowjones-constituent" in seen["url"]
    assert "apikey=x" in seen["url"]


def test_get_nasdaq_constituents_hits_expected_endpoint(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"symbol": "AAPL", "name": "Apple Inc."}])

    _install_mock_transport(monkeypatch, handler)
    client = FMPClient(api_key="x")

    result = asyncio.run(client.get_nasdaq_constituents())

    assert result == [{"symbol": "AAPL", "name": "Apple Inc."}]
    assert "/nasdaq-constituent" in seen["url"]
    assert "apikey=x" in seen["url"]


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


def test_get_earnings_history_and_dividends_request_the_deeper_limits(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, dict(request.url.params)))
        return httpx.Response(200, json=[])

    _install_mock_transport(monkeypatch, handler)
    client = FMPClient(api_key="x")

    asyncio.run(client.get_earnings_history("AAPL"))
    asyncio.run(client.get_dividends("AAPL"))

    # base_url carries a /stable prefix; only the endpoint suffix matters here.
    assert seen[0][0].endswith("/earnings") and (seen[0][1]["symbol"], seen[0][1]["limit"]) == ("AAPL", "40")
    assert seen[1][0].endswith("/dividends") and (seen[1][1]["symbol"], seen[1][1]["limit"]) == ("AAPL", "400")


def _recording_transport(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json=[{"ok": True}])

    _install_mock_transport(monkeypatch, handler)
    return seen


def test_only_the_endpoints_own_group_is_gated(monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    seen = _recording_transport(monkeypatch)
    _dg.set_group_enabled("fundamentals", False)
    client = FMPClient(api_key="x")

    with pytest.raises(FMPGroupDisabledError) as exc:
        asyncio.run(client.get_income_statement("AAPL", "annual", 1))
    assert exc.value.group == "fundamentals"
    assert isinstance(exc.value, FMPDisabledError)  # existing except sites keep working
    assert seen == []

    asyncio.run(client.get_profile("AAPL"))  # profile_quote still live
    assert seen == ["/stable/profile"]


def test_forex_quote_follows_fundamentals_not_profile_quote(monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    seen = _recording_transport(monkeypatch)
    _dg.set_group_enabled("profile_quote", False)
    client = FMPClient(api_key="x")

    asyncio.run(client.get_forex_quote("EUR"))  # fundamentals live -> allowed
    with pytest.raises(FMPGroupDisabledError):
        asyncio.run(client.get_quote("AAPL"))
    assert seen == ["/stable/quote"]


def test_earnings_history_follows_corporate_events_not_fundamentals(monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    _recording_transport(monkeypatch)
    _dg.set_group_enabled("corporate_events", False)
    client = FMPClient(api_key="x")

    asyncio.run(client.get_earnings("AAPL"))
    with pytest.raises(FMPGroupDisabledError):
        asyncio.run(client.get_earnings_history("AAPL"))


def test_above_plan_and_restricted_groups_refuse_live_calls(monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    _recording_transport(monkeypatch)
    _dg.set_fmp_plan("Starter")
    client = FMPClient(api_key="x")
    with pytest.raises(FMPGroupDisabledError):
        asyncio.run(client.get_ratios("AAPL"))  # fundamentals needs Premium
    _dg.set_fmp_plan("Ultimate")
    _dg.mark_restricted("news", "402")
    with pytest.raises(FMPGroupDisabledError):
        asyncio.run(client.get_stock_news("AAPL"))


def test_unmapped_endpoint_fails_closed(monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    seen = _recording_transport(monkeypatch)
    with pytest.raises(FMPGroupDisabledError):
        asyncio.run(FMPClient(api_key="x").get("/brand-new-endpoint", {"symbol": "AAPL"}))
    assert seen == []


def test_successful_call_records_group_success(monkeypatch):
    _recording_transport(monkeypatch)
    asyncio.run(FMPClient(api_key="x").get_profile("AAPL"))
    assert _dg.get_snapshot().groups["profile_quote"].last_success_at is not None


def test_historical_price_eod_is_gated_by_the_group_the_caller_names(monkeypatch):
    """One endpoint, three groups: turning one off refuses only calls that name it."""
    from clients.fmp_client import FMPGroupDisabledError

    seen = _recording_transport(monkeypatch)
    client = FMPClient(api_key="x")
    for off, still_live in (
        ("daily_prices", ("daily_prices_long", "daily_prices_intl")),
        ("daily_prices_long", ("daily_prices", "daily_prices_intl")),
        ("daily_prices_intl", ("daily_prices", "daily_prices_long")),
    ):
        _dg.set_group_enabled(off, False)
        seen.clear()
        with pytest.raises(FMPGroupDisabledError) as exc:
            asyncio.run(client.get_historical_price_eod("AAPL", "2020-01-01", "2020-02-01", group=off))
        assert exc.value.group == off and seen == []
        for other in still_live:
            asyncio.run(client.get_historical_price_eod("AAPL", "2020-01-01", "2020-02-01", group=other))
        assert seen == ["/stable/historical-price-eod/full"] * 2
        _dg.set_group_enabled(off, True)


def test_historical_price_eod_defaults_to_the_daily_prices_group(monkeypatch):
    from clients.fmp_client import FMPGroupDisabledError

    _recording_transport(monkeypatch)
    _dg.set_group_enabled("daily_prices", False)
    with pytest.raises(FMPGroupDisabledError) as exc:
        asyncio.run(FMPClient(api_key="x").get_historical_price_eod("AAPL", "2020-01-01", "2020-02-01"))
    assert exc.value.group == "daily_prices"
