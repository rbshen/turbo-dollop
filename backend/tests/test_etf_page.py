"""Backend for the ETF page: the `etf_info` data group, /etf/info overview (equity, non-equity, group
off, call fails), the "known ETF" lookups, the ETF watchlist add (idempotent, cap), the Moat guard,
and the small related fixes (search marker, watchlist-row flag, momentum and fundamentals-fetch
exclusion). Every test builds its own in-memory engine and patches it onto the module under test."""

import asyncio
import json
from datetime import date, datetime, timedelta

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import clients.fmp_client as fmp_client_module
import clients.shared_bars_cache as shared_bars_cache
import core.data_groups as dg
import core.main as main
import data.etf_data as etf_data
import data.momentum_data as momentum_data
import data.ticker_search as ticker_search
import data.watchlist_data as watchlist_data
import pipeline.nightly_fundamentals_fetch as nightly
from clients.fmp_client import FMPClient
from core.models import FundamentalsCache, MomentumSnapshot, TickerMoat, TickerScore, Watchlist, WatchlistTicker, TickerView
from core.schemas import Step1Out
from data.watchlists import ETF_WATCHLIST_NAME, is_monitored_watchlist_name


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


# FMP /etf/info shaped like the live SPY / SMH / GLD / TLT responses (trimmed).
SPY_INFO = {
    "symbol": "SPY",
    "name": "State Street SPDR S&P 500 ETF",
    "description": "SPY is the best-recognized and oldest US listed ETF.",
    "assetClass": "Equity",
    "domicile": "US",
    "website": "https://example.test/spy",
    "etfCompany": "SPDR",
    "expenseRatio": 0.09,
    "assetsUnderManagement": 811183220000,
    "avgVolume": 48631468,
    "inceptionDate": "1993-01-22",
    "nav": 764.13,
    "navCurrency": "USD",
    "holdingsCount": 504,
    "updatedAt": "2026-10-01T00:50:10.019Z",
    "sectorsList": [
        {"industry": "Basic Materials", "exposure": 1.68},
        {"industry": "Technology", "exposure": 34.4},
        {"industry": "Cash & Others", "exposure": 0.01},
        {"industry": "Financial Services", "exposure": 13.2},
    ],
}
GLD_INFO = {
    "symbol": "GLD",
    "name": "SPDR Gold Shares",
    "description": "Tracks the price of gold.",
    "assetClass": "Commodities",
    "etfCompany": "SPDR",
    "expenseRatio": 0.4,
    "assetsUnderManagement": 141495130000,
    "avgVolume": 8774920,
    "inceptionDate": "2004-11-18",
    "nav": 381.7,
    "holdingsCount": 0,
    "sectorsList": [{"industry": "Cash & Others", "exposure": 100}],
}


def _patch_info(monkeypatch, engine, payload=None, error: Exception | None = None):
    """Patches etf_data's engine and the client call; returns the call counter."""
    monkeypatch.setattr(etf_data, "engine", engine)
    monkeypatch.setattr(shared_bars_cache, "engine", engine)  # the Trading data block reads cached daily bars
    calls = {"n": 0}

    async def fake_get_etf_info(ticker):
        calls["n"] += 1
        if error is not None:
            raise error
        return payload

    monkeypatch.setattr(etf_data.fmp_client, "get_etf_info", fake_get_etf_info)
    return calls


def _overview(ticker="SPY"):
    return asyncio.run(etf_data.get_etf_overview(ticker))


def _seed_info_cache(engine, ticker, payload, age_days=0):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker,
                statement_type="etf_info",
                period="latest",
                fetched_at=datetime.now() - timedelta(days=age_days),
                raw_json=json.dumps(payload),
            )
        )
        session.commit()


# ---------------------------------------------------------------------------
# Data group
# ---------------------------------------------------------------------------


