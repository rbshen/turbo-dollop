"""data/tracked_universe.py: the one definition of the nightly universe (rules a-e, delisted exclusion,
30-day expiry), view recording, the init_db seed that gives every existing ticker 30 days of grace, and the
guard that every job and the Screener read the helper instead of re-declaring the union. Each test builds
its own in-memory engine and patches it onto every module that reads (the per-module convention)."""

import asyncio
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.db as db
import core.main as main
import data.momentum_data as momentum_data
import data.tracked_universe as tu
from core.models import (
    FundamentalsCache,
    IndexConstituent,
    MomentumSnapshot,
    TickerBankCapitalMetrics,
    TickerCustomValuation,
    TickerMoat,
    TickerScore,
    TickerView,
    Watchlist,
    WatchlistTicker,
)

NOW = datetime(2026, 11, 15, 12, 0)


@pytest.fixture
def engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for module in (tu, db, main, momentum_data):
        monkeypatch.setattr(module, "engine", engine)
    return engine


def _profile(session, ticker):
    session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW, raw_json="{}"))


def _viewed(session, ticker, days_ago):
    session.add(TickerView(ticker=ticker, last_viewed_at=NOW - timedelta(days=days_ago)))


def _universe(engine, now=NOW):
    with Session(engine) as session:
        return tu.load_tracked_universe(session, now)


def _reasons(engine, now=NOW):
    with Session(engine) as session:
        return tu.classify_known_tickers(session, now)


# --- the rules ------------------------------------------------------------------------------------


def test_each_rule_puts_a_ticker_in_and_a_viewed_only_ticker_expires(engine):
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        session.add(IndexConstituent(index_name="dow", ticker="DOW", company_name="d", last_synced_at=NOW))
        session.add(IndexConstituent(index_name="nasdaq", ticker="NDQ", company_name="n", last_synced_at=NOW))
        watchlist = Watchlist(name="Scratch list", created_at=NOW, updated_at=NOW)  # not monitored: still counts
        session.add(watchlist)
        session.commit()
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="WL", added_at=NOW))
        for ticker in ("VIEWED", "STALEVIEW", "NEVER"):
            _profile(session, ticker)
        _viewed(session, "VIEWED", 3)
        _viewed(session, "STALEVIEW", 45)
        session.commit()

    reasons = _reasons(engine)
    assert reasons["IDX"] == reasons["DOW"] == reasons["NDQ"] == tu.INDEX
    assert reasons["WL"] == tu.WATCHLIST
    assert reasons["VIEWED"] == tu.VIEWED
    assert reasons["STALEVIEW"] == tu.EXPIRED and reasons["NEVER"] == tu.EXPIRED
    assert _universe(engine) == ["DOW", "IDX", "NDQ", "VIEWED", "WL"]


def test_an_index_row_under_another_index_name_is_not_membership(engine):
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="other-index", ticker="XYZ", company_name="x", last_synced_at=NOW))
        _profile(session, "XYZ")
        session.commit()
    assert _universe(engine) == []


@pytest.mark.parametrize("days_ago, expected_in", [(0, True), (29, True), (30, True), (31, False), (200, False)])
def test_the_view_window_boundary_is_30_days(engine, days_ago, expected_in):
    with Session(engine) as session:
        _profile(session, "AAA")
        _viewed(session, "AAA", days_ago)
        session.commit()
    assert ("AAA" in _universe(engine)) is expected_in


def test_manual_data_protects_a_ticker_that_was_never_viewed_again(engine):
    with Session(engine) as session:
        for ticker in ("MOAT", "CUSTOM", "BANK", "PLAIN"):
            _profile(session, ticker)
            _viewed(session, ticker, 400)
        session.add(TickerMoat(ticker="MOAT", moat="wide_moat", updated_at=NOW))
        session.add(TickerCustomValuation(ticker="CUSTOM", method="DCF", parameters_json="{}", is_active=False, saved_at=NOW))
        session.add(TickerBankCapitalMetrics(ticker="BANK", updated_at=NOW))
        session.commit()

    reasons = _reasons(engine)
    assert {reasons[t] for t in ("MOAT", "CUSTOM", "BANK")} == {tu.MANUAL}
    assert reasons["PLAIN"] == tu.EXPIRED
    assert _universe(engine) == ["BANK", "CUSTOM", "MOAT"]


def test_manual_data_for_a_ticker_the_app_does_not_know_adds_nothing(engine):
    with Session(engine) as session:
        session.add(TickerMoat(ticker="GHOST", moat="no_moat", updated_at=NOW))  # no profile, score or view
        session.commit()
    assert _universe(engine) == []


