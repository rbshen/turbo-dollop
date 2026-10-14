"""The FMP plan is Starter (2026-10-14, docs/decisions.md): which groups stay live, the relative-date probes, the two groups
split out of profile_quote, and the Sunday index-membership jobs skipping with the stored lists untouched."""

import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.fmp_client as fmp_client_module
import core.data_groups as dg
import pipeline.stale_data_health_check as health_check
import scrapers.refresh_dow_list as refresh_dow_list
import scrapers.refresh_nasdaq_list as refresh_nasdaq_list
import scrapers.refresh_sp500_list as refresh_sp500_list
from clients.fmp_client import FMPClient
from core.models import IndexConstituent, TickerScore


@pytest.fixture
def starter():
    dg.set_fmp_plan("Starter")


def _install(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(**kwargs)

    monkeypatch.setattr(fmp_client_module.httpx, "AsyncClient", factory)


# --- which groups a Starter plan leaves live ---------------------------------------------------------


def test_only_index_membership_is_above_a_starter_plan(starter):
    off = {g for g in dg.GROUPS if dg.effective_state(g)[0] is False}
    assert off == {"index_membership"}
    assert dg.effective_state("index_membership") == (False, "above_plan")
    for group in ("daily_prices", "daily_prices_long", "intraday_bars", "sector_industry_pe", "etf_info", "price_change", "ticker_search"):
        assert dg.effective_state(group) == (True, "live"), group


def test_every_group_is_recorded_starter_except_index_membership():
    assert {g for g, m in dg.GROUPS.items() if m.default_tier != "Starter"} == {"index_membership"}


# --- probes: dates relative to today ------------------------------------------------------------------


def test_probe_dates_are_relative_to_today_not_fixed():
    today = date.today()
    snapshot = dg.PROBE_ENDPOINTS["sector_industry_pe"][1]["date"]
    assert today - timedelta(days=330) <= date.fromisoformat(snapshot) <= today  # inside the 12-month Starter window
    for group in ("daily_prices", "daily_prices_long", "intraday_bars"):
        params = dg.PROBE_ENDPOINTS[group][1]
        assert date.fromisoformat(params["from"]) < date.fromisoformat(params["to"]) < today, group
    assert today - date.fromisoformat(dg.PROBE_ENDPOINTS["daily_prices"][1]["from"]) <= timedelta(days=30)
    assert today - date.fromisoformat(dg.PROBE_ENDPOINTS["intraday_bars"][1]["from"]) <= timedelta(days=30)
    # long history: older than the 5-year nightly window, inside the 10-year store
    long_from = today - date.fromisoformat(dg.PROBE_ENDPOINTS["daily_prices_long"][1]["from"])
    assert timedelta(days=5 * 365) < long_from < timedelta(days=10 * 365)


def test_no_probe_carries_a_hardcoded_year():
    for group in dg.PROBE_ENDPOINTS:
        values = [str(v) for v in dg.PROBE_ENDPOINTS[group][1].values()]
        assert not any(v.startswith(("2016", "2024")) for v in values), group


def test_probes_follow_the_clock(monkeypatch):
    class FakeDate(date):
        @classmethod
        def today(cls):
            return cls(2031, 6, 30)

    monkeypatch.setattr(dg, "date", FakeDate)
    assert dg.PROBE_ENDPOINTS["sector_industry_pe"][1]["date"] == "2031-05-31"


def test_probe_group_sends_the_relative_date(monkeypatch):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[{"date": "x", "pe": 1}])

    _install(monkeypatch, handler)
    dg.mark_restricted("sector_industry_pe", "simulated")
    assert asyncio.run(FMPClient(api_key="x").probe_group("sector_industry_pe")) == "ok"
    assert seen[0]["date"] == dg.PROBE_ENDPOINTS["sector_industry_pe"][1]["date"]
    assert dg.effective_state("sector_industry_pe") == (True, "live")


# --- price_change / ticker_search are no longer part of profile_quote -----------------------------------


