"""Retention/pruning of SharedBarsCache (clients/shared_bars_cache.py::
prune_old_bars). Covers: old bars actually leave and recent ones stay; the
survivors' span/freshness are still coherent afterwards (the cache neither
reads as stale nor as too narrow for its widest consumer, so pruning never
triggers a refetch); and the retention windows keep their two design
invariants against the consumers' REAL lookback constants."""

import asyncio
from datetime import date, datetime, time, timedelta

import pandas as pd
import pytest
from sqlalchemy import insert
from sqlmodel import Session, SQLModel, create_engine, func, select

import clients.shared_bars_cache as cache
from clients.shared_bars_cache import (
    DAILY_INTERVAL,
    INTRADAY_INTERVAL,
    RETENTION_DAYS,
    _cache_span,
    _period_for,
    _period_steps,
    _preserved_lookback_days,
    get_or_fetch_bars_batch,
    prune_old_bars,
)
from core.models import SharedBarsCache
from data.liquidity_zone_data import LOOKBACK_DAYS as LZ_LOOKBACK_DAYS
from data.trend_analysis_data import LOOKBACK_DAYS as TREND_LOOKBACK_DAYS
from pipeline.nightly_entry_signal_calculation import LOOKBACK_DAYS as BBRSI_LOOKBACK_DAYS
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS as WARREN_LOOKBACK_DAYS

TODAY = date(2026, 9, 17)  # a Thursday
LAST_DAILY_BAR = datetime(2026, 9, 17)
LAST_INTRADAY_BAR = datetime(2026, 9, 17, 15, 30)
_SESSION_STARTS = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cache, "engine", engine)
    monkeypatch.setattr(cache, "_most_recent_completed_trading_date", lambda reference=None: TODAY)
    monkeypatch.setattr(cache, "_most_recent_completed_intraday_bar_start", lambda reference=None: LAST_INTRADAY_BAR)
    monkeypatch.setattr(cache, "_eastern_today", lambda reference=None: TODAY)
    calls: list[dict] = []

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        calls.append({"tickers": list(tickers), "period": period, "interval": interval})
        return {}

    monkeypatch.setattr(cache.yahoo_client, "get_history", fake_get_history)
    return engine, calls


def _weekday_bars(ticker: str, interval: str, days_back: int) -> list[dict]:
    """One row per weekday (daily) / seven per weekday (60m) from
    `days_back` calendar days ago through the pinned last bar."""
    rows = []
    for offset in range(days_back, -1, -1):
        day = TODAY - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        stamps = [datetime.combine(day, time.min)] if interval == DAILY_INTERVAL else [
            datetime.combine(day, time(h, m)) for h, m in _SESSION_STARTS
        ]
        for stamp in stamps:
            rows.append(
                {"ticker": ticker, "interval": interval, "bar_time": stamp, "open": 1.0, "high": 2.0, "low": 0.5,
                 "close": 1.5, "volume": 10, "fetched_at": datetime(2026, 9, 18, 3, 0)}
            )
    return rows


def _seed(engine, ticker: str, interval: str, days_back: int) -> int:
    rows = _weekday_bars(ticker, interval, days_back)
    with Session(engine) as session:
        session.execute(insert(SharedBarsCache), rows)
        session.commit()
    return len(rows)


def _count(engine, interval: str | None = None, ticker: str | None = None) -> int:
    stmt = select(func.count()).select_from(SharedBarsCache)
    if interval:
        stmt = stmt.where(SharedBarsCache.interval == interval)
    if ticker:
        stmt = stmt.where(SharedBarsCache.ticker == ticker)
    with Session(engine) as session:
        return session.exec(stmt).one()


def _span(engine, ticker: str, interval: str):
    with Session(engine) as session:
        return _cache_span(session, [ticker], interval)[ticker]


