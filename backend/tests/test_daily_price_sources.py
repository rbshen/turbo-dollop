import asyncio
from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_price_sources as daily_price_sources
from clients.daily_price_sources import FMPDailyBarSource
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

    _seed_cache_row(engine, "WDC", "2y", datetime.now() - timedelta(days=2), [_bar("2026-09-14")])
    call_count = _fake_fetch_fn(monkeypatch, [_bar("2026-09-14"), _bar("2026-09-15")])

    result = asyncio.run(FMPDailyBarSource().get_daily_bars(["WDC"], 2))

    assert call_count["n"] == 1  # the stale row forced a live re-fetch
    assert len(result["WDC"]) == 2  # the fresh fetch's newer close is present


def test_fresh_within_daily_bar_staleness_is_served_from_cache(monkeypatch):
    """The flip side: a row fetched within daily_bar_staleness_days must be
    served as-is with zero live calls, same as any other get_or_fetch
    consumer -- this fix tightens the window, it doesn't remove caching."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_price_sources.settings, "daily_bar_staleness_days", 1)
    monkeypatch.setattr(daily_price_sources.settings, "fmp_enabled", True)

    _seed_cache_row(engine, "WDC", "2y", datetime.now() - timedelta(hours=1), [_bar("2026-09-15")])
    call_count = _fake_fetch_fn(monkeypatch, [_bar("2026-09-15"), _bar("2026-09-16")])

    result = asyncio.run(FMPDailyBarSource().get_daily_bars(["WDC"], 2))

    assert call_count["n"] == 0  # served from cache, no live call
    assert len(result["WDC"]) == 1


def test_different_lookback_years_get_independent_cache_rows_not_a_shared_key(monkeypatch):
    """Regression test for the shared-cache-key collision: Chart's D_6M/D_1Y
    (lookback_years=2), D_2Y (3), W_4Y (8), and Liquidity Zone (4) must each
    land in their own cache row, not all collide on one hardcoded '4y' key
    regardless of what was actually requested."""
    engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(daily_price_sources.settings, "daily_bar_staleness_days", 1)
    monkeypatch.setattr(daily_price_sources.settings, "fmp_enabled", True)
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