def test_etf_info_group_is_registered_gated_and_probed_with_spy():
    meta = dg.GROUPS["etf_info"]
    assert meta.live and meta.default_enabled
    assert meta.default_tier == "Starter"  # the owner's recorded tier, editable in Settings; never Ultimate
    assert dg.ENDPOINT_GROUP["/etf/info"] == "etf_info"
    assert dg.STATEMENT_TYPE_GROUP["etf_info"] == "etf_info"
    assert dg.PROBE_ENDPOINTS["etf_info"] == ("/etf/info", {"symbol": "SPY"})
    assert dg.CANARY_SYMBOL_OVERRIDES["/etf/info"] == "SPY"


def test_only_etf_info_is_used_among_the_etf_endpoints():
    import re

    src = open(fmp_client_module.__file__).read()
    called = set(re.findall(r'self\.get\(\s*"(/etf/[^"]+)"', src))
    assert called == {"/etf/info"}
    assert [e for e in dg.ENDPOINT_GROUP if e.startswith("/etf/")] == ["/etf/info"]


def test_a_symbol_402_on_etf_info_is_checked_against_spy_not_aapl(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, request.url.params["symbol"]))
        return httpx.Response(402, json={"Error Message": "plan"})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        fmp_client_module.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_etf_info("QQQ"))

    assert seen == [("/stable/etf/info", "QQQ"), ("/stable/etf/info", "SPY")]  # canary is SPY
    assert dg.get_snapshot().groups["etf_info"].status == "plan_restricted"  # both 402 -> plan-level


