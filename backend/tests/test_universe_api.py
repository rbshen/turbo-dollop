"""The opt-in universe API (step 3a): GET status (design state, cache-only), POST Add, DELETE Remove, the start-of-request
touch in GET /summary, and the immediate ETF row after a watchlist add. Mocks and temp in-memory databases only: no FMP
call, and the live database is never opened (conftest's write guard would fail the run)."""

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.data_groups as data_groups
import core.main as main
import data.etf_screener_refresh as etf_refresh
import data.tracked_universe as tu
import data.universe_membership as um
from clients.fmp_client import fmp_client
from core.exceptions import TickerNotFoundError
from core.models import EtfScreenerRow, FundamentalsCache, TickerScore, TickerView, Watchlist, WatchlistTicker
from wipe_seed import NOW, add_protection, make_engine


class Calls:
    """Records the mocked network-facing calls."""

    def __init__(self):
        self.compute: list[tuple[str, bool]] = []
        self.refresh: list[list[str]] = []
        self.profile: list[str] = []
        self.compute_raises: Exception | None = None
        self.compute_returns_none = False
        self.refresh_raises: Exception | None = None
        self.refresh_written = True
        self.refresh_errors: list[str] = []
        self.live_profile: list | dict | None = None  # what a live get_profile answers


@pytest.fixture
def env(monkeypatch):
    engine = make_engine()
    for module in (main, um, tu):
        monkeypatch.setattr(module, "engine", engine)
    calls = Calls()

    async def fake_compute(ticker, cache_only=False):
        calls.compute.append((ticker, cache_only))
        if calls.compute_raises is not None:
            raise calls.compute_raises
        if calls.compute_returns_none:
            return None
        return TickerScore(ticker=ticker, computed_at=NOW)

    class _Result:
        def __init__(self, written, errors):
            self.written, self.errors = written, errors

    async def fake_refresh(tickers=None, **kwargs):
        calls.refresh.append(list(tickers))
        if calls.refresh_raises is not None:
            raise calls.refresh_raises
        return {"results": {t: _Result(calls.refresh_written, list(calls.refresh_errors)) for t in tickers}}

    async def fake_get_profile(ticker):
        calls.profile.append(ticker)
        if calls.live_profile is None:
            raise AssertionError("a live profile call was not expected")
        return calls.live_profile

    monkeypatch.setattr(um, "compute_ticker_score", fake_compute)
    monkeypatch.setattr(um, "refresh_etf_screener", fake_refresh)
    monkeypatch.setattr(fmp_client, "get_profile", fake_get_profile)
    engine.calls = calls
    return engine


def _profile(engine, ticker, *, etf=False, exchange="NASDAQ", raw=None):
    body = raw if raw is not None else {"companyName": f"{ticker} Inc", "exchange": exchange, "isEtf": etf, "isFund": False}
    with Session(engine) as s:
        s.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json=json.dumps(body)))
        s.commit()


def _view(engine, ticker, *, days_ago=2, added=False, source="user"):
    with Session(engine) as s:
        s.add(
            TickerView(
                ticker=ticker, last_viewed_at=datetime.now() - timedelta(days=days_ago),
                added_at=NOW if added else None, added_source=source if added else None,
            )
        )
        s.commit()


def _status(engine, ticker):
    with TestClient(main.app) as client:
        response = client.get(f"/api/tickers/{ticker}/universe")
    assert response.status_code == 200
    return response.json()


def _row(engine, ticker):
    with Session(engine) as s:
        return s.get(TickerView, ticker)


# --- GET: the state matrix -------------------------------------------------------------------------------------------


def test_browsed_stock(env):
    _profile(env, "AAA")
    _view(env, "AAA")
    assert _status(env, "aaa") == {
        "ticker": "AAA", "kind": "stock", "in_universe": False, "state": "browsed", "reasons": [], "can_add": True,
        "can_remove": False, "added_at": None, "added_source": None, "delisted": False,
    }


def test_browsed_etf(env):
    _profile(env, "FUND", etf=True)
    body = _status(env, "FUND")
    assert body["kind"] == "etf" and body["state"] == "browsed" and body["can_add"] is True