def test_old_bars_are_removed_and_recent_ones_kept_per_interval(env):
    engine, _ = env
    _seed(engine, "AAPL", DAILY_INTERVAL, 8 * 365)
    _seed(engine, "AAPL", INTRADAY_INTERVAL, 4 * 365)

    deleted = prune_old_bars()

    assert deleted[DAILY_INTERVAL] > 0 and deleted[INTRADAY_INTERVAL] > 0
    first_daily, last_daily = _span(engine, "AAPL", DAILY_INTERVAL)
    first_intraday, last_intraday = _span(engine, "AAPL", INTRADAY_INTERVAL)
    daily_cutoff = datetime.combine(TODAY - timedelta(days=RETENTION_DAYS[DAILY_INTERVAL]), time.min)
    intraday_cutoff = datetime.combine(TODAY - timedelta(days=RETENTION_DAYS[INTRADAY_INTERVAL]), time.min)
    # MIN moved forward to the first surviving bar (never before the cutoff, and no
    # more than a weekend past it); MAX -- what freshness reads -- did not move.
    assert daily_cutoff <= first_daily < daily_cutoff + timedelta(days=4)
    assert intraday_cutoff <= first_intraday < intraday_cutoff + timedelta(days=4)
    assert last_daily == LAST_DAILY_BAR and last_intraday == LAST_INTRADAY_BAR


def test_a_bar_exactly_on_the_cutoff_survives_and_one_day_earlier_does_not(env):
    engine, _ = env
    cutoff = datetime.combine(TODAY - timedelta(days=RETENTION_DAYS[DAILY_INTERVAL]), time.min)
    with Session(engine) as session:
        for bar_time in (cutoff, cutoff - timedelta(days=1)):
            session.add(SharedBarsCache(ticker="AAPL", interval=DAILY_INTERVAL, bar_time=bar_time, open=1, high=1, low=1,
                                        close=1, volume=1, fetched_at=datetime(2026, 9, 17)))
        session.commit()

    prune_old_bars()

    assert _span(engine, "AAPL", DAILY_INTERVAL) == (cutoff, cutoff)


def test_windows_are_independent_per_interval_and_per_ticker(env):
    """A 4y-old 60m bar is past ITS window (3y) but a 4y-old daily bar is not
    past the daily window (6y); other tickers are untouched."""
    engine, _ = env
    _seed(engine, "AAPL", DAILY_INTERVAL, 4 * 365)
    _seed(engine, "MSFT", INTRADAY_INTERVAL, 4 * 365)
    daily_before = _count(engine, DAILY_INTERVAL)

    deleted = prune_old_bars()

    assert deleted[DAILY_INTERVAL] == 0 and _count(engine, DAILY_INTERVAL) == daily_before
    assert deleted[INTRADAY_INTERVAL] > 0
    assert _count(engine, ticker="AAPL") == daily_before


def test_a_ticker_with_nothing_inside_the_window_loses_its_row_entirely(env):
    engine, _ = env
    with Session(engine) as session:
        session.add(SharedBarsCache(ticker="DELISTED", interval=DAILY_INTERVAL, bar_time=datetime(2015, 1, 5), open=1, high=1,
                                    low=1, close=1, volume=1, fetched_at=datetime(2015, 1, 6)))
        session.commit()
    _seed(engine, "AAPL", DAILY_INTERVAL, 365)

    prune_old_bars()

    assert _count(engine, ticker="DELISTED") == 0
    assert _count(engine, ticker="AAPL") > 0


def test_dry_run_reports_the_same_counts_but_deletes_nothing(env):
    engine, _ = env
    _seed(engine, "AAPL", DAILY_INTERVAL, 8 * 365)
    before = _count(engine)

    would = prune_old_bars(dry_run=True)
    assert _count(engine) == before

    assert prune_old_bars() == would


def test_pruning_is_idempotent(env):
    engine, _ = env
    _seed(engine, "AAPL", INTRADAY_INTERVAL, 4 * 365)
    prune_old_bars()
    after_first = _count(engine)

    assert prune_old_bars() == {DAILY_INTERVAL: 0, INTRADAY_INTERVAL: 0}
    assert _count(engine) == after_first