def test_etf_info_402_with_a_working_spy_canary_leaves_the_group_live(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[SPY_INFO]) if request.url.params["symbol"] == "SPY" else httpx.Response(402, json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        fmp_client_module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(FMPClient(api_key="x").get_etf_info("ODDBALL"))
    assert dg.get_snapshot().groups["etf_info"].status != "plan_restricted"


def test_stock_canaries_still_use_aapl():
    assert fmp_client_module._canary_params({"symbol": "MSFT"}, "/profile") == {"symbol": "AAPL"}
    assert fmp_client_module._canary_params({"symbol": "AAPL"}, "/profile") is None


# ---------------------------------------------------------------------------
# Overview states
# ---------------------------------------------------------------------------


def test_equity_overview_carries_facts_and_sorted_sector_weights(monkeypatch):
    _patch_info(monkeypatch, _engine(), [SPY_INFO])
    out = _overview()

    assert out.status == "ok" and out.reason is None
    assert (out.issuer, out.asset_class, out.domicile) == ("SPDR", "Equity", "US")
    assert out.expense_ratio == 0.09 and out.holdings_count == 504 and out.nav == 764.13
    assert out.assets_under_management == 811183220000 and out.avg_volume == 48631468
    assert out.inception_date == "1993-01-22" and out.description.startswith("SPY is")
    assert [w.sector for w in out.sector_weights] == ["Technology", "Financial Services", "Basic Materials", "Cash & Others"]


def test_non_equity_overview_has_no_sector_weights_and_omits_zero_facts(monkeypatch):
    _patch_info(monkeypatch, _engine(), [GLD_INFO])
    out = _overview("GLD")

    assert out.status == "ok"
    assert out.sector_weights == []  # commodity fund: "Cash & Others 100%" is not a sector breakdown
    assert out.holdings_count is None  # GLD reports 0: omitted, not "0"
    assert out.domicile is None and out.website is None  # never returned: None, so the UI omits the row


def test_equity_with_only_cash_and_others_hides_sector_weights(monkeypatch):
    _patch_info(monkeypatch, _engine(), [{**SPY_INFO, "sectorsList": [{"industry": "Cash & Others", "exposure": 100}]}])
    assert _overview().sector_weights == []


def test_fund_with_unknown_asset_class_still_shows_real_sector_weights(monkeypatch):
    info = {k: v for k, v in SPY_INFO.items() if k != "assetClass"}
    _patch_info(monkeypatch, _engine(), [info])
    assert [w.sector for w in _overview().sector_weights][0] == "Technology"


def test_empty_etf_info_is_no_data(monkeypatch):
    # A stock, or a closed-end fund: FMP answers 200 [].
    _patch_info(monkeypatch, _engine(), [])
    assert _overview("AAPL").status == "no_data"


def test_group_off_with_nothing_cached_is_unavailable_and_makes_no_call(monkeypatch):
    calls = _patch_info(monkeypatch, _engine(), [SPY_INFO])
    dg.set_group_enabled("etf_info", False)

    out = _overview()

    assert (out.status, out.reason) == ("unavailable", "group_off")
    assert calls["n"] == 0


def test_group_off_serves_the_cached_row_even_when_stale(monkeypatch):
    engine = _engine()
    _seed_info_cache(engine, "SPY", [SPY_INFO], age_days=30)
    calls = _patch_info(monkeypatch, engine, [SPY_INFO])
    dg.set_group_enabled("etf_info", False)

    out = _overview()

    assert out.status == "ok" and out.issuer == "SPDR"
    assert calls["n"] == 0


def test_master_switch_off_is_the_same_unavailable_state(monkeypatch):
    _patch_info(monkeypatch, _engine(), [SPY_INFO])
    dg.set_master(False)
    assert (_overview().status, _overview().reason) == ("unavailable", "group_off")


def test_failed_call_with_nothing_cached_is_unavailable(monkeypatch):
    _patch_info(monkeypatch, _engine(), error=httpx.ConnectTimeout("timed out"))
    out = _overview()
    assert (out.status, out.reason) == ("unavailable", "fetch_failed")


def test_failed_refetch_serves_the_stale_row(monkeypatch):
    engine = _engine()
    _seed_info_cache(engine, "SPY", [SPY_INFO], age_days=10)
    _patch_info(monkeypatch, engine, error=httpx.ConnectTimeout("timed out"))
    out = _overview()
    assert out.status == "ok" and out.issuer == "SPDR"


def test_response_is_cached_for_the_configured_window(monkeypatch):
    engine = _engine()
    calls = _patch_info(monkeypatch, engine, [SPY_INFO])
    _overview()
    _overview()
    assert calls["n"] == 1
    with Session(engine) as session:
        row = session.exec(select(FundamentalsCache)).one()
    assert (row.statement_type, row.period) == ("etf_info", "latest")

    # Past the window it refetches.
    with Session(engine) as session:
        row = session.exec(select(FundamentalsCache)).one()
        row.fetched_at = datetime.now() - timedelta(days=etf_data.settings.etf_info_staleness_days + 1)
        session.add(row)
        session.commit()
    _overview()
    assert calls["n"] == 2


def test_overview_endpoint_returns_the_body_even_when_unavailable(monkeypatch):
    _patch_info(monkeypatch, _engine(), [SPY_INFO])
    dg.set_group_enabled("etf_info", False)
    with TestClient(main.app) as client:
        response = client.get("/api/tickers/spy/etf-overview")
    assert response.status_code == 200
    assert response.json()["status"] == "unavailable" and response.json()["ticker"] == "SPY"


# ---------------------------------------------------------------------------
# Known-ETF lookups
# ---------------------------------------------------------------------------


def _profile_row(ticker, **flags):
    return FundamentalsCache(
        ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(),
        raw_json=json.dumps([{"symbol": ticker, **flags}]),
    )


def test_known_etf_tickers_reads_profile_flags_and_score_rows_only():
    engine = _engine()
    with Session(engine) as session:
        session.add(_profile_row("QQQ", isEtf=True, isFund=False))
        session.add(_profile_row("PTY", isEtf=False, isFund=True))  # closed-end fund
        session.add(_profile_row("AAPL", isEtf=False, isFund=False))
        session.add(TickerScore(ticker="SPY", is_etf=True, computed_at=datetime.now()))
        session.add(TickerScore(ticker="MSFT", is_etf=False, computed_at=datetime.now()))
        session.commit()

        assert etf_data.known_etf_tickers(session) == {"QQQ", "PTY", "SPY"}
        assert etf_data.known_etf_tickers(session, ["aapl", "qqq", "NEVERSEEN"]) == {"QQQ"}
        assert etf_data.known_etf_tickers(session, []) == set()
        assert etf_data.is_known_etf(session, "pty") and not etf_data.is_known_etf(session, "MSFT")


# ---------------------------------------------------------------------------
# Add to watchlist (the "ETF" list)
# ---------------------------------------------------------------------------


def _main_engine(monkeypatch):
    engine = _engine()
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_the_etf_watchlist_name_is_a_monitored_name():
    assert ETF_WATCHLIST_NAME == "ETF" and is_monitored_watchlist_name(ETF_WATCHLIST_NAME)


def test_add_creates_the_etf_list_on_first_use_and_adds_the_ticker(monkeypatch):
    engine = _main_engine(monkeypatch)
    with TestClient(main.app) as client:
        response = client.post("/api/tickers/qqq/etf-watchlist")

    assert response.status_code == 200
    body = response.json()
    assert body["watchlist_name"] == "ETF" and body["added"] is True
    with Session(engine) as session:
        lists = session.exec(select(Watchlist)).all()
        tickers = session.exec(select(WatchlistTicker)).all()
    assert [w.name for w in lists] == ["ETF"]
    assert [(t.watchlist_id, t.ticker) for t in tickers] == [(body["watchlist_id"], "QQQ")]


def test_add_is_idempotent_and_reuses_the_existing_list(monkeypatch):
    engine = _main_engine(monkeypatch)
    with TestClient(main.app) as client:
        first = client.post("/api/tickers/QQQ/etf-watchlist").json()
        second = client.post("/api/tickers/QQQ/etf-watchlist")
        third = client.post("/api/tickers/SMH/etf-watchlist").json()

    assert second.status_code == 200 and second.json() == {**first, "added": False}
    assert third["watchlist_id"] == first["watchlist_id"] and third["added"] is True
    with Session(engine) as session:
        assert len(session.exec(select(Watchlist)).all()) == 1
        assert sorted(t.ticker for t in session.exec(select(WatchlistTicker)).all()) == ["QQQ", "SMH"]


def test_add_at_the_cap_is_rejected_with_a_clear_message_but_a_member_still_succeeds(monkeypatch):
    engine = _main_engine(monkeypatch)
    with Session(engine) as session:
        watchlist = Watchlist(name="ETF", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for i in range(main.WATCHLIST_CAPACITY):
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=f"E{i:04d}", added_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        full = client.post("/api/tickers/QQQ/etf-watchlist")
        member = client.post("/api/tickers/E0000/etf-watchlist")

    assert full.status_code == 400
    assert "100/100" in full.json()["detail"] and "ETF" in full.json()["detail"]
    assert member.status_code == 200 and member.json()["added"] is False  # idempotent even at the cap
    with Session(engine) as session:
        assert len(session.exec(select(WatchlistTicker)).all()) == 100


def test_watchlist_listing_flags_which_lists_are_monitored(monkeypatch):
    engine = _main_engine(monkeypatch)
    with Session(engine) as session:
        for name in ("E1", "ETF", "Growth", "W1", "E01"):
            session.add(Watchlist(name=name, created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1)))
        session.commit()
    with TestClient(main.app) as client:
        flags = {w["name"]: w["monitored"] for w in client.get("/api/watchlists").json()}
    assert flags == {"E1": True, "ETF": True, "Growth": False, "W1": False, "E01": False}


# ---------------------------------------------------------------------------
# Moat can't be set on an ETF / doesn't reach momentum
# ---------------------------------------------------------------------------


def test_moat_put_rejects_a_known_etf_and_still_accepts_a_stock(monkeypatch):
    engine = _main_engine(monkeypatch)
    with Session(engine) as session:
        session.add(_profile_row("QQQ", isEtf=True))
        session.add(_profile_row("AAPL", isEtf=False, isFund=False))
        session.commit()

    async def no_score(ticker, cache_only=False):
        return None

    monkeypatch.setattr(main, "compute_ticker_score", no_score)
    with TestClient(main.app) as client:
        etf = client.put("/api/tickers/QQQ/moat", json={"moat": "wide_moat"})
        stock = client.put("/api/tickers/AAPL/moat", json={"moat": "wide_moat"})

    assert etf.status_code == 400 and "ETF" in etf.json()["detail"]
    assert stock.status_code == 200
    with Session(engine) as session:
        assert session.get(TickerMoat, "QQQ") is None
        assert session.get(TickerMoat, "AAPL") is not None


def test_momentum_snapshot_excludes_a_moat_rated_etf(monkeypatch):
    engine = _engine()
    monkeypatch.setattr(momentum_data, "engine", engine)
    with Session(engine) as session:
        session.add(TickerScore(ticker="WIDE", moat="wide_moat", is_etf=False, computed_at=datetime.now()))
        session.add(TickerScore(ticker="QQQ", moat="wide_moat", is_etf=True, computed_at=datetime.now()))  # rated before the guard
        session.commit()
    index = pd.bdate_range(start="2024-08-01", end="2026-08-31")
    history = pd.DataFrame({"close": [100.0] * (len(index) - 1) + [150.0]}, index=index)

    monkeypatch.setattr(momentum_data, "load_tracked_universe", lambda session: ["WIDE", "QQQ"])

    async def fake_bars(tickers, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        return {t: history for t in tickers}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_bars)
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))

    summary = asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    assert summary["universe_size"] == 1
    with Session(engine) as session:
        assert [r.ticker for r in session.exec(select(MomentumSnapshot)).all()] == ["WIDE"]