def test_an_etf_is_recognised_by_a_score_row_alone(env):
    with Session(env) as s:
        s.add(TickerScore(ticker="OLDETF", computed_at=NOW, is_etf=True))
        s.commit()
    assert _status(env, "OLDETF")["kind"] == "etf"


def test_added(env):
    _profile(env, "ADD")
    _view(env, "ADD", added=True, source="grandfathered")
    body = _status(env, "ADD")
    assert (body["state"], body["in_universe"], body["can_add"], body["can_remove"]) == ("added", True, False, True)
    assert body["added_source"] == "grandfathered" and body["added_at"] is not None and body["reasons"] == []


@pytest.mark.parametrize(
    "kind, reason",
    [
        ("index:sp500", "index:sp500"),
        ("index:nasdaq", "index:nasdaq"),
        ("index:dow", "index:dow"),
        ("index:russell2000", "index:russell2000"),
        ("watchlist", "watchlist:L-PROT"),
        ("moat", "manual:moat"),
        ("custom_valuation", "manual:custom_valuation"),
        ("bank_capital", "manual:bank_capital"),
        ("growth_note", "manual:growth_note"),
        ("rs_benchmark", "rs_benchmark"),
    ],
)
def test_each_protection_alone_makes_a_ticker_protected(env, kind, reason):
    _profile(env, "PROT")
    _view(env, "PROT")
    add_protection(env, kind, "PROT")
    body = _status(env, "PROT")
    assert (body["state"], body["in_universe"], body["reasons"]) == ("protected", True, [reason])
    assert body["can_add"] is False and body["can_remove"] is False


def test_a_seed_and_the_benchmark_constant_are_protected(env, monkeypatch):
    _profile(env, "XLK", etf=True)
    assert _status(env, "XLK")["reasons"] == ["seed"]
    monkeypatch.setattr(tu, "ETF_SEED_TICKERS", frozenset())
    _profile(env, tu.WEINSTEIN_BENCHMARK_TICKER, etf=True)
    assert _status(env, tu.WEINSTEIN_BENCHMARK_TICKER)["reasons"] == ["benchmark"]


def test_several_protections_are_all_listed_in_a_stable_order(env):
    _profile(env, "MANY")
    add_protection(env, "index:sp500", "MANY")
    add_protection(env, "watchlist", "MANY")
    add_protection(env, "moat", "MANY")
    assert _status(env, "MANY")["reasons"] == ["index:sp500", "watchlist:L-MANY", "manual:moat"]


def test_added_and_protected_reads_protected_and_keeps_its_added_fields(env):
    """Watchlisted after being added: protected for as long as the list holds it, added_at untouched, Remove not offered."""
    _profile(env, "BOTH")
    _view(env, "BOTH", added=True)
    add_protection(env, "watchlist", "BOTH")
    body = _status(env, "BOTH")
    assert (body["state"], body["can_remove"], body["can_add"]) == ("protected", False, False)
    assert body["added_at"] is not None and body["added_source"] == "user"
    # taken off the list: back to "added" with the same added_at (a watchlist change never writes added_at)
    with Session(env) as s:
        for row in s.exec(select(WatchlistTicker)).all():
            s.delete(row)
        s.commit()
    again = _status(env, "BOTH")
    assert (again["state"], again["can_remove"]) == ("added", True) and again["added_at"] == body["added_at"]


def test_a_ticker_only_ever_watchlisted_falls_back_to_browsed_when_taken_off(env):
    _profile(env, "WLONLY")
    _view(env, "WLONLY")
    add_protection(env, "watchlist", "WLONLY")
    assert _status(env, "WLONLY")["state"] == "protected"
    with Session(env) as s:
        for row in s.exec(select(WatchlistTicker)).all():
            s.delete(row)
        s.commit()
    assert _status(env, "WLONLY")["state"] == "browsed"


def test_delisted_rules(env):
    for ticker in ("DLB", "DLA"):
        _profile(env, ticker)
        with Session(env) as s:
            s.add(TickerScore(ticker=ticker, computed_at=NOW, delisted_at=NOW))
            s.commit()
    _view(env, "DLB")
    _view(env, "DLA", added=True)
    browsed, added = _status(env, "DLB"), _status(env, "DLA")
    assert browsed["delisted"] and browsed["can_add"] is False  # add only when not delisted
    assert added["delisted"] and added["can_remove"] is True  # a delisted added ticker can still be removed


