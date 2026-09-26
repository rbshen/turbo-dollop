"""Intraday OHLCV bar source for the technical entry-signal features (see analysis/entry_signal/,
data/entry_signal_data.py, Warren). FMP `/historical-chart/1hour` (data group `intraday_bars`) is
the only provider; the source below is a thin reader of the shared bars cache
(clients/shared_bars_cache.py), which owns the fetch and the group gate. Yahoo Finance was
removed in Phase 6b (2026-09-26).
"""

import logging
from typing import Protocol

import pandas as pd

from clients.shared_bars_cache import INTRADAY_INTERVAL, get_or_fetch_bars_batch

logger = logging.getLogger(__name__)

# The raw bar interval (INTRADAY_INTERVAL, "60m" -- defined in
# clients/shared_bars_cache.py, re-exported here) was validated during the Phase 1
# investigation (30m and 60m bars resample to bit-identical 2h candles and
# RSI/%B series) -- 60m halves
# the row count for the same 2h-candle result, so it's the one actually used.
__all__ = ["INTRADAY_INTERVAL", "IntradayBarSource", "FMPTechnicalSource", "get_technical_source"]


class IntradayBarSource(Protocol):
    async def get_intraday_bars(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        """Returns {ticker: OHLCV DataFrame} (lowercase open/high/low/close/
        volume columns, ascending datetime index) for every ticker real bars
        were found for -- a bad/delisted ticker is simply absent, not an
        error (per-ticker-tolerant). Batch-shaped (all tickers in one
        call), not per-ticker -- this app's established nightly-job
        convention (see pipeline/nightly_trend_calculation.py) of one
        multi-ticker fetch rather than N separate ones."""
        ...


class FMPTechnicalSource:
    """Reads through the shared bars cache (clients/shared_bars_cache.py, interval "60m"), NOT
    its own fetch: Warren's nightly job reads the very same (ticker, "60m") row at a much wider
    (2y) window, so a 60-day request is served from whatever Warren (or an earlier run of the
    BB+RSI job) already fetched whenever that row is still close-fresh and wide enough -- and
    whichever job runs first on a given night does the one live fetch. auto_adjust is moot (FMP
    intraday is split-adjusted, never dividend-adjusted). The cache hands back lowercase columns
    and an America/New_York tz-aware index, which is what
    analysis/entry_signal/resample.py::build_2h_session_candles requires."""

    async def get_intraday_bars(self, tickers: list[str], lookback_days: int) -> dict[str, pd.DataFrame]:
        return await get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, lookback_days, auto_adjust=False)


def get_technical_source() -> IntradayBarSource:
    """The shared-cache reader; the `intraday_bars` data group is honored inside
    clients/shared_bars_cache.py, not here."""
    return FMPTechnicalSource()