def test_system_tickers_is_retired_and_no_seed_is_ever_on_the_stock_side(engine):
    """Cutover 2026-10-03: SPY and the sector SPDRs are ETFs, protected on the ETF side by ETF_SEED_TICKERS; the stock
    universe holds none of them, even with a profile row, a view, a watchlist entry or a score row."""
    assert not hasattr(tu, "SYSTEM_TICKERS")
    with Session(engine) as session:
        for ticker in ("XLK", "SPY", "XLB"):
            _profile(session, ticker)  # even a profile row without the ETF flag
        _viewed(session, "XLK", 1)
        session.add(TickerScore(ticker="XLB", computed_at=NOW, is_etf=False))
        session.commit()
        stock_side, _ = tu.partition_known_tickers(session)
    assert _universe(engine) == [] and stock_side == set()


def test_a_delisted_flag_removes_a_ticker_even_from_an_index_or_a_watchlist(engine):
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="EQR", company_name="e", last_synced_at=NOW))
        session.add(TickerScore(ticker="EQR", computed_at=NOW, delisted_at=NOW))
        session.add(TickerScore(ticker="EA", computed_at=NOW, delisted_at=NOW))
        session.add(TickerMoat(ticker="EA", moat="narrow_moat", updated_at=NOW))
        _viewed(session, "EA", 1)
        session.commit()

    assert _reasons(engine) == {"EQR": tu.DELISTED, "EA": tu.DELISTED}
    assert _universe(engine) == []


def test_re_viewing_an_expired_ticker_puts_it_back(engine):
    with Session(engine) as session:
        _profile(session, "AAA")
        _viewed(session, "AAA", 90)
        session.commit()
    assert _universe(engine) == []

    assert tu.record_ticker_view("aaa", now=NOW) is True

    assert _universe(engine) == ["AAA"]


def test_the_wide_known_set_never_expires_and_keeps_delisted_tickers(engine):
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        _profile(session, "OLD")
        session.add(TickerScore(ticker="GONE", computed_at=NOW, delisted_at=NOW))
        session.add(FundamentalsCache(ticker="EURUSD", statement_type="forex_rate", period="latest", fetched_at=NOW, raw_json="[]"))
        _viewed(session, "OLD", 500)
        session.commit()
        wide = tu.load_all_known_tickers(session)

    assert wide == ["GONE", "IDX", "OLD"]  # an FX pair is not a ticker
    assert set(_universe(engine)) < set(wide)  # the nightly universe is always a subset of the wide set


# --- the ETF side (additive: nothing reads it yet) --------------------------------------------------

ETF_PROFILE = '{"isEtf": true}'


def _etf(session, ticker, days_ago=None, *, fund=False):
    """A known ETF: a cached profile carrying the flag, optionally viewed `days_ago` days before NOW."""
    flag = "isFund" if fund else "isEtf"
    session.add(
        FundamentalsCache(
            ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW, raw_json=f'{{"{flag}": true}}'
        )
    )
    if days_ago is not None:
        _viewed(session, ticker, days_ago)


def _etf_reasons(engine, now=NOW):
    with Session(engine) as session:
        return tu.classify_etf_tickers(session, now)


def _etf_universe(engine, now=NOW):
    with Session(engine) as session:
        return tu.load_etf_universe(session, now)


def test_etf_seed_tickers_are_spy_plus_the_sector_etfs():
    from data.sector_heatmap_data import SECTOR_ETFS

    assert tu.ETF_SEED_TICKERS == {"SPY"} | {symbol for symbol, _ in SECTOR_ETFS}
    assert len(tu.ETF_SEED_TICKERS) == 12


def test_seeds_are_in_the_etf_universe_with_no_profile_row_and_no_view(engine):
    reasons = _etf_reasons(engine)  # an empty database
    assert set(reasons) == set(tu.ETF_SEED_TICKERS)
    assert set(reasons.values()) == {tu.SYSTEM}
    assert _etf_universe(engine) == sorted(tu.ETF_SEED_TICKERS)


