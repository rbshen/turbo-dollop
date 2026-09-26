import core.data_groups as _dg
import asyncio

import pandas as pd
import pytest

import clients.technical_sources as technical_sources_module
from clients.technical_sources import FMPTechnicalSource, YahooTechnicalSource, get_technical_source


def _sample_ohlcv(n: int = 10) -> pd.DataFrame:
    dates = pd.date_range("2026-01-05 09:30", periods=n, freq="60min", tz="America/New_York")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=dates,
    )


def test_yahoo_technical_source_reads_through_the_shared_bars_cache(monkeypatch):
    """BB+RSI must NOT fetch on its own: it reads the (ticker, "60m") row
    Warren's job shares, at its own 60-day width, raw (non-adjusted)."""
    seen = {}

    async def fake_batch(tickers, interval, lookback_days, auto_adjust=True, **kwargs):
        seen.update(tickers=list(tickers), interval=interval, lookback_days=lookback_days, auto_adjust=auto_adjust, kwargs=kwargs)
        return {"AAPL": _sample_ohlcv().rename(columns=str.lower)}

    monkeypatch.setattr(technical_sources_module, "get_or_fetch_bars_batch", fake_batch)

    result = asyncio.run(YahooTechnicalSource().get_intraday_bars(["AAPL"], lookback_days=60))

    assert list(result["AAPL"].columns) == ["open", "high", "low", "close", "volume"]
    assert seen == {"tickers": ["AAPL"], "interval": "60m", "lookback_days": 60, "auto_adjust": False, "kwargs": {}}
    assert not hasattr(technical_sources_module, "yahoo_client")  # no independent fetch path left in this module


def test_fmp_technical_source_reads_the_shared_cache_like_the_other(monkeypatch):
    # P4: FMP intraday is live (the 402 note was stale); provider choice lives in the shared
    # cache, so this reader no longer raises.
    async def fake_batch(tickers, interval, lookback_days, auto_adjust=True, **kwargs):
        return {"AAPL": _sample_ohlcv().rename(columns=str.lower)}

    monkeypatch.setattr(technical_sources_module, "get_or_fetch_bars_batch", fake_batch)
    result = asyncio.run(FMPTechnicalSource().get_intraday_bars(["AAPL"], lookback_days=60))
    assert "AAPL" in result


def test_get_technical_source_always_returns_yahoo(monkeypatch):
    # Provider choice (FMP first, Yahoo fallback per the `intraday_bars` group) lives in the
    # shared bars cache, so the selector never flips on the master switch.
    from core.config import settings

    _dg.set_master(True)
    assert isinstance(get_technical_source(), YahooTechnicalSource)

    _dg.set_master(False)
    assert isinstance(get_technical_source(), YahooTechnicalSource)