def test_a_non_us_profile_cannot_be_added(env):
    _profile(env, "HKX", exchange="HKSE")
    assert _status(env, "HKX")["can_add"] is False


def test_a_never_seen_ticker_has_no_kind_and_get_makes_no_call_and_no_write(env):
    statements = []

    @event.listens_for(env, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    body = _status(env, "NEVERSEEN")
    assert (body["kind"], body["state"], body["can_add"], body["in_universe"]) == (None, "browsed", True, False)
    assert env.calls.profile == [] and env.calls.compute == [] and env.calls.refresh == []
    assert not [s for s in statements if s.startswith(("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER"))]


def test_get_never_touches_tickerview(env):
    _profile(env, "AAA")
    _view(env, "AAA", days_ago=40)
    before = _row(env, "AAA").last_viewed_at
    for _ in range(3):
        _status(env, "AAA")
    assert _row(env, "AAA").last_viewed_at == before
    _status(env, "NOROW")
    assert _row(env, "NOROW") is None


def test_the_protection_reasons_agree_with_the_wipe_candidate_logic(env):
    kinds = [None, "index:sp500", "index:russell2000", "watchlist", "moat", "custom_valuation", "bank_capital", "growth_note", "rs_benchmark"]
    for i, kind in enumerate(kinds):
        ticker = f"T{i}"
        _view(env, ticker, days_ago=90)
        if kind:
            add_protection(env, kind, ticker)
    with Session(env) as s:
        for i in range(len(kinds)):
            ticker = f"T{i}"
            wipe = tu.classify_wipe_candidates(s, NOW, tickers=[ticker])[ticker]
            assert bool(tu.load_protection_reasons(s, ticker)) == bool(wipe.protections), ticker


def test_every_manual_table_has_a_label():
    from data.ticker_data_registry import MANUAL_DATA_LABELS, MANUAL_DATA_MODELS

    assert {m.__tablename__ for m in MANUAL_DATA_MODELS} == set(MANUAL_DATA_LABELS)


# --- POST: Add ---------------------------------------------------------------------------------------------------


def _post(path):
    with TestClient(main.app) as client:
        return client.post(path)


def _delete(path):
    with TestClient(main.app) as client:
        return client.delete(path)


def test_add_a_stock_commits_first_then_computes_the_score(env):
    _profile(env, "STK")
    _view(env, "STK", days_ago=5)
    seen_at_compute = {}
    original = um.compute_ticker_score

    async def spying(ticker, cache_only=False):
        with Session(env) as s:  # a separate read: the add must already be committed
            seen_at_compute["added_at"] = s.get(TickerView, ticker).added_at
        return await original(ticker, cache_only=cache_only)

    um.compute_ticker_score = spying
    try:
        response = _post("/api/tickers/stk/universe")
    finally:
        um.compute_ticker_score = original
    body = response.json()
    assert response.status_code == 200
    assert body["changed"] is True and body["score_computed"] is True and body["row_written"] is None
    assert body["status"]["state"] == "added" and body["status"]["added_source"] == "user" and body["status"]["can_remove"] is True
    assert seen_at_compute["added_at"] is not None
    assert env.calls.compute == [("STK", False)] and env.calls.refresh == [] and env.calls.profile == []
    row = _row(env, "STK")
    assert row.added_source == "user" and abs((datetime.now() - row.last_viewed_at) - timedelta(days=5)) < timedelta(minutes=1)  # last_viewed_at kept


def test_add_creates_a_tickerview_row_when_there_is_none(env):
    _profile(env, "STK")
    assert _row(env, "STK") is None
    _post("/api/tickers/STK/universe")
    row = _row(env, "STK")
    assert row.added_at is not None and datetime.now() - row.last_viewed_at < timedelta(minutes=1)


def test_add_an_etf_writes_its_row_through_refresh_etf_screener(env):
    _profile(env, "FUND", etf=True)
    body = _post("/api/tickers/FUND/universe").json()
    assert body["changed"] is True and body["row_written"] is True and body["score_computed"] is None
    assert env.calls.refresh == [["FUND"]] and env.calls.compute == []
    assert body["status"]["kind"] == "etf" and body["status"]["state"] == "added"


def test_add_an_etf_that_computes_nothing_says_it_appears_tonight(env):
    _profile(env, "FUND", etf=True)
    env.calls.refresh_written = False
    body = _post("/api/tickers/FUND/universe").json()
    assert body["row_written"] is False and body["reason"] == "no_data" and "tonight" in body["message"]
    assert body["status"]["state"] == "added"


def test_add_is_idempotent_and_never_overwrites(env):
    _profile(env, "STK")
    _view(env, "STK")
    first = _post("/api/tickers/STK/universe").json()
    second = _post("/api/tickers/STK/universe").json()
    assert first["changed"] is True and second["changed"] is False
    assert second["status"]["added_at"] == first["status"]["added_at"] and second["status"]["added_source"] == "user"
    assert env.calls.compute == [("STK", False)]  # the repeat computed nothing


def test_add_does_not_overwrite_a_grandfathered_ticker(env):
    _profile(env, "OLD")
    _view(env, "OLD", added=True, source="grandfathered")
    body = _post("/api/tickers/OLD/universe").json()
    assert body["changed"] is False and body["status"]["added_source"] == "grandfathered"
    assert _row(env, "OLD").added_source == "grandfathered"


def test_add_a_protected_ticker_is_a_no_op_with_no_write(env):
    _profile(env, "IDX")
    add_protection(env, "index:sp500", "IDX")
    body = _post("/api/tickers/IDX/universe").json()
    assert body["changed"] is False and body["status"]["state"] == "protected" and "index:sp500" in body["message"]
    assert _row(env, "IDX") is None and env.calls.compute == []


def test_add_rejects_non_us_and_delisted_without_writing(env):
    _profile(env, "HKX", exchange="HKSE")
    non_us = _post("/api/tickers/HKX/universe")
    assert non_us.status_code == 400 and "US-listed" in non_us.json()["detail"]
    _profile(env, "DEAD")
    with Session(env) as s:
        s.add(TickerScore(ticker="DEAD", computed_at=NOW, delisted_at=NOW))
        s.commit()
    delisted = _post("/api/tickers/DEAD/universe")
    assert delisted.status_code == 409 and "delisted" in delisted.json()["detail"]
    assert _row(env, "HKX") is None and _row(env, "DEAD") is None and env.calls.compute == []


def test_add_a_cached_empty_profile_is_a_404_and_writes_nothing(env):
    _profile(env, "GHOST", raw=[])
    response = _post("/api/tickers/GHOST/universe")
    assert response.status_code == 404 and _row(env, "GHOST") is None and env.calls.compute == []


def test_add_a_never_seen_ticker_with_an_empty_live_profile_is_a_404_and_writes_nothing(env):
    env.calls.live_profile = []
    response = _post("/api/tickers/GHOST/universe")
    assert response.status_code == 404 and env.calls.profile == ["GHOST"]
    with Session(env) as s:
        assert s.exec(select(FundamentalsCache)).all() == [] and s.exec(select(TickerView)).all() == []


def test_add_a_never_seen_ticker_costs_one_live_profile_call_and_caches_it(env):
    env.calls.live_profile = [{"companyName": "New Co", "exchange": "NYSE", "isEtf": False}]
    body = _post("/api/tickers/newco/universe").json()
    assert env.calls.profile == ["NEWCO"] and body["changed"] is True and body["status"]["kind"] == "stock"
    with Session(env) as s:
        assert s.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type == "profile")).one().ticker == "NEWCO"