def test_each_etf_reason(engine):
    with Session(engine) as session:
        _etf(session, "RECENT", 3)
        _etf(session, "OLDVIEW", 45)
        _etf(session, "NEVERVIEWED")
        _etf(session, "GONE", 1)
        session.add(TickerScore(ticker="GONE", computed_at=NOW, delisted_at=NOW))
        _etf(session, "SPY", 400)  # a seed the app has seen, long unviewed
        watchlist = Watchlist(name="Scratch list", created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        _etf(session, "WLETF", 400)
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="WLETF", added_at=NOW))
        session.commit()

    reasons = _etf_reasons(engine)
    assert reasons["RECENT"] == tu.VIEWED
    assert reasons["OLDVIEW"] == tu.EXPIRED and reasons["NEVERVIEWED"] == tu.EXPIRED
    assert reasons["GONE"] == tu.DELISTED
    assert reasons["WLETF"] == tu.WATCHLIST
    assert reasons["SPY"] == tu.SYSTEM
    universe = _etf_universe(engine)
    assert {"RECENT", "WLETF", "SPY"} <= set(universe)
    assert not {"OLDVIEW", "NEVERVIEWED", "GONE"} & set(universe)
    assert set(universe) == set(tu.ETF_SEED_TICKERS) | {"RECENT", "WLETF"}


def test_an_etf_on_any_watchlist_never_expires_monitored_or_not(engine):
    with Session(engine) as session:
        plain = Watchlist(name="Anything", created_at=NOW, updated_at=NOW)
        monitored = Watchlist(name="ETF", created_at=NOW, updated_at=NOW)
        session.add_all([plain, monitored])
        session.commit()
        for ticker, watchlist in (("QQQ", plain), ("GLD", monitored)):
            _etf(session, ticker, 5000)
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=ticker, added_at=NOW))
        session.commit()

    for years in (0, 1, 5):
        reasons = _etf_reasons(engine, NOW + timedelta(days=365 * years))
        assert reasons["QQQ"] == reasons["GLD"] == tu.WATCHLIST


@pytest.mark.parametrize("days_ago, expected_in", [(0, True), (29, True), (30, True), (31, False), (200, False)])
def test_the_etf_view_window_boundary_is_30_days_like_stocks(engine, days_ago, expected_in):
    with Session(engine) as session:
        _etf(session, "QQQ", days_ago)
        session.commit()
    assert ("QQQ" in _etf_universe(engine)) is expected_in


def test_a_fund_flag_counts_as_an_etf_and_re_viewing_an_expired_etf_puts_it_back(engine):
    with Session(engine) as session:
        _etf(session, "MUTUAL", 90, fund=True)
        session.commit()
    assert _etf_reasons(engine)["MUTUAL"] == tu.EXPIRED

    assert tu.record_ticker_view("mutual", now=NOW) is True
    assert _etf_reasons(engine)["MUTUAL"] == tu.VIEWED


def test_index_and_manual_reasons_never_apply_to_an_etf(engine):
    with Session(engine) as session:
        _etf(session, "MOATETF", 400)
        session.add(TickerMoat(ticker="MOATETF", moat="wide_moat", updated_at=NOW))  # a rating set before the guard
        _etf(session, "INDEXETF", 400)
        session.add(IndexConstituent(index_name="sp500", ticker="INDEXETF", company_name="i", last_synced_at=NOW))
        session.commit()

    reasons = _etf_reasons(engine)
    assert reasons["MOATETF"] == reasons["INDEXETF"] == tu.EXPIRED
    assert tu.INDEX not in reasons.values() and tu.MANUAL not in reasons.values()


def test_a_delisted_seed_is_delisted_not_system(engine):
    with Session(engine) as session:
        session.add(TickerScore(ticker="XLC", computed_at=NOW, delisted_at=NOW, is_etf=True))
        session.commit()
    assert _etf_reasons(engine)["XLC"] == tu.DELISTED
    assert "XLC" not in _etf_universe(engine)


def test_hidden_inactive_etfs_counts_only_expired_ones(engine):
    with Session(engine) as session:
        _etf(session, "FRESH", 2)
        _etf(session, "OLD1", 40)
        _etf(session, "OLD2", 90)
        _etf(session, "GONE", 90)
        session.add(TickerScore(ticker="GONE", computed_at=NOW, delisted_at=NOW))
        _etf(session, "SPY", 900)  # a seed never expires
        session.commit()
        assert tu.load_expired_etfs(session, NOW) == {"OLD1", "OLD2"}
        assert tu.count_hidden_inactive_etfs(session, NOW) == 2