# ---------------------------------------------------------------------------
# Search marker, watchlist-row flag, nightly fundamentals skip
# ---------------------------------------------------------------------------


def test_search_results_mark_known_etfs_only(monkeypatch):
    engine = _engine()
    monkeypatch.setattr(ticker_search, "engine", engine)
    with Session(engine) as session:
        session.add(_profile_row("QQQ", isEtf=True))
        session.add(_profile_row("QQ", isEtf=False))
        session.commit()

    async def symbol_matches(query, limit):
        return [
            {"symbol": "QQQ", "name": "Invesco QQQ Trust", "exchange": "NASDAQ"},
            {"symbol": "QQ", "name": "QQ Corp", "exchange": "NYSE"},
            {"symbol": "QQQM", "name": "Invesco NASDAQ 100 ETF", "exchange": "NASDAQ"},  # an ETF, but never seen
        ]

    async def name_matches(query, limit):
        return []

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", symbol_matches)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", name_matches)

    results = asyncio.run(ticker_search.search_tickers("QQ"))

    assert {r.symbol: r.is_etf for r in results} == {"QQQ": True, "QQ": False, "QQQM": False}


def test_tracked_universe_search_fallback_marks_known_etfs_too(monkeypatch):
    engine = _engine()
    monkeypatch.setattr(ticker_search, "engine", engine)
    with Session(engine) as session:
        session.add(TickerScore(ticker="QQQ", is_etf=True, computed_at=datetime.now()))
        session.add(TickerScore(ticker="QQ", is_etf=False, computed_at=datetime.now()))
        session.commit()
    dg.set_master(False)

    results = asyncio.run(ticker_search.search_tickers("QQ"))

    assert {r.symbol: r.is_etf for r in results} == {"QQ": False, "QQQ": True}