def test_add_with_the_profile_group_off_and_nothing_cached_is_a_503(env):
    data_groups.set_group_enabled("profile_quote", False)
    response = _post("/api/tickers/NEWCO/universe")
    assert response.status_code == 503 and _row(env, "NEWCO") is None


def test_add_a_stock_with_the_fundamentals_group_off_falls_back_to_cache_only(env):
    _profile(env, "STK")
    data_groups.set_group_enabled("fundamentals", False)
    body = _post("/api/tickers/STK/universe").json()
    assert body["changed"] is True and body["score_computed"] is False and body["reason"] == "fundamentals_group_off"
    assert env.calls.compute == [("STK", True)]  # cache-only: zero FMP calls
    assert _row(env, "STK").added_at is not None


def test_add_an_etf_with_the_daily_prices_group_off_skips_the_refresh(env):
    _profile(env, "FUND", etf=True)
    data_groups.set_group_enabled("daily_prices", False)
    body = _post("/api/tickers/FUND/universe").json()
    assert body["row_written"] is False and body["reason"] == "daily_prices_group_off" and env.calls.refresh == []
    assert _row(env, "FUND").added_at is not None


def test_a_failed_stock_compute_still_leaves_the_ticker_added(env):
    _profile(env, "STK")
    env.calls.compute_raises = RuntimeError("boom https://x/y?apikey=SECRET123")
    response = _post("/api/tickers/STK/universe")
    body = response.json()
    assert response.status_code == 200 and body["changed"] is True and body["score_computed"] is False and body["reason"] == "failed"
    assert "SECRET123" not in body["error"] and "boom" in body["error"]
    assert _row(env, "STK").added_at is not None and body["status"]["state"] == "added"


