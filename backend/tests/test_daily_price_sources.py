import asyncio
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_price_sources as daily_price_sources
from clients.daily_price_sources import FMPDailyBarSource, _most_recent_completed_trading_date
from core.models import FundamentalsCache


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(daily_price_sources, "engine", engine)
    return engine


def _seed_cache_row(engine, ticker: str, period: str, fetched_at: datetime, rows: list[dict]) -> None:
    import json

    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker,
                statement_type="historical_price_eod",
                period=period,
                fetched_at=fetched_at,
                raw_json=json.dumps(rows),
            )
        )
        session.commit()


def _bar(d: str) -> dict:
    return {"date": d, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}


def _fake_fetch_fn(monkeypatch, rows_to_return: list[dict]):
    """Patches fmp_client.get_historical_price_eod with a counting fake,
    matching the shared-singleton-import convention every other test in
    this codebase uses (the object is imported directly, not accessed via
    the module namespace, so patching the attribute on the real object is
    what every call site actually sees)."""
    call_count = {"n": 0}

    async def fake(ticker, from_date, to_date):
        call_count["n"] += 1
        return list(rows_to_return)

    monkeypatch.setattr(daily_price_sources.fmp_client, "get_historical_price_eod", fake)
    return call_count


def test_stale_beyond_daily_bar_staleness_but_within_cache_staleness_triggers_a_refetch(monkeypatch):
    """Regression test for the exact production bug: a row fetched before
    daily_bar_staleness_days (1) but well inside the old cache_staleness_days
    (7) must NOT be served as fresh -- it must trigger a live re-fetch,
    since a daily-price row that old is missing at least one trading day's
    close."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_price_sources.settings, "daily_bar_staleness_days", 1)
    monkeypatch.setattr(daily_price_sources.settings, "cache_staleness_days", 7)
    monkeypatch.setattr(daily_price_sources.settings, "fmp_enabled", True)
    # Pins the session-freshness gate to match the freshly-fetched bar's own
    # date, so the single live fetch this test expects isn't followed by a
    # second, unrelated one from the market-close-aware check added later --
    # this test is specifically about the TTL/cache_staleness_days
    # distinction, not that check.
    monkeypatch.setattr(daily_price_sources, "_most_recent_completed_trading_date", lambda: date(2026, 9, 15))

    _seed_cache_row(engine, "WDC", "2y", datetime.now() - timedelta(days=2), [_bar("2026-09-14")])
    call_count = _fake_fetch_fn(monkeypatch, [_bar("2026-09-14"), _bar("2026-09-15")])

    result = asyncio.run(FMPDailyBarSource().get_daily_bars(["WDC"], 2))

    assert call_count["n"] == 1  # the stale row forced a live re-fetch
    assert len(result["WDC"]) == 2  # the fresh fetch's newer close is present


def test_fresh_within_daily_bar_staleness_is_served_from_cache(monkeypatch):
    """The flip side: a row fetched within daily_bar_staleness_days, whose
    own last bar already reflects the most recently completed session, must
    be served as-is with zero live calls, same as any other get_or_fetch
    consumer -- this fix tightens the window, it doesn't remove caching.
    Pins _most_recent_completed_trading_date to the cached bar's own date so
    this test isolates the TTL check specifically, independent of the
    market-close-aware check added below (and of whatever the real
    wall-clock date happens to be when this test runs)."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_price_sources.settings, "daily_bar_staleness_days", 1)
    monkeypatch.setattr(daily_price_sources.settings, "fmp_enabled", True)
    monkeypatch.setattr(daily_price_sources, "_most_recent_completed_trading_date", lambda: date(2026, 9, 15))

    _seed_cache_row(engine, "WDC", "2y", datetime.now() - timedelta(hours=1), [_bar("2026-09-15")])
    call_count = _fake_fetch_fn(monkeypatch, [_bar("2026-09-15"), _bar("2026-09-16")])

    result = asyncio.run(FMPDailyBarSource().get_daily_bars(["WDC"], 2))

    assert call_count["n"] == 0  # served from cache, no live call
    assert len(result["WDC"]) == 1