def test_watchlist_row_carries_is_etf_from_the_score_row(monkeypatch):
    async def fake_score(ticker, cache_only=False):
        return TickerScore(ticker=ticker, company_name="Invesco QQQ", is_etf=(ticker == "QQQ"), computed_at=datetime(2026, 1, 1))

    async def fake_consensus(ticker):
        return "N/A"

    async def fake_exchange(ticker):
        return "NASDAQ"

    async def fake_step1(ticker, cache_only=False):
        return Step1Out(
            ticker=ticker, years=[], revenue=[], net_income=[], operating_income=[], gross_margin=[], net_margin=[],
            score=0, verdict="n/a", components={}, weights={},
        )

    monkeypatch.setattr(watchlist_data, "compute_ticker_score", fake_score)
    monkeypatch.setattr(watchlist_data, "_consensus_rating", fake_consensus)
    monkeypatch.setattr(watchlist_data, "_cached_exchange", fake_exchange)
    monkeypatch.setattr(watchlist_data, "get_step1_data", fake_step1)
    rows = asyncio.run(
        watchlist_data.get_watchlist_rows(
            [WatchlistTicker(watchlist_id=1, ticker=t, added_at=datetime(2026, 1, 1)) for t in ("QQQ", "AAPL")]
        )
    )
    assert {r.ticker: r.is_etf for r in rows} == {"QQQ": True, "AAPL": False}