def test_endpoints_and_cache_types_map_to_the_split_groups():
    assert dg.ENDPOINT_GROUP["/stock-price-change"] == "price_change"
    assert dg.STATEMENT_TYPE_GROUP["price_change"] == "price_change"
    assert dg.ENDPOINT_GROUP["/search-symbol"] == dg.ENDPOINT_GROUP["/search-name"] == "ticker_search"
    for group in ("price_change", "ticker_search"):
        assert dg.PROBE_ENDPOINTS[group][0] in dg.ENDPOINT_GROUP and dg.ENDPOINT_GROUP[dg.PROBE_ENDPOINTS[group][0]] == group


def test_a_402_on_stock_price_change_leaves_the_header_groups_live(monkeypatch):
    def handler(request):
        return httpx.Response(402, json=[])

    _install(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_price_change("AAPL"))
    assert dg.effective_state("price_change") == (False, "restricted")
    assert dg.effective_state("profile_quote") == (True, "live")


def test_a_402_on_search_leaves_the_header_groups_live(monkeypatch):
    def handler(request):
        return httpx.Response(402, json=[])

    _install(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").search_symbol("AAP"))
    assert dg.effective_state("ticker_search") == (False, "restricted")
    assert dg.effective_state("profile_quote") == (True, "live")
    assert dg.effective_state("price_change") == (True, "live")


def test_search_falls_back_to_the_tracked_universe_when_ticker_search_is_off(monkeypatch):
    import data.ticker_search as ts

    dg.set_group_enabled("ticker_search", False)
    monkeypatch.setattr(ts, "_search_tracked_universe", lambda query, tracked_only=False: ["fallback"])

    async def boom(*a, **k):
        raise AssertionError("no live FMP call while ticker_search is off")

    monkeypatch.setattr(ts.fmp_client, "search_symbol", boom)
    monkeypatch.setattr(ts.fmp_client, "search_name", boom)
    assert asyncio.run(ts.search_tickers("AAP")) == ["fallback"]


# --- Sunday index-membership jobs and the delisted sync skip cleanly on Starter -------------------------


def _engine(monkeypatch, *modules):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in modules:
        monkeypatch.setattr(module, "engine", engine)
    return engine


@pytest.mark.parametrize(
    "module, refresh_attr, index_name",
    [
        (refresh_sp500_list, "refresh_sp500_constituents", "sp500"),
        (refresh_dow_list, "refresh_dow_constituents", "dow"),
        (refresh_nasdaq_list, "refresh_nasdaq_constituents", "nasdaq100"),
    ],
)
def test_index_list_refresh_skips_on_starter_and_keeps_the_stored_list(monkeypatch, starter, module, refresh_attr, index_name):
    engine = _engine(monkeypatch, module)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name=index_name, ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 10, 11)))
        session.commit()

    async def fail_if_called(session):
        raise AssertionError("no fetch while index_membership is above the plan")

    monkeypatch.setattr(module, refresh_attr, fail_if_called)

    assert asyncio.run(module.main()) is None  # the heartbeat then records `skipped`, not success or failure
    assert dg.job_skip_reason("index_membership") == "skipped (group index_membership required tier above current plan)"
    with Session(engine) as session:
        assert [r.ticker for r in session.exec(select(IndexConstituent)).all()] == ["AAPL"]


def test_delisted_sync_skips_on_starter_without_a_call_or_a_flag_change(monkeypatch, starter, tmp_path):
    engine = _engine(monkeypatch, health_check)
    monkeypatch.setattr(health_check, "LOG_PATH", tmp_path / "x.log")
    with Session(engine) as session:
        session.add(TickerScore(ticker="TWTR", company_name="Twitter", overall_score=50, overall_verdict="Pass", computed_at=datetime.now(), delisted_at=datetime(2026, 9, 1)))
        session.commit()

    async def boom(*a, **k):
        raise AssertionError("no /delisted-companies or /profile call while index_membership is above the plan")

    monkeypatch.setattr(health_check.fmp_client, "get_delisted_companies", boom)
    monkeypatch.setattr(health_check.fmp_client, "get_profile", boom)

    result = health_check.sync_delisted_flags(["TWTR"])

    assert result == {"newly_flagged": [], "cleared": [], "skipped": True, "complete": False}
    with Session(engine) as session:
        assert session.get(TickerScore, "TWTR").delisted_at == datetime(2026, 9, 1)  # an existing flag is never cleared
    assert "skipped (index_membership group not live)" in health_check._format_report(
        {"fresh": [], "stale": [], "never_fetched": [], "delisted": result}, 0, 10
    )
