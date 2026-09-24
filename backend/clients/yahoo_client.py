"""Thin wrapper around yfinance for daily OHLCV price data -- the non-FMP
data source powering trend-structure analysis (see analysis/trend_structure/)
and, when FMP is paused, the price/quote fallback (see data/ticker_summary.py).
Mirrors clients/fmp_client.py's shape (a thin client class + module-level
singleton), but deliberately has no FMP-data-group-style kill switch: nothing in
this app's design asks for one, and Yahoo Finance is a free/unauthenticated
endpoint with no subscription to pause the way FMP's paid tier needs -- a
considered-and-rejected symmetry, not an oversight.
"""

import asyncio
import logging

import pandas as pd
import yfinance as yf

from core.data_source_health import record_success

logger = logging.getLogger(__name__)


class YahooClient:
    """Batch OHLCV fetch via yfinance's multi-ticker download -- one HTTP
    round-trip for the whole tracked universe, not one call per ticker (see
    pipeline/nightly_trend_calculation.py). yfinance's `download` is
    synchronous/blocking; every other async data-layer function in this
    codebase awaits, so this runs it in a worker thread via
    asyncio.to_thread rather than stalling the event loop."""

    async def get_history(
        self, tickers: list[str], period: str = "2y", interval: str = "1d", auto_adjust: bool = True
    ) -> dict[str, pd.DataFrame]:
        """Returns {ticker: OHLCV DataFrame} for every ticker yfinance
        actually returned real data for -- a bad/delisted/typo'd ticker is
        simply absent from the returned dict rather than raising, so one bad
        symbol in a large batch never fails the whole fetch (mirrors
        nightly_fundamentals_fetch.py's per-ticker try/except isolation, at
        the batch layer here since this is one call for N tickers, not N
        separate calls).

        auto_adjust defaults to True (split/dividend-adjusted closes) --
        this was this client's original tuning, chosen for trend-structure's
        swing/ATR/BOS engine, where continuity across a corporate action
        mattered more than raw price-level fidelity. That tradeoff was
        revisited 2026-09-18: adjusted closes showed a confirmed ~1-7%
        divergence vs. FMP for dividend-heavy tickers (O/UNH/F), so every
        technical-analysis consumer -- Chart, Weinstein Stage, Trend,
        Liquidity Zones, Warren, BB+RSI -- now passes auto_adjust=False
        explicitly at its own call site instead of relying on this default.
        The default itself is deliberately left at True, unchanged: Price/
        Quote's Yahoo fallback (data/ticker_summary.py::
        _fetch_yahoo_latest_close) and the unrelated Momentum feature
        (data/momentum_data.py) don't pass this parameter at all, so they
        keep today's behavior rather than silently picking up a change
        neither asked for."""
        if not tickers:
            return {}
        try:
            raw = await asyncio.to_thread(
                yf.download,
                tickers,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=auto_adjust,
                threads=True,
                progress=False,
            )
        except Exception:
            logger.warning("Yahoo Finance batch download failed for %d ticker(s)", len(tickers))
            return {}

        # The live call itself succeeded (no exception) -- this is the same
        # "got a response" bar FMPClient.get records success at, not "did
        # every requested ticker have real data" (checked next).
        record_success("yahoo")

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

    async def get_dividends(self, ticker: str) -> pd.Series:
        """Ex-dividend-date-indexed (tz-aware, exchange-local) series of
        split-adjusted per-share dividend amounts -- the same split-adjusted
        basis Yahoo's Close column uses. Empty for a non-payer. Unlike
        get_history above, exceptions PROPAGATE: the one consumer
        (data/chart_events_data.py) needs "the fetch failed" distinguishable
        from "this ticker pays no dividend"."""
        series = await asyncio.to_thread(lambda: yf.Ticker(ticker).dividends)
        record_success("yahoo")
        return series if series is not None else pd.Series(dtype=float)

    async def get_earnings_dates(self, ticker: str, limit: int = 40) -> pd.DataFrame:
        """Earnings-date-indexed (tz-aware, exchange-local, time-of-day
        included) frame with 'EPS Estimate' / 'Reported EPS' / 'Surprise(%)'
        columns, newest first. Includes the next scheduled date with NaN
        actuals. Empty for a symbol Yahoo has no earnings calendar for (ETFs).
        Exceptions propagate, same reasoning as get_dividends."""
        frame = await asyncio.to_thread(lambda: yf.Ticker(ticker).get_earnings_dates(limit=limit))
        record_success("yahoo")
        return frame if frame is not None else pd.DataFrame()


yahoo_client = YahooClient()