def test_fundamentals_fetch_universe_skips_known_etfs_but_the_full_universe_keeps_them(monkeypatch):
    engine = _engine()
    with Session(engine) as session:
        session.add(_profile_row("QQQ", isEtf=True))
        session.add(_profile_row("PTY", isFund=True))
        session.add(_profile_row("AAPL", isEtf=False, isFund=False))
        session.add(TickerScore(ticker="SPY", is_etf=True, computed_at=datetime.now()))
        session.add(TickerScore(ticker="MSFT", is_etf=False, computed_at=datetime.now()))
        session.add_all([TickerView(ticker=t, last_viewed_at=datetime.now()) for t in ("QQQ", "PTY", "AAPL", "SPY", "MSFT")])
        session.commit()

        assert nightly.load_tracked_universe(session) == ["AAPL", "MSFT", "PTY", "QQQ", "SPY"]
        assert nightly.load_fundamentals_fetch_universe(session) == ["AAPL", "MSFT"]


def test_nightly_main_fetches_only_non_etfs_from_the_universe(monkeypatch, tmp_path):
    engine = _engine()
    monkeypatch.setattr(nightly, "engine", engine)
    monkeypatch.setattr(nightly, "LOG_PATH", tmp_path / "nightly.log")
    with Session(engine) as session:
        session.add(_profile_row("QQQ", isEtf=True))
        session.add(_profile_row("AAPL", isEtf=False))
        session.add_all([TickerView(ticker=t, last_viewed_at=datetime.now()) for t in ("QQQ", "AAPL")])
        session.commit()

    fetched = []

    async def fake_step(ticker, **kwargs):
        fetched.append(ticker)

    async def fake_score(ticker, cache_only=False):
        return None

    for name in ("get_step1_data", "get_step2_data", "get_step4_data", "get_step5_data", "get_segmentation_data"):
        monkeypatch.setattr(nightly, name, fake_step)
    monkeypatch.setattr(nightly, "get_summary", fake_step)
    monkeypatch.setattr(nightly, "compute_ticker_score", fake_score)

    result = asyncio.run(nightly.main())

    assert result["processed"] == 1 and set(fetched) == {"AAPL"}


# ---------------------------------------------------------------------------
# etf_info tier default: Starter for a fresh seed, an existing row is never touched
# ---------------------------------------------------------------------------


def test_a_fresh_seed_creates_the_etf_info_row_at_starter():
    assert dg.get_snapshot().groups["etf_info"].required_tier == "Starter"


@pytest.mark.parametrize("edited_tier", ["Premium", "Ultimate", "Starter"])
def test_reseeding_never_overwrites_an_existing_etf_info_tier(edited_tier):
    dg.get_snapshot()  # first seed
    dg.set_required_tier("etf_info", edited_tier)
    dg.invalidate_cache()  # forces _load -> _seed again, as a restart would

    assert dg.get_snapshot().groups["etf_info"].required_tier == edited_tier


# ---------------------------------------------------------------------------
# Watchlist: an ETF row makes no consensus-rating call and carries the placeholder
# ---------------------------------------------------------------------------