def test_a_stock_compute_with_no_data_still_leaves_the_ticker_added(env):
    _profile(env, "STK")
    env.calls.compute_returns_none = True
    body = _post("/api/tickers/STK/universe").json()
    assert body["score_computed"] is False and body["reason"] == "no_data" and body["status"]["state"] == "added"


def test_a_failed_etf_refresh_still_leaves_the_ticker_added(env):
    _profile(env, "FUND", etf=True)
    env.calls.refresh_raises = RuntimeError("fmp down")
    body = _post("/api/tickers/FUND/universe").json()
    assert body["row_written"] is False and body["reason"] == "failed" and "fmp down" in body["error"]
    assert _row(env, "FUND").added_at is not None


# --- DELETE: Remove ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["index:sp500", "index:russell2000", "watchlist", "moat", "custom_valuation", "bank_capital", "growth_note", "rs_benchmark"])
def test_remove_is_refused_with_the_reasons_while_any_protection_applies(env, kind):
    _profile(env, "PROT")
    _view(env, "PROT", added=True)
    add_protection(env, kind, "PROT")
    response = _delete("/api/tickers/PROT/universe")
    assert response.status_code == 409 and "cannot be removed" in response.json()["detail"]
    assert _row(env, "PROT").added_at is not None  # untouched


def test_remove_a_seed_is_refused(env):
    _profile(env, "XLK", etf=True)
    assert _delete("/api/tickers/XLK/universe").status_code == 409


def test_remove_is_a_no_op_when_not_added(env):
    _profile(env, "AAA")
    _view(env, "AAA")
    response = _delete("/api/tickers/AAA/universe")
    assert response.status_code == 200 and response.json()["changed"] is False
    assert _delete("/api/tickers/NEVERSEEN/universe").json()["changed"] is False
    assert _row(env, "NEVERSEEN") is None


def test_remove_a_stock_clears_only_the_two_columns_and_leaves_everything_else(env):
    _profile(env, "STK")
    _view(env, "STK", days_ago=7, added=True)
    with Session(env) as s:
        s.add(TickerScore(ticker="STK", computed_at=NOW))
        s.commit()
    before = _row(env, "STK").last_viewed_at
    body = _delete("/api/tickers/STK/universe").json()
    assert body["changed"] is True and body["status"]["state"] == "browsed" and body["status"]["can_add"] is True
    row = _row(env, "STK")
    assert (row.added_at, row.added_source) == (None, None) and row.last_viewed_at == before  # last_viewed_at untouched
    with Session(env) as s:
        assert s.get(TickerScore, "STK") is not None  # the wipe handles it later
        assert s.exec(select(FundamentalsCache)).all()


def test_remove_an_etf_deletes_its_screener_row(env):
    _profile(env, "FUND", etf=True)
    _view(env, "FUND", added=True)
    with Session(env) as s:
        s.add(EtfScreenerRow(ticker="FUND"))
        s.add(EtfScreenerRow(ticker="OTHER"))
        s.commit()
    body = _delete("/api/tickers/FUND/universe").json()
    assert body["changed"] is True and body["status"]["kind"] == "etf"
    with Session(env) as s:
        assert [r.ticker for r in s.exec(select(EtfScreenerRow)).all()] == ["OTHER"]