def test_the_partition_is_exhaustive_with_no_overlap_and_seeds_always_land_on_the_etf_side(engine):
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        _profile(session, "OLD")
        _etf(session, "QQQ", 1)
        _etf(session, "SPY", 1)
        _profile(session, "XLK")  # a seed whose profile row lacks the ETF flag: still the ETF side
        session.add(TickerScore(ticker="SCORED_ETF", computed_at=NOW, is_etf=True))
        session.add(TickerScore(ticker="SCORED_STOCK", computed_at=NOW, is_etf=False))
        session.commit()
        known = set(tu.load_all_known_tickers(session))
        stock_side, etf_side = tu.partition_known_tickers(session)

    assert stock_side & etf_side == set()
    assert known <= stock_side | etf_side
    assert stock_side == known - etf_side  # nothing on the stock side that is not known
    assert stock_side == {"IDX", "OLD", "SCORED_STOCK"}
    assert etf_side == {"QQQ", "SPY", "XLK", "SCORED_ETF"} | set(tu.ETF_SEED_TICKERS)


def test_the_stock_universe_is_the_stock_side_only_and_the_two_universes_are_exhaustive_and_disjoint(engine):
    """The cutover pin (replaces the 2026-10-02 "unchanged union" pin): load_tracked_universe holds no ETF, whether the
    ETF is viewed, expired, a known seed or watchlisted; the stock and ETF sides partition the known set."""
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        _profile(session, "VIEWED")
        _viewed(session, "VIEWED", 3)
        _profile(session, "OLDSTOCK")
        _viewed(session, "OLDSTOCK", 90)  # an expired stock
        _etf(session, "QQQ", 3)  # a viewed ETF
        _etf(session, "OLDETF", 90)  # an expired ETF
        _etf(session, "SPY", 400)  # a known seed
        _profile(session, "XLK")
        watchlist = Watchlist(name="L", created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        _etf(session, "WLETF", 400)
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="WLETF", added_at=NOW))
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="WLSTOCK", added_at=NOW))
        session.commit()

    assert _universe(engine) == ["IDX", "VIEWED", "WLSTOCK"]
    etfs = _etf_universe(engine)
    assert set(etfs) == {"QQQ", "SPY", "WLETF"} | set(tu.ETF_SEED_TICKERS)
    assert set(_universe(engine)) & set(etfs) == set()
    assert _reasons(engine)["OLDSTOCK"] == tu.EXPIRED and "OLDETF" not in _reasons(engine)
    assert _etf_reasons(engine)["OLDETF"] == tu.EXPIRED
    # calling the ETF side changes nothing about the stock side
    assert _universe(engine) == ["IDX", "VIEWED", "WLSTOCK"]
    with Session(engine) as session:
        stock_side, etf_side = tu.partition_known_tickers(session)
        known = set(tu.load_all_known_tickers(session))
        assert stock_side & etf_side == set() and known <= stock_side | etf_side
        # expired sets never overlap, so the two "hidden" counts cannot double-count a ticker
        assert tu.load_expired_tickers(session, NOW) == {"OLDSTOCK"}
        assert tu.load_expired_etfs(session, NOW) == {"OLDETF"}
        assert tu.count_hidden_inactive_etfs(session, NOW) == 1


# --- recording a view -------------------------------------------------------------------------------


def _last_viewed(engine, ticker):
    with Session(engine) as session:
        row = session.get(TickerView, ticker)
        return row.last_viewed_at if row else None


def test_a_view_is_written_at_most_once_per_calendar_day(engine):
    morning, evening, next_day = datetime(2026, 11, 15, 9), datetime(2026, 11, 15, 21), datetime(2026, 11, 16, 8)

    assert tu.record_ticker_view("AAPL", now=morning) is True
    assert tu.record_ticker_view("AAPL", now=evening) is False  # same day: no write
    assert _last_viewed(engine, "AAPL") == morning
    assert tu.record_ticker_view("AAPL", now=next_day) is True  # a later day moves it forward
    assert _last_viewed(engine, "AAPL") == next_day
    with Session(engine) as session:
        assert len(session.exec(select(TickerView)).all()) == 1


def test_record_ticker_view_never_raises_when_the_db_fails(monkeypatch):
    class Broken:
        def __enter__(self):
            raise RuntimeError("db is down")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(tu, "Session", lambda engine: Broken())
    assert tu.record_ticker_view("AAPL") is False


