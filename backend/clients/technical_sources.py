"""Dual data-source adapter for intraday OHLCV bars, feeding the technical
entry-signal feature (see analysis/entry_signal/, data/entry_signal_data.py).
Mirrors clients/fmp_client.py's/clients/yahoo_client.py's thin-client-class
shape, and the rest of this app's data-group-gated source-selection
pattern -- with one deliberate deviation, explained on get_technical_source
below.

History: on 2026-09-09 every FMP intraday interval returned HTTP 402 under Fathom's plan,
so this feature was Yahoo-only. That is stale -- FMP's `/historical-chart/1hour` answers 200
(re-verified 2026-09-24 and 2026-09-26) and, since P4 (2026-09-26), is the primary source of the
shared "60m" bars for US-listed tickers (data group `intraday_bars`, see
clients/daily_bar_sources.py::FMPIntradaySource), with Yahoo as the fallback. Both sources
are reached through clients/shared_bars_cache.py, so the classes below are thin readers of it.
"""

import logging
from typing import Protocol

import pandas as pd

from clients.shared_bars_cache import INTRADAY_INTERVAL, get_or_fetch_bars_batch

logger = logging.getLogger(__name__)

# The raw bar interval (INTRADAY_INTERVAL, "60m" -- defined in
# clients/shared_bars_cache.py, re-exported here) matches yfinance's own
# granularity choice validated during the Phase 1 investigation (30m and 60m
# bars resample to bit-identical 2h candles and RSI/%B series) -- 60m halves
# the row count for the same 2h-candle result, so it's the one actually used.
__all__ = ["INTRADAY_INTERVAL", "IntradayBarSource", "YahooTechnicalSource", "FMPTechnicalSource", "get_technical_source"]


class IntradayBarSource(Protocol):
    async def get_intraday_bars(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        """Returns {ticker: OHLCV DataFrame} (lowercase open/high/low/close/
        volume columns, ascending datetime index) for every ticker real bars
        were found for -- a bad/delisted ticker is simply absent, not an
        error, matching clients/yahoo_client.py::YahooClient.get_history's
        own per-ticker-tolerant convention. Batch-shaped (all tickers in one
        call), not per-ticker -- this app's established nightly-job
        convention (see pipeline/nightly_trend_calculation.py) of one
        multi-ticker fetch rather than N separate ones."""
        ...


class YahooTechnicalSource:
    """The reader wired in today -- see module docstring (the name predates P4; the bars it
    returns are FMP's for US-listed tickers, Yahoo's otherwise/as fallback).

    Reads through the shared bars cache (clients/shared_bars_cache.py,
    interval "60m"), NOT its own independent Yahoo fetch: Warren's nightly
    job reads the very same (ticker, "60m") row at a much wider (2y) window,
    so this 60-day request is served from whatever Warren (or an earlier
    run of this job) already fetched whenever that row is still close-fresh
    and wide enough -- and whichever of the two jobs runs first on a given
    night does the one live fetch that keeps it fresh. auto_adjust=False
    (2026-09-18): raw, non-dividend-adjusted bars. The cache hands back
    lowercase columns and an America/New_York tz-aware index already, which
    is what analysis/entry_signal/resample.py::build_2h_session_candles
    requires."""

    async def get_intraday_bars(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        return await get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, lookback_days, auto_adjust=False)


class FMPTechnicalSource:
    """Kept for API symmetry only. FMP intraday is no longer unavailable (see module
    docstring), but source choice now lives inside the shared bars cache
    (FMP first, Yahoo fallback), so there is nothing separate to select here."""

    async def get_intraday_bars(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        return await get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, lookback_days, auto_adjust=False)


def get_technical_source() -> IntradayBarSource:
    """The shared-cache reader. Which provider actually serves the bars (FMP, else Yahoo) is
    decided inside clients/shared_bars_cache.py per the `intraday_bars` data group, not here."""
    return YahooTechnicalSource()