def test_add_then_remove_then_add_again(env):
    _profile(env, "STK")
    _view(env, "STK")
    _post("/api/tickers/STK/universe")
    _delete("/api/tickers/STK/universe")
    again = _post("/api/tickers/STK/universe").json()
    assert again["changed"] is True and again["status"]["state"] == "added"


# --- the touch moves to the start of GET /summary -------------------------------------------------------------------


def test_an_existing_row_is_touched_before_the_summary_work(env, monkeypatch):
    async def _scenario():
        _view(env, "AAA", days_ago=3, added=True, source="grandfathered")
        seen = {}

        async def fake_summary(ticker, **kwargs):
            seen["during"] = _row(env, "AAA").last_viewed_at
            return "summary"

        monkeypatch.setattr(main, "get_summary", fake_summary)
        result = await main.ticker_summary("aaa")
        assert result == "summary"
        assert seen["during"].date() == datetime.now().date()  # already touched while the summary was being built
        row = _row(env, "AAA")
        assert (row.added_source, row.added_at) == ("grandfathered", NOW)  # the added fields are never altered

    asyncio.run(_scenario())
def test_a_new_ticker_gets_its_row_only_after_the_summary_succeeds(env, monkeypatch):
    async def _scenario():
        seen = {}

        async def fake_summary(ticker, **kwargs):
            seen["during"] = _row(env, "NEW")
            return "summary"

        monkeypatch.setattr(main, "get_summary", fake_summary)
        await main.ticker_summary("NEW")
        assert seen["during"] is None  # no row while the summary is built
        assert _row(env, "NEW") is not None

    asyncio.run(_scenario())
def test_no_row_is_created_for_a_404(env, monkeypatch):
    async def _scenario():
        async def missing(ticker, **kwargs):
            raise TickerNotFoundError(ticker)

        monkeypatch.setattr(main, "get_summary", missing)
        with pytest.raises(Exception) as exc:
            await main.ticker_summary("BADSYM")
        assert getattr(exc.value, "status_code", None) == 404
        assert _row(env, "BADSYM") is None

    asyncio.run(_scenario())
def test_the_touch_stays_at_most_once_per_calendar_day(env, monkeypatch):
    async def _scenario():
        async def fake_summary(ticker, **kwargs):
            return "summary"

        monkeypatch.setattr(main, "get_summary", fake_summary)
        _view(env, "AAA", days_ago=2)
        await main.ticker_summary("AAA")
        first = _row(env, "AAA").last_viewed_at
        await main.ticker_summary("AAA")
        await main.ticker_summary("AAA")
        assert _row(env, "AAA").last_viewed_at == first  # same day: no further write

    asyncio.run(_scenario())
def test_touch_existing_ticker_view_unit(env):
    morning, evening, next_day = datetime(2026, 11, 15, 9), datetime(2026, 11, 15, 21), datetime(2026, 11, 16, 8)
    assert tu.touch_existing_ticker_view("NOROW", now=morning) is False
    assert _row(env, "NOROW") is None  # never creates
    with Session(env) as s:
        s.add(TickerView(ticker="AAA", last_viewed_at=datetime(2026, 11, 14, 9), added_at=NOW, added_source="user"))
        s.commit()
    assert tu.touch_existing_ticker_view("aaa", now=morning) is True
    assert tu.touch_existing_ticker_view("AAA", now=evening) is False
    assert tu.touch_existing_ticker_view("AAA", now=next_day) is True
    row = _row(env, "AAA")
    assert row.last_viewed_at == next_day and (row.added_at, row.added_source) == (NOW, "user")


# --- watchlist adds: the ETF's card is written at once, best effort ------------------------------------------------


def _watchlist(env, name="Test"):
    with Session(env) as s:
        w = Watchlist(name=name, created_at=NOW, updated_at=NOW)
        s.add(w)
        s.commit()
        return w.id


def test_the_etf_list_endpoint_writes_the_missing_row_now(env):
    _profile(env, "FUND", etf=True)
    response = _post("/api/tickers/fund/etf-watchlist")
    assert response.status_code == 200 and response.json()["added"] is True
    assert env.calls.refresh == [["FUND"]]