def test_the_summary_route_records_a_view_only_after_it_succeeds(engine, monkeypatch):
    from core.exceptions import TickerNotFoundError
    from core.schemas import TickerSummaryOut

    async def ok(ticker):
        return TickerSummaryOut(company_name="Apple", ticker=ticker)

    async def missing(ticker):
        raise TickerNotFoundError(ticker)

    with TestClient(main.app) as client:
        monkeypatch.setattr(main, "get_summary", missing)
        assert client.get("/api/tickers/NOPE/summary").status_code == 404
        assert _last_viewed(engine, "NOPE") is None

        monkeypatch.setattr(main, "get_summary", ok)
        assert client.get("/api/tickers/aapl/summary").status_code == 200
        first = _last_viewed(engine, "AAPL")
        assert first is not None
        client.get("/api/tickers/AAPL/summary")
        assert _last_viewed(engine, "AAPL") == first  # throttled: same day, same value


# --- the init_db seed: 30 days of grace for everything that exists today ---------------------------


def _legacy_db(engine):
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        session.add(IndexConstituent(index_name="other-index", ticker="NOTCOUNTED", company_name="x", last_synced_at=NOW))
        _profile(session, "PROFILED")
        session.add(TickerScore(ticker="SCORED", computed_at=NOW))
        watchlist = Watchlist(name="L", created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="WL", added_at=NOW))
        session.add(FundamentalsCache(ticker="EURUSD", statement_type="forex_rate", period="latest", fetched_at=NOW, raw_json="[]"))
        session.commit()


def test_the_seed_gives_every_existing_ticker_the_migration_time(engine):
    _legacy_db(engine)

    assert db._seed_ticker_views(now=NOW) == 4

    with Session(engine) as session:
        rows = {r.ticker: r.last_viewed_at for r in session.exec(select(TickerView)).all()}
    assert rows == {t: NOW for t in ("IDX", "PROFILED", "SCORED", "WL")}  # no FX pair, no other index


def test_the_seed_is_idempotent_and_never_moves_a_grace_date(engine):
    _legacy_db(engine)
    db._seed_ticker_views(now=NOW)

    assert db._seed_ticker_views(now=NOW + timedelta(days=9)) == 0  # a restart or a cron job's init_db()
    assert db._seed_ticker_views(now=NOW + timedelta(days=20)) == 0

    with Session(engine) as session:
        assert {r.last_viewed_at for r in session.exec(select(TickerView)).all()} == {NOW}


def test_the_seed_does_not_run_once_the_table_has_any_row(engine):
    _legacy_db(engine)
    tu.record_ticker_view("ONLYONE", now=NOW)

    assert db._seed_ticker_views(now=NOW) == 0
    with Session(engine) as session:
        assert [r.ticker for r in session.exec(select(TickerView)).all()] == ["ONLYONE"]


def test_init_db_seeds_on_an_existing_database_and_does_nothing_on_the_second_call(engine):
    _legacy_db(engine)
    db.init_db()
    with Session(engine) as session:
        first = {r.ticker: r.last_viewed_at for r in session.exec(select(TickerView)).all()}
    assert set(first) == {"IDX", "PROFILED", "SCORED", "WL"}

    db.init_db()
    with Session(engine) as session:
        assert {r.ticker: r.last_viewed_at for r in session.exec(select(TickerView)).all()} == first


def test_init_db_on_an_empty_database_seeds_nothing(engine):
    db.init_db()
    with Session(engine) as session:
        assert session.exec(select(TickerView)).all() == []


def test_nothing_leaves_the_universe_in_the_first_30_days_and_viewed_only_tickers_leave_on_day_31(engine):
    _legacy_db(engine)
    db._seed_ticker_views(now=NOW)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL_VIEWED", computed_at=NOW))
        session.add(TickerView(ticker="AAPL_VIEWED", last_viewed_at=NOW))
        session.commit()
    everyone = {"IDX", "PROFILED", "SCORED", "WL", "AAPL_VIEWED"}

    assert set(_universe(engine, NOW + timedelta(days=29, hours=23))) == everyone
    assert set(_universe(engine, NOW + timedelta(days=31))) == {"IDX", "WL"}  # index and watchlist stay


# --- every job and the Screener read the helper -----------------------------------------------------

BACKEND = Path(__file__).resolve().parents[1]
EXPIRING = [
    "pipeline/nightly_fundamentals_fetch.py",
    "pipeline/nightly_price_target_snapshot.py",
    "pipeline/nightly_trend_calculation.py",
    "pipeline/nightly_score_recompute.py",
    "pipeline/recompute_ticker_scores.py",
    "pipeline/stale_data_health_check.py",
    "data/momentum_data.py",
    "core/main.py",
]
WIDE = [
    "pipeline/non_us_purge.py",
    "pipeline/stale_data_health_check.py",
    "data/ticker_search.py",
    "pipeline/backfills/backfill_fmp_daily_bars.py",
    "pipeline/backfills/backfill_price_target_snapshots.py",
]


