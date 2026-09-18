import asyncio
from datetime import datetime

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_price_sources as daily_price_sources
import clients.yahoo_cache as yahoo_cache_module
from clients.daily_price_sources import get_daily_bars
from core.models import YahooPriceCache


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)
    return engine


def _sample_df(n: int = 3, start_price: float = 100.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [start_price + i for i in range(n)],
            "High": [start_price + i + 1 for i in range(n)],
            "Low": [start_price + i - 1 for i in range(n)],
            "Close": [start_price + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=dates,
    )


def test_get_daily_bars_fetches_via_yahoo_unconditionally(monkeypatch):
    """Regression test for the 2026-09-18 Yahoo-consolidation change:
    Liquidity Zones no longer has an FMP branch at all -- get_daily_bars
    must call Yahoo, and the module has no fmp_enabled conditional (or
    fmp_client import) left to gate on."""
    _fresh_engine(monkeypatch)
    assert not hasattr(daily_price_sources, "fmp_client")

    calls: list[dict] = []

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        calls.append({"tickers": list(tickers), "period": period, "auto_adjust": auto_adjust})
        return {"AAPL": _sample_df()}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    result = asyncio.run(get_daily_bars(["AAPL"]))

    assert len(calls) == 1
    assert calls[0]["tickers"] == ["AAPL"]
    assert len(result["AAPL"]) == 3


def test_get_daily_bars_requests_non_dividend_adjusted_bars(monkeypatch):
    """The load-bearing assertion for this round's change: Liquidity Zone
    support/resistance levels must be based on raw (auto_adjust=False)
    closes, not Yahoo's own default (True), which showed a confirmed
    ~1-7% divergence vs. FMP's raw closes for dividend-heavy tickers."""
    _fresh_engine(monkeypatch)

    seen_auto_adjust = {}

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        seen_auto_adjust["value"] = auto_adjust
        return {"AAPL": _sample_df()}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    asyncio.run(get_daily_bars(["AAPL"]))

    assert seen_auto_adjust["value"] is False


def test_get_daily_bars_skips_a_ticker_with_no_data(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        return {"AAPL": _sample_df()}  # BADCO absent

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    result = asyncio.run(get_daily_bars(["AAPL", "BADCO"]))

    assert "AAPL" in result
    assert "BADCO" not in result


def test_get_daily_bars_forces_a_live_fetch_even_when_cache_is_fresh(monkeypatch):
    """Regression test for the cross-job cache-coverage collision this
    round's Yahoo consolidation introduced: every Liquidity Zone ticker is
    also covered by pipeline/nightly_trend_calculation.py's own
    period="2y" fetch, which runs 15 minutes earlier in cron and shares
    this exact table. Without force=True, a ticker Trend just fetched
    would read as "fresh" here and silently serve ~2 years of history
    instead of the ~5 this function actually needs -- truncating the
    Weekly (4yr) timeframe every night. get_daily_bars must therefore
    always live-fetch, never trusting an already-fresh cache row it didn't
    populate itself."""
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        # A single row, freshly written moments ago (e.g. by Trend's own
        # job) -- comfortably inside yahoo_price_cache_staleness_days, so
        # the ordinary staleness check alone would call this fresh.
        session.add(
            YahooPriceCache(
                ticker="AAPL",
                date=pd.Timestamp("2024-01-01").date(),
                open=1,
                high=2,
                low=0.5,
                close=1.5,
                volume=100,
                fetched_at=datetime.now(),
            )
        )
        session.commit()

    call_count = {"n": 0}

    async def fake_get_history(tickers, period="2y", interval="1d", auto_adjust=True):
        call_count["n"] += 1
        return {"AAPL": _sample_df(n=5)}  # the fuller history this function actually wants

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    result = asyncio.run(get_daily_bars(["AAPL"]))

    assert call_count["n"] == 1  # forced a live fetch despite the fresh row
    assert len(result["AAPL"]) == 5  # got the fuller history, not the stale single row


def test_get_daily_bars_passes_force_true_through_to_the_batch_helper(monkeypatch):
    _fresh_engine(monkeypatch)
    seen = {}

    async def fake_batch(tickers, period="2y", auto_adjust=True, force=False):
        seen["force"] = force
        return {}

    monkeypatch.setattr(daily_price_sources, "get_or_fetch_price_history_batch", fake_batch)

    asyncio.run(get_daily_bars(["AAPL"]))

    assert seen["force"] is True