def test_after_pruning_the_widest_consumer_is_still_served_from_cache_with_zero_fetches(env):
    """The retained window must still satisfy (a) coverage for the widest
    lookback each interval has -- otherwise the very next nightly run would
    refetch it -- and (b) freshness, since only the OLD end was trimmed."""
    engine, calls = env
    _seed(engine, "AAPL", DAILY_INTERVAL, 8 * 365)
    _seed(engine, "AAPL", INTRADAY_INTERVAL, 4 * 365)
    prune_old_bars()

    daily = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, LZ_LOOKBACK_DAYS, auto_adjust=False))["AAPL"]
    intraday = asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, WARREN_LOOKBACK_DAYS, auto_adjust=False))["AAPL"]

    assert calls == []
    assert daily.index.max() == pd.Timestamp(LAST_DAILY_BAR)
    assert (daily.index.max() - daily.index.min()).days >= LZ_LOOKBACK_DAYS - 5
    assert intraday.index.max().to_pydatetime().replace(tzinfo=None) == LAST_INTRADAY_BAR
    assert (intraday.index.max() - intraday.index.min()).days >= WARREN_LOOKBACK_DAYS - 5


# ---------------------------------------------------------------------------
# Design invariants: retention vs. the consumers' real fetch widths.
# ---------------------------------------------------------------------------

_CONSUMER_LOOKBACKS = {
    DAILY_INTERVAL: {"liquidity_zones": LZ_LOOKBACK_DAYS, "trend": TREND_LOOKBACK_DAYS},
    INTRADAY_INTERVAL: {"warren": WARREN_LOOKBACK_DAYS, "bb_rsi": BBRSI_LOOKBACK_DAYS},
}


@pytest.mark.parametrize("interval", [DAILY_INTERVAL, INTRADAY_INTERVAL])
def test_retention_covers_the_fetch_tier_of_every_consumer_with_headroom(interval):
    """A consumer whose fetch tier exceeds retention would download that
    tier's full width every night and have the weekly prune trim it back
    (and, between prunes' trims, see itself as insufficiently covered) --
    a new consumer asking for more than this must raise RETENTION_DAYS."""
    for name, lookback in _CONSUMER_LOOKBACKS[interval].items():
        tier_days = dict(_period_steps(interval))[_period_for(interval, lookback)]
        assert tier_days + 365 <= RETENTION_DAYS[interval], (
            f"{name}: lookback {lookback}d fetches the {tier_days}d tier, which needs a year of headroom under "
            f"RETENTION_DAYS[{interval!r}]={RETENTION_DAYS[interval]}"
        )


@pytest.mark.parametrize("interval", [DAILY_INTERVAL, INTRADAY_INTERVAL])
def test_a_fully_grown_retained_row_still_reads_as_the_tier_it_was_fetched_at(interval):
    """RETENTION must stay under the NEXT tier's threshold so a row that has
    grown to the retention cap doesn't snap up to a wider tier and ratchet
    every nightly refetch wider (see _preserved_lookback_days)."""
    steps = _period_steps(interval)
    first = datetime(2020, 1, 1)
    last = first + timedelta(days=RETENTION_DAYS[interval] - 1)
    snapped = _preserved_lookback_days(first, last, interval)

    widest_consumer_tier = max(
        dict(steps)[_period_for(interval, lookback)] for lookback in _CONSUMER_LOOKBACKS[interval].values()
    )
    # Never a tier ABOVE what the widest consumer fetches.
    assert snapped <= max(widest_consumer_tier, RETENTION_DAYS[interval])
    assert snapped in {days for _, days in steps} | {RETENTION_DAYS[interval]}
    next_tiers = [days for _, days in steps if days > widest_consumer_tier]
    if next_tiers:
        assert snapped < min(next_tiers)