@pytest.mark.parametrize("path", EXPIRING)
def test_expiring_universe_consumers_import_the_helper(path):
    source = (BACKEND / path).read_text()
    assert "from data.tracked_universe import" in source and "load_tracked_universe" in source, path


@pytest.mark.parametrize("path", WIDE)
def test_wide_set_consumers_import_the_helper(path):
    source = (BACKEND / path).read_text()
    assert "load_all_known_tickers" in source, path


def test_no_module_keeps_the_old_union_or_its_name():
    """Defined once, imported everywhere: nothing may re-declare the old union or call the old name."""
    offenders = []
    for path in list((BACKEND / "pipeline").rglob("*.py")) + list((BACKEND / "data").rglob("*.py")) + [BACKEND / "core/main.py"]:
        if path.name == "tracked_universe.py":
            continue
        source = path.read_text()
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        if "load_full_tracked_universe" in code:
            offenders.append(f"{path.name}: old function name")
        if re.search(r"select\(WatchlistTicker\.ticker\)", code):
            offenders.append(f"{path.name}: re-declared union")
    assert offenders == []


def test_the_job_level_universe_loaders_exclude_expired_and_delisted_tickers(engine, monkeypatch):
    import pipeline.nightly_fundamentals_fetch as fundamentals
    import pipeline.nightly_price_target_snapshot as price_target

    monkeypatch.setattr(price_target, "_profile_exchanges", lambda tickers: {t: "NASDAQ" for t in tickers})
    with Session(engine) as session:
        for ticker in ("KEEP", "EXPIRED", "GONE"):
            session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        session.add(TickerScore(ticker="GONE", computed_at=datetime.now(), delisted_at=datetime.now()))
        session.add(TickerView(ticker="KEEP", last_viewed_at=datetime.now()))
        session.add(TickerView(ticker="EXPIRED", last_viewed_at=datetime.now() - timedelta(days=60)))
        session.add(TickerView(ticker="GONE", last_viewed_at=datetime.now()))
        session.commit()

        assert fundamentals.load_fundamentals_fetch_universe(session) == ["KEEP"]
        assert price_target.load_us_price_target_universe(session) == ["KEEP"]


# --- Screener: expired rows are hidden, a re-view brings them back ----------------------------------


def _scored(session, ticker, **kwargs):
    session.add(TickerScore(ticker=ticker, company_name=ticker, is_etf=False, computed_at=datetime.now(), **kwargs))


def test_the_screener_hides_an_expired_viewed_only_row_and_a_view_brings_it_back(engine, monkeypatch):
    from core.schemas import TickerSummaryOut

    now = datetime.now()
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=now))
        _scored(session, "IDX")
        _scored(session, "RECENT")
        _scored(session, "OLDVIEW")
        _scored(session, "DELISTED", delisted_at=now)
        session.add(TickerView(ticker="RECENT", last_viewed_at=now - timedelta(days=5)))
        session.add(TickerView(ticker="OLDVIEW", last_viewed_at=now - timedelta(days=40)))
        for ticker in ("RECENT", "OLDVIEW", "DELISTED"):
            _profile(session, ticker)
        session.commit()

    async def ok(ticker):
        return TickerSummaryOut(company_name=ticker, ticker=ticker)

    monkeypatch.setattr(main, "get_summary", ok)
    with TestClient(main.app) as client:
        rows = {r["ticker"] for r in client.get("/api/screener", params={"universe": "all"}).json()}
        meta = client.get("/api/screener/meta", params={"universe": "all"}).json()
        assert rows == {"IDX", "RECENT"}
        assert meta == {"universe": "all", "total_constituents": 2, "hidden_inactive": 1}  # OLDVIEW; not the delisted one
        # An index universe is unaffected and reports nothing hidden.
        assert client.get("/api/screener/meta", params={"universe": "sp500"}).json()["hidden_inactive"] == 0

        client.get("/api/tickers/OLDVIEW/summary")  # the page view re-adds it

        rows = {r["ticker"] for r in client.get("/api/screener", params={"universe": "all"}).json()}
        meta = client.get("/api/screener/meta", params={"universe": "all"}).json()
    assert rows == {"IDX", "RECENT", "OLDVIEW"}
    assert meta["hidden_inactive"] == 0 and meta["total_constituents"] == 3