def _watchlist_rows(monkeypatch, score_by_ticker):
    consensus_calls: list[str] = []

    async def fake_score(ticker, cache_only=False):
        return score_by_ticker.get(ticker)

    async def fake_consensus(ticker):
        consensus_calls.append(ticker)
        return "Buy"

    async def fake_exchange(ticker):
        return "NASDAQ"

    async def fake_step1(ticker, cache_only=False):
        return Step1Out(
            ticker=ticker, years=[], revenue=[], net_income=[], operating_income=[], gross_margin=[], net_margin=[],
            score=0, verdict="n/a", components={}, weights={},
        )

    monkeypatch.setattr(watchlist_data, "compute_ticker_score", fake_score)
    monkeypatch.setattr(watchlist_data, "_consensus_rating", fake_consensus)
    monkeypatch.setattr(watchlist_data, "_cached_exchange", fake_exchange)
    monkeypatch.setattr(watchlist_data, "get_step1_data", fake_step1)
    tickers = [WatchlistTicker(watchlist_id=1, ticker=t, added_at=datetime(2026, 1, 1)) for t in score_by_ticker]
    rows = asyncio.run(watchlist_data.get_watchlist_rows(tickers))
    return {r.ticker: r for r in rows}, consensus_calls


def test_an_etf_row_skips_the_consensus_call_and_a_stock_row_still_makes_it(monkeypatch):
    scores = {
        "QQQ": TickerScore(ticker="QQQ", company_name="Invesco QQQ", is_etf=True, computed_at=datetime(2026, 1, 1)),
        "AAPL": TickerScore(ticker="AAPL", company_name="Apple", is_etf=False, computed_at=datetime(2026, 1, 1)),
    }
    rows, consensus_calls = _watchlist_rows(monkeypatch, scores)

    assert consensus_calls == ["AAPL"]
    assert rows["QQQ"].consensus_rating == watchlist_data.NO_CONSENSUS_RATING == "N/A" and rows["QQQ"].is_etf
    assert rows["AAPL"].consensus_rating == "Buy"


def test_a_row_with_no_score_is_not_assumed_to_be_an_etf(monkeypatch):
    rows, consensus_calls = _watchlist_rows(monkeypatch, {"NEWCO": None})

    assert consensus_calls == ["NEWCO"] and rows["NEWCO"].is_etf is False


def test_the_real_consensus_fetch_is_not_reached_for_an_etf_and_writes_no_empty_row(monkeypatch):
    """End to end through the real _consensus_rating: an in-memory engine, FMP counted."""
    engine = _engine()
    monkeypatch.setattr(watchlist_data, "engine", engine)
    fmp_calls: list[str] = []

    async def fake_grades(ticker):
        fmp_calls.append(ticker)
        return []

    monkeypatch.setattr(watchlist_data.fmp_client, "get_grades_consensus", fake_grades)

    async def fake_score(ticker, cache_only=False):
        return TickerScore(ticker=ticker, company_name="x", is_etf=(ticker == "GLD"), computed_at=datetime(2026, 1, 1))

    async def fake_exchange(ticker):
        return "AMEX"

    async def fake_step1(ticker, cache_only=False):
        return Step1Out(
            ticker=ticker, years=[], revenue=[], net_income=[], operating_income=[], gross_margin=[], net_margin=[],
            score=0, verdict="n/a", components={}, weights={},
        )

    monkeypatch.setattr(watchlist_data, "compute_ticker_score", fake_score)
    monkeypatch.setattr(watchlist_data, "_cached_exchange", fake_exchange)
    monkeypatch.setattr(watchlist_data, "get_step1_data", fake_step1)
    asyncio.run(watchlist_data.get_watchlist_rows([WatchlistTicker(watchlist_id=1, ticker="GLD", added_at=datetime(2026, 1, 1))]))

    assert fmp_calls == []
    with Session(engine) as session:
        assert session.exec(select(FundamentalsCache)).all() == []