def test_fresh_per_ttl_but_missing_latest_session_still_forces_a_refetch(monkeypatch):
    """Regression test for the market-close-aware fix itself: a row fetched
    well within daily_bar_staleness_days (so the flat TTL alone would call
    it fresh) must still be treated as stale, and force a live refetch, when
    its own last bar predates the most recently completed trading session --
    this is the exact mechanism that hit the Chart tab (fixed there by
    dropping caching entirely) and was found still live for this job's own
    cached '4y'/'2y'/etc. rows."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_price_sources.settings, "daily_bar_staleness_days", 1)
    monkeypatch.setattr(daily_price_sources.settings, "fmp_enabled", True)
    monkeypatch.setattr(daily_price_sources, "_most_recent_completed_trading_date", lambda: date(2026, 9, 17))

    # Fetched 1 hour ago -- comfortably inside the 1-day TTL -- but its last
    # bar (09-15) is two sessions behind the most recently completed one
    # (09-17), the classic pre-close-morning-fetch shape.
    _seed_cache_row(engine, "WDC", "2y", datetime.now() - timedelta(hours=1), [_bar("2026-09-14"), _bar("2026-09-15")])
    call_count = _fake_fetch_fn(monkeypatch, [_bar("2026-09-14"), _bar("2026-09-15"), _bar("2026-09-16"), _bar("2026-09-17")])

    result = asyncio.run(FMPDailyBarSource().get_daily_bars(["WDC"], 2))

    assert call_count["n"] == 1  # TTL alone said fresh, but the session check forced a live refetch anyway
    assert len(result["WDC"]) == 4  # the fresh fetch's newer closes are present


def test_different_lookback_years_get_independent_cache_rows_not_a_shared_key(monkeypatch):
    """Regression test for the shared-cache-key collision: Chart's D_6M/D_1Y
    (lookback_years=2), D_2Y (3), W_4Y (8), and Liquidity Zone (4) must each
    land in their own cache row, not all collide on one hardcoded '4y' key
    regardless of what was actually requested."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_price_sources.settings, "daily_bar_staleness_days", 1)
    monkeypatch.setattr(daily_price_sources.settings, "fmp_enabled", True)
    # Pins the session-freshness gate to match the fixture's own bar date so
    # this test's final cache-hit assertion isolates the cache-key-collision
    # behavior it's actually about, independent of the market-close-aware
    # check added later (and of the real wall-clock date at test time).
    monkeypatch.setattr(daily_price_sources, "_most_recent_completed_trading_date", lambda: date(2026, 9, 15))
    call_count = _fake_fetch_fn(monkeypatch, [_bar("2026-09-15")])

    asyncio.run(FMPDailyBarSource().get_daily_bars(["AAPL"], 2))
    asyncio.run(FMPDailyBarSource().get_daily_bars(["AAPL"], 8))

    assert call_count["n"] == 2  # two distinct requested windows, two live fetches, no collision

    with Session(engine) as session:
        periods = sorted(session.exec(select(FundamentalsCache.period)).all())
    assert periods == ["2y", "8y"]

    # A third call re-requesting lookback_years=2 must now be a cache hit
    # against its own "2y" row, not trigger a third live fetch.
    asyncio.run(FMPDailyBarSource().get_daily_bars(["AAPL"], 2))
    assert call_count["n"] == 2


@pytest.mark.parametrize(
    "reference_utc, expected",
    [
        # Tuesday 03:25 UTC == Monday 23:25 ET (EDT, UTC-4 in September) --
        # this app's own nightly-cron scenario: well after Monday's close,
        # so Monday itself is the most recently completed session.
        (datetime(2026, 9, 15, 3, 25, tzinfo=timezone.utc), date(2026, 9, 14)),
        # Monday 13:00 UTC == Monday 09:00 ET, before the 9:30 ET open and
        # well before the 16:00 ET close -- the most recently completed
        # session is still the prior trading day, and since that's a
        # Monday, rolls back across the weekend to the preceding Friday.
        (datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        # Friday 21:00 UTC == Friday 17:00 ET, after that day's own close --
        # Friday itself is already the most recently completed session.
        (datetime(2026, 9, 11, 21, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        # Saturday, any time of day -- always rolls back to Friday.
        (datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        # Sunday, any time of day -- always rolls back to Friday.
        (datetime(2026, 9, 13, 15, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        # A naive datetime is treated as UTC, matching this codebase's own
        # datetime.now() convention on a server whose system timezone is UTC.
        (datetime(2026, 9, 15, 3, 25), date(2026, 9, 14)),
    ],
)
def test_most_recent_completed_trading_date(reference_utc, expected):
    assert _most_recent_completed_trading_date(reference_utc) == expected