def test_a_saved_screener_view_stays_valid_and_just_shows_fewer_rows(engine):
    from data.saved_screener_filters import list_saved_filters, upsert_saved_filter

    now = datetime.now()
    with Session(engine) as session:
        _scored(session, "OLDVIEW")
        session.add(TickerView(ticker="OLDVIEW", last_viewed_at=now - timedelta(days=90)))
        _profile(session, "OLDVIEW")
        session.commit()
    with Session(engine) as session:
        upsert_saved_filter(session, name="All passed", universe="all", sort_field="overall_score", sort_direction="desc", filters_json="{}")
        assert [f.name for f in list_saved_filters(session)] == ["All passed"]

    with TestClient(main.app) as client:
        assert client.get("/api/screener", params={"universe": "all"}).json() == []


# --- Monthly Momentum keeps protected tickers -------------------------------------------------------


def test_momentum_keeps_a_moat_rated_ticker_that_was_not_viewed_for_a_year(engine, monkeypatch):
    now = datetime.now()
    index = pd.bdate_range(start="2024-08-01", end="2026-08-31")
    history = pd.DataFrame({"close": [100.0] * (len(index) - 1) + [150.0]}, index=index)

    async def fake_batch(tickers, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        return {t: history for t in tickers}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_batch)
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))
    with Session(engine) as session:
        for ticker in ("RATED", "UNRATED"):
            _profile(session, ticker)
            session.add(TickerView(ticker=ticker, last_viewed_at=now - timedelta(days=365)))
        _scored(session, "RATED", moat="wide_moat")
        _scored(session, "UNRATED", moat=None)
        session.add(TickerMoat(ticker="RATED", moat="wide_moat", updated_at=now))
        _profile(session, "EXPIRED_NOMOAT_VIEWED_ONLY")
        _scored(session, "EXPIRED_NOMOAT_VIEWED_ONLY", moat="narrow_moat")  # a stale copy with no TickerMoat row
        session.add(TickerView(ticker="EXPIRED_NOMOAT_VIEWED_ONLY", last_viewed_at=now - timedelta(days=365)))
        session.commit()

    summary = asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    with Session(engine) as session:
        tickers = {r.ticker for r in session.exec(select(MomentumSnapshot)).all()}
    assert tickers == {"RATED"}  # protected by its Moat; the unrated and the unprotected expired ones are out
    assert summary["universe_size"] == 1


def test_momentum_still_reports_a_moat_rated_delisted_ticker_as_skipped(engine, monkeypatch):
    async def fake_batch(tickers, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        return {}

    monkeypatch.setattr(momentum_data, "get_or_fetch_bars_batch", fake_batch)
    monkeypatch.setattr(momentum_data, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))
    with Session(engine) as session:
        _profile(session, "EA")
        _scored(session, "EA", moat="narrow_moat", delisted_at=datetime.now())
        session.add(TickerMoat(ticker="EA", moat="narrow_moat", updated_at=datetime.now()))
        session.commit()

    summary = asyncio.run(momentum_data.compute_and_store_momentum_snapshot(date(2026, 8, 31)))

    assert summary["skipped_delisted_count"] == 1 and summary["universe_size"] == 0


# --- the verification report (read-only) ------------------------------------------------------------


def test_the_report_counts_reasons_and_lists_who_leaves_soon(engine):
    from pipeline.tracked_universe_report import build_report, format_report

    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        for ticker in ("SOON", "LATER", "OLD"):
            _profile(session, ticker)
        session.add(TickerScore(ticker="GONE", computed_at=NOW, delisted_at=NOW))
        _viewed(session, "SOON", 25)
        _viewed(session, "LATER", 1)
        _viewed(session, "OLD", 60)
        session.commit()
        report = build_report(session, now=NOW, within_days=7)

    assert report["by_reason"] == {"index": 1, "viewed": 2, "expired": 1, "delisted": 1}
    assert report["in_universe"] == 3 and report["expired"] == ["OLD"] and report["delisted"] == ["GONE"]
    assert [t for t, _ in report["expiring"]] == ["SOON"]
    assert "Leaving within 7 days: SOON (2026-11-20)" in format_report(report)


