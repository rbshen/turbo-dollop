"""402 safety net, against SIMULATED responses only (no real 402 has ever been
observed on our key): a group is marked plan_restricted only when a canary
(AAPL, same endpoint) also 402s; 401/403 are a key problem that blames no
group; 429 never marks anything; restricted groups are re-probed."""

import asyncio

import httpx
import pytest

import clients.fmp_client as fmp_client_module
import core.data_groups as dg
from clients.fmp_client import FMPClient


def _install(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)


def _status_by_symbol(codes: dict[str, int], default=200):
    seen = []

    def handler(request):
        sym = request.url.params.get("symbol") or request.url.params.get("symbols") or request.url.params.get("query")
        seen.append(sym)
        return httpx.Response(codes.get(sym, default), json=[{"ok": True}])

    handler.seen = seen
    return handler


def _get(client, coro):
    return asyncio.run(coro)


def test_402_with_canary_also_402_marks_group_restricted(monkeypatch):
    h = _status_by_symbol({"0700.HK": 402, "AAPL": 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_income_statement("0700.HK", "annual", 1))
    assert h.seen == ["0700.HK", "AAPL"]  # failing call, then the canary
    assert dg.effective_state("fundamentals") == (False, "restricted")
    assert dg.get_snapshot().groups["fundamentals"].restricted_since is not None
    # ...and the group is now short-circuited: no further network call
    n = len(h.seen)
    with pytest.raises(fmp_client_module.FMPGroupDisabledError):
        asyncio.run(FMPClient(api_key="x").get_income_statement("MSFT", "annual", 1))
    assert len(h.seen) == n


def test_402_symbol_scoped_canary_ok_does_not_mark(monkeypatch):
    h = _status_by_symbol({"0700.HK": 402})  # AAPL -> 200
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_income_statement("0700.HK", "annual", 1))
    assert dg.effective_state("fundamentals") == (True, "live")


def test_402_on_aapl_itself_is_its_own_canary(monkeypatch):
    h = _status_by_symbol({"AAPL": 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_stock_news("AAPL"))
    assert h.seen == ["AAPL"]  # no redundant second call
    assert dg.effective_state("news") == (False, "restricted")


def test_402_on_symbolless_endpoint_marks_immediately(monkeypatch):
    h = _status_by_symbol({}, default=402)
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_dowjones_constituents())
    assert dg.effective_state("index_membership") == (False, "restricted")


def test_only_the_402d_group_is_marked(monkeypatch):
    _install(monkeypatch, _status_by_symbol({}, default=402))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_stock_news("AAPL"))
    assert dg.effective_state("news")[0] is False
    assert dg.effective_state("fundamentals")[0] is True
    assert dg.effective_state("profile_quote")[0] is True


@pytest.mark.parametrize("code", [401, 403])
def test_401_403_is_a_key_problem_and_blames_no_group(monkeypatch, code):
    h = _status_by_symbol({}, default=code)
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_profile("AAPL"))
    snap = dg.get_snapshot()
    assert snap.key_problem_at is not None and str(code) in snap.key_problem_detail
    assert all(g.status == "ok" for g in snap.groups.values())
    assert dg.effective_state("profile_quote") == (True, "live")
    assert h.seen == ["AAPL"]  # no canary probe for a key problem


def test_key_problem_clears_on_next_success(monkeypatch):
    dg.set_key_problem("HTTP 401")
    _install(monkeypatch, _status_by_symbol({}))
    asyncio.run(FMPClient(api_key="x").get_profile("AAPL"))
    assert dg.get_snapshot().key_problem_at is None


def test_429_never_marks_anything(monkeypatch):
    monkeypatch.setattr(fmp_client_module, "RATE_LIMIT_RETRY_BACKOFF_SECONDS", 0.0)
    h = _status_by_symbol({}, default=429)
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_profile("AAPL"))
    snap = dg.get_snapshot()
    assert all(g.status == "ok" and g.consecutive_failures == 0 for g in snap.groups.values())
    assert snap.key_problem_at is None


def test_server_errors_count_toward_failing_but_never_disable(monkeypatch):
    _install(monkeypatch, _status_by_symbol({}, default=500))
    for _ in range(dg.FAILING_AFTER_CONSECUTIVE):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(FMPClient(api_key="x").get_profile("AAPL"))
    assert dg.get_snapshot().groups["profile_quote"].status == "failing"
    assert dg.group_live("profile_quote")


def test_reprobe_clears_restriction_when_canary_succeeds(monkeypatch):
    dg.mark_restricted("news", "simulated")
    _install(monkeypatch, _status_by_symbol({}))
    result = asyncio.run(FMPClient(api_key="x").reprobe_restricted_groups())
    assert result == {"news": "ok"}
    assert dg.effective_state("news") == (True, "live")


