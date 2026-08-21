"""Thin wrapper around yfinance for daily OHLCV price data -- the non-FMP
data source powering trend-structure analysis (see analysis/trend_structure/)
and, when FMP is paused, the price/quote fallback (see data/ticker_summary.py).
Mirrors clients/fmp_client.py's shape (a thin client class + module-level
singleton), but deliberately has no FMP_ENABLED-style kill switch: nothing in
this app's design asks for one, and Yahoo Finance is a free/unauthenticated
endpoint with no subscription to pause the way FMP's paid tier needs -- a
considered-and-rejected symmetry, not an oversight.
"""

import asyncio
import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YahooClient:
    """Batch OHLCV fetch via yfinance's multi-ticker download -- one HTTP
    round-trip for the whole tracked universe, not one call per ticker (see
    pipeline/nightly_trend_calculation.py). yfinance's `download` is
    synchronous/blocking; every other async data-layer function in this
    codebase awaits, so this runs it in a worker thread via
    asyncio.to_thread rather than stalling the event loop."""

    async def get_history(
        self, tickers: list[str], period: str = "2y", interval: str = "1d"
    ) -> dict[str, pd.DataFrame]:
        """Returns {ticker: OHLCV DataFrame} for every ticker yfinance
        actually returned real data for -- a bad/delisted/typo'd ticker is
        simply absent from the returned dict rather than raising, so one bad
        symbol in a large batch never fails the whole fetch (mirrors
        nightly_fundamentals_fetch.py's per-ticker try/except isolation, at
        the batch layer here since this is one call for N tickers, not N
        separate calls). auto_adjust=True (split/dividend-adjusted closes) --
        swing/ATR structure should be continuous across a split, not show a
        false gap."""
        if not tickers:
            return {}
        try:
            raw = await asyncio.to_thread(
                yf.download,
                tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception:
            logger.warning("Yahoo Finance batch download failed for %d ticker(s)", len(tickers))
            return {}

        if raw is None or raw.empty:
            return {}

        result: dict[str, pd.DataFrame] = {}
        is_multi = isinstance(raw.columns, pd.MultiIndex)
        for ticker in tickers:
            try:
                df = raw[ticker] if is_multi else raw
            except KeyError:
                continue
            df = df.dropna(subset=["Close"])
            if df.empty:
                continue
            result[ticker] = df
        return result


yahoo_client = YahooClient()