def test_the_report_has_a_separate_etf_side_that_does_not_overlap_the_stock_side(engine):
    from pipeline.tracked_universe_report import build_report, format_report

    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        _etf(session, "QQQ", 25)
        _etf(session, "OLDETF", 60)
        session.add(TickerScore(ticker="GONEETF", computed_at=NOW, is_etf=True, delisted_at=NOW))
        session.commit()
        report = build_report(session, now=NOW, within_days=7)

    assert report["by_reason"] == {"index": 1} and report["known_stock"] == 1  # no ETF in the stock figures
    etf = report["etf"]
    assert etf["by_reason"]["viewed"] == 1 and etf["by_reason"]["expired"] == 1 and etf["by_reason"]["delisted"] == 1
    assert etf["by_reason"]["system"] == len(tu.ETF_SEED_TICKERS)
    assert etf["expired"] == ["OLDETF"] and etf["delisted"] == ["GONEETF"]
    assert [t for t, _ in etf["expiring"]] == ["QQQ"]
    text = format_report(report)
    assert "ETF side:" in text and "ETF expired" in text and "ETFs leaving within 7 days: QQQ (2026-11-20)" in text


# --- opt-in universe, step 2: the added state (docs/specs/tracked-universe.md "Planned") -------------------------------


def test_record_ticker_view_never_clears_or_changes_the_added_fields(engine):
    added_at = datetime(2026, 10, 3, 8, 0)
    with Session(engine) as session:
        session.add(TickerView(ticker="ADDED", last_viewed_at=datetime(2026, 11, 14, 9), added_at=added_at, added_source="grandfathered"))
        session.commit()
    for now in (datetime(2026, 11, 15, 9), datetime(2026, 11, 15, 21), datetime(2026, 11, 16, 8), datetime(2026, 12, 25, 8)):
        tu.record_ticker_view("ADDED", now=now)  # same day (no write) and later days (a write): both leave the fields alone
        with Session(engine) as session:
            row = session.get(TickerView, "ADDED")
            assert (row.added_at, row.added_source) == (added_at, "grandfathered")
    assert _last_viewed(engine, "ADDED") == datetime(2026, 12, 25, 8)
    # a brand-new view starts with both NULL
    tu.record_ticker_view("PLAIN", now=NOW)
    with Session(engine) as session:
        row = session.get(TickerView, "PLAIN")
        assert (row.added_at, row.added_source) == (None, None)


def test_load_added_tickers_and_the_stock_etf_split(engine):
    with Session(engine) as session:
        for ticker, raw in (("STK", "{}"), ("ETF", '{"isEtf": true}'), ("PLAIN", "{}")):
            session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW, raw_json=raw))
        session.add(TickerView(ticker="STK", last_viewed_at=NOW, added_at=NOW, added_source="user"))
        session.add(TickerView(ticker="ETF", last_viewed_at=NOW, added_at=NOW, added_source="grandfathered"))
        session.add(TickerView(ticker="PLAIN", last_viewed_at=NOW))
        session.commit()
        assert tu.load_added_tickers(session) == {"STK", "ETF"}
        assert tu.load_added_by_side(session) == ({"STK"}, {"ETF"})


def test_the_universes_are_identical_with_and_without_added_at_populated(engine):
    """The classification flip is a LATER step: until then added_at/added_source change no universe, no reason and no
    hidden count, whatever they hold (including an added ticker that is expired by the old rule)."""
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="IDX", company_name="i", last_synced_at=NOW))
        for ticker, raw in (
            ("IDX", "{}"), ("VIEWED", "{}"), ("OLDSTOCK", "{}"), ("VIEWEDETF", '{"isEtf": true}'), ("OLDETF", '{"isEtf": true}'),
            ("NEVER", "{}"),
        ):
            session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW, raw_json=raw))
        _viewed(session, "VIEWED", 3)
        _viewed(session, "OLDSTOCK", 60)
        _viewed(session, "VIEWEDETF", 3)
        _viewed(session, "OLDETF", 60)
        session.commit()

    def snapshot():
        with Session(engine) as session:
            return (
                tu.load_tracked_universe(session, NOW),
                tu.load_etf_universe(session, NOW),
                tu.classify_known_tickers(session, NOW),
                tu.classify_etf_tickers(session, NOW),
                tu.load_expired_tickers(session, NOW),
                tu.load_expired_etfs(session, NOW),
                tu.count_hidden_inactive_etfs(session, NOW),
            )

    without = snapshot()
    with Session(engine) as session:
        for row in session.exec(select(TickerView)).all():  # every view row, expired ones included, becomes added
            row.added_at, row.added_source = NOW, "user"
            session.add(row)
        session.commit()
    assert snapshot() == without
    assert "OLDSTOCK" not in without[0] and without[2]["OLDSTOCK"] == tu.EXPIRED  # an added ticker still expires today