def test_reprobe_keeps_restriction_on_402_and_ignores_inconclusive(monkeypatch):
    dg.mark_restricted("news", "simulated")
    dg.mark_restricted("segmentation", "simulated")

    def handler(request):
        return httpx.Response(402 if "news" in request.url.path else 500, json=[])

    _install(monkeypatch, handler)
    result = asyncio.run(FMPClient(api_key="x").reprobe_restricted_groups())
    assert result == {"news": "restricted", "segmentation": "inconclusive"}
    assert dg.effective_state("news") == (False, "restricted")
    assert dg.effective_state("segmentation") == (False, "restricted")


def test_reprobe_is_a_noop_while_master_is_off(monkeypatch):
    dg.mark_restricted("news", "simulated")
    dg.set_master(False)

    def handler(request):
        raise AssertionError("master off -> zero live calls")

    _install(monkeypatch, handler)
    assert asyncio.run(FMPClient(api_key="x").reprobe_restricted_groups()) == {}


def test_every_probe_endpoint_is_mapped_to_its_own_group():
    # /historical-price-eod/full is shared by three groups (the caller names one), so
    # its default mapping only has to match `daily_prices`.
    shared = {"daily_prices_long", "daily_prices_intl"}
    for group, (endpoint, _params) in dg.PROBE_ENDPOINTS.items():
        if group in shared:
            assert endpoint in dg.ENDPOINT_GROUP_OVERRIDES_USED
            continue
        assert dg.ENDPOINT_GROUP[endpoint] == group, (group, endpoint)


# --- P3: daily_prices_long / daily_prices_intl share /historical-price-eod/full -------------------


def _get_bars(symbol, group):
    return asyncio.run(FMPClient(api_key="x").get_historical_price_eod(symbol, "2016-01-01", "2016-02-01", group=group))


def test_intl_402_canary_is_a_non_us_symbol_not_aapl(monkeypatch):
    """A plan without global coverage 402s non-US symbols only, so AAPL (200) must NOT
    make the group read 'symbol-scoped, left live' -- its canary is 0005.HK."""
    h = _status_by_symbol({"3988.HK": 402, "0005.HK": 402})  # AAPL -> 200
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _get_bars("3988.HK", "daily_prices_intl")
    assert h.seen == ["3988.HK", "0005.HK"]
    assert dg.effective_state("daily_prices_intl") == (False, "restricted")
    assert dg.effective_state("daily_prices") == (True, "live")  # sibling groups untouched
    assert dg.effective_state("daily_prices_long") == (True, "live")


def test_intl_402_on_one_symbol_only_leaves_the_group_live(monkeypatch):
    h = _status_by_symbol({"3988.HK": 402})  # canary 0005.HK -> 200
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _get_bars("3988.HK", "daily_prices_intl")
    assert dg.effective_state("daily_prices_intl") == (True, "live")


def test_intl_402_on_the_canary_symbol_is_its_own_canary(monkeypatch):
    h = _status_by_symbol({"0005.HK": 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _get_bars("0005.HK", "daily_prices_intl")
    assert h.seen == ["0005.HK"]
    assert dg.effective_state("daily_prices_intl") == (False, "restricted")


def test_long_402_with_aapl_canary_restricts_only_the_long_group(monkeypatch):
    h = _status_by_symbol({"KO": 402, "AAPL": 402})
    _install(monkeypatch, h)
    with pytest.raises(httpx.HTTPStatusError):
        _get_bars("KO", "daily_prices_long")
    assert h.seen == ["KO", "AAPL"]
    assert dg.effective_state("daily_prices_long") == (False, "restricted")
    assert dg.effective_state("daily_prices") == (True, "live")


@pytest.mark.parametrize("group,canary", [("daily_prices_long", "AAPL"), ("daily_prices_intl", "0005.HK")])
def test_reprobe_clears_a_restricted_p3_group(monkeypatch, group, canary):
    h = _status_by_symbol({})
    _install(monkeypatch, h)
    dg.mark_restricted(group, "simulated 402")
    assert asyncio.run(FMPClient(api_key="x").reprobe_restricted_groups()) == {group: "ok"}
    assert h.seen == [canary]
    assert dg.effective_state(group) == (True, "live")


def test_reprobe_keeps_a_group_restricted_on_402(monkeypatch):
    _install(monkeypatch, _status_by_symbol({}, default=402))
    dg.mark_restricted("daily_prices_intl", "simulated 402")
    assert asyncio.run(FMPClient(api_key="x").reprobe_restricted_groups()) == {"daily_prices_intl": "restricted"}
    assert dg.effective_state("daily_prices_intl") == (False, "restricted")