def test_the_generic_add_writes_the_missing_etf_row_but_not_for_a_stock(env):
    _profile(env, "FUND", etf=True)
    _profile(env, "STK")
    wid = _watchlist(env)
    with TestClient(main.app) as client:
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "FUND"}).status_code == 201
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "STK"}).status_code == 201
    assert env.calls.refresh == [["FUND"]]  # the stock add triggered nothing


def test_an_etf_that_already_has_a_row_is_not_refreshed_again(env):
    _profile(env, "FUND", etf=True)
    with Session(env) as s:
        s.add(EtfScreenerRow(ticker="FUND"))
        s.commit()
    _post("/api/tickers/FUND/etf-watchlist")
    assert env.calls.refresh == []


def test_an_unknown_ticker_gets_no_immediate_write(env):
    wid = _watchlist(env)
    with TestClient(main.app) as client:
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "NEVERSEEN"}).status_code == 201
    assert env.calls.refresh == []


def test_a_failing_refresh_never_fails_the_watchlist_add(env):
    _profile(env, "FUND", etf=True)
    env.calls.refresh_raises = RuntimeError("fmp down")
    response = _post("/api/tickers/FUND/etf-watchlist")
    assert response.status_code == 200 and response.json()["added"] is True
    with Session(env) as s:
        assert [t.ticker for t in s.exec(select(WatchlistTicker)).all()] == ["FUND"]


def test_the_immediate_write_is_skipped_while_daily_prices_is_off(env):
    _profile(env, "FUND", etf=True)
    data_groups.set_group_enabled("daily_prices", False)
    assert _post("/api/tickers/FUND/etf-watchlist").json()["added"] is True
    assert env.calls.refresh == []


def test_a_bulk_add_makes_one_call_for_at_most_a_few_etfs(env):
    names = [f"ETF{i}" for i in range(8)]
    for name in names:
        _profile(env, name, etf=True)
    _profile(env, "STK")
    wid = _watchlist(env)
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": names + ["STK"]})
    assert response.status_code == 200 and response.json()["added"] == 9
    assert len(env.calls.refresh) == 1 and env.calls.refresh[0] == names[: um.MAX_IMMEDIATE_ETF_ROWS]


def test_ensure_etf_screener_rows_never_raises(env, monkeypatch):
    async def _scenario():
        def boom(*a, **k):
            raise RuntimeError("db gone")

        monkeypatch.setattr(um, "known_etf_tickers", boom)
        assert await um.ensure_etf_screener_rows(["FUND"]) == []

    asyncio.run(_scenario())
# --- the classification is untouched by any of this ---------------------------------------------------------------


def test_universes_and_reasons_are_unchanged_by_status_add_and_remove(env):
    for ticker, etf in (("STK", False), ("OLDSTK", False), ("FUND", True), ("OLDFUND", True), ("IDX", False)):
        _profile(env, ticker, etf=etf)
    _view(env, "STK", days_ago=3)
    _view(env, "OLDSTK", days_ago=60)
    _view(env, "FUND", days_ago=3)
    _view(env, "OLDFUND", days_ago=60)
    add_protection(env, "index:sp500", "IDX")

    def snapshot():
        with Session(env) as s:
            return (
                tu.load_tracked_universe(s, datetime.now()), tu.load_etf_universe(s, datetime.now()),
                tu.classify_known_tickers(s, datetime.now()), tu.classify_etf_tickers(s, datetime.now()),
                tu.load_expired_tickers(s, datetime.now()), tu.load_expired_etfs(s, datetime.now()),
            )

    before = snapshot()
    for ticker in ("STK", "OLDSTK", "FUND", "OLDFUND", "IDX"):
        _status(env, ticker)
        _post(f"/api/tickers/{ticker}/universe")
        _status(env, ticker)
    assert snapshot() == before  # added state is invisible to every universe (the flip is a later step)
    for ticker in ("STK", "OLDSTK", "FUND", "OLDFUND", "IDX"):
        _delete(f"/api/tickers/{ticker}/universe")
    assert snapshot() == before
    assert before[2]["OLDSTK"] == tu.EXPIRED  # an added-then-removed expired ticker still expires today
