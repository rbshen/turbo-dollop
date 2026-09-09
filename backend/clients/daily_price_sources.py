"""Dual data-source adapter for daily EOD OHLCV bars, feeding Liquidity
Zone (LP) detection (see analysis/liquidity_zones/, data/liquidity_zone_data.py).
Mirrors clients/technical_sources.py's protocol/adapter shape, but for
daily bars and with the ORDINARY settings.fmp_enabled toggle -- unlike
BB+RSI's intraday feed, FMP's daily EOD endpoint isn't plan-restricted
(confirmed via FMPClient.get_historical_price_eod, already used in
production by data/ticker_summary.py and analysis/ma_magnet/data.py), so
this follows the normal FMP-when-enabled/Yahoo-fallback pattern instead
of BB+RSI's hard-forced single source.
"""

import logging
from datetime import date, timedelta
from typing import Protocol

import pandas as pd
from sqlmodel import Session

from clients.fmp_client import fmp_client
from clients.yahoo_cache import get_or_fetch_price_history_batch
from core.cache import get_or_fetch
from core.config import settings
from core.db import engine

logger = logging.getLogger(__name__)

# /historical-price-eod/full silently caps at 5000 rows regardless of the
# from/to span requested (confirmed empirically, see
# analysis/ma_magnet/data.py's own comment) -- 4 calendar years of daily
# bars (~1000 trading days) stays comfortably under that cap in one call,
# and covers both this feature's Daily (1yr) and Weekly (4yr, resampled
# locally) lookback needs from a single fetch per ticker.
LOOKBACK_YEARS = 4

# yfinance's period enum has no "4y" value (1d/5d/1mo/3mo/6mo/1y/2y/5y/
# 10y/ytd/max only) -- the Yahoo fallback fetches the next enum value up
# and data/liquidity_zone_data.py trims every source's frame down to the
# same trailing LOOKBACK_YEARS window before use, so both sources feed
# the engine an identically-sized window regardless of which one served
# the data.
_YAHOO_FALLBACK_PERIOD = "5y"


class DailyBarSource(Protocol):
    async def get_daily_bars(self, tickers: list[str], lookback_years: int) -> dict[str, pd.DataFrame]:
        """Returns {ticker: OHLCV DataFrame} (lowercase open/high/low/close/
        volume columns, ascending DatetimeIndex) for every ticker real bars
        were found for -- a bad/delisted ticker is simply absent, not an
        error."""
        ...


async def _fetch_fmp_daily_bars(ticker: str, from_date: date, to_date: date) -> pd.DataFrame:
    with Session(engine) as session:
        data = await get_or_fetch(
            session,
            ticker,
            "historical_price_eod",
            f"{LOOKBACK_YEARS}y",
            lambda: fmp_client.get_historical_price_eod(ticker, from_date.isoformat(), to_date.isoformat()),
            settings.cache_staleness_days,
        )
    rows = data if isinstance(data, list) else []
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows).drop_duplicates(subset="date")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    return df[["open", "high", "low", "close", "volume"]]


class FMPDailyBarSource:
    """FMP has no multi-ticker batch endpoint for historical EOD bars --
    get_historical_price_eod is single-ticker -- so this loops per ticker,
    same shape as analysis/ma_magnet/data.py's own fetch. Each call goes
    through the normal cache_staleness_days-gated cache, so a steady-state
    nightly run (warm cache) makes zero live FMP calls for most tickers."""

    async def get_daily_bars(self, tickers: list[str], lookback_years: int) -> dict[str, pd.DataFrame]:
        to_date = date.today()
        from_date = to_date - timedelta(days=365 * lookback_years)
        result: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            df = await _fetch_fmp_daily_bars(ticker, from_date, to_date)
            if not df.empty:
                result[ticker] = df
        return result


class YahooDailyBarSource:
    """One batch call via clients.yahoo_cache.get_or_fetch_price_history_batch
    (already used by pipeline/nightly_trend_calculation.py) -- Yahoo has a
    real multi-ticker download, unlike FMP's per-ticker endpoint.

    Note: get_or_fetch_price_history_batch's staleness check is time-based
    (was this ticker's cache refreshed recently?), not coverage-based (does
    the cache actually hold `lookback_years` of history?) -- if another
    job already refreshed this ticker's YahooPriceCache rows today with a
    shorter period, this call can return less history than requested
    without triggering a fresh fetch. This is an existing, general
    property of that shared cache, not something this adapter works
    around; the engine already degrades gracefully on thinner-than-usual
    history (fewer/no confirmed swings), matching every other consumer of
    this cache."""

    async def get_daily_bars(self, tickers: list[str], lookback_years: int) -> dict[str, pd.DataFrame]:
        rows_by_ticker = await get_or_fetch_price_history_batch(tickers, period=_YAHOO_FALLBACK_PERIOD)
        result: dict[str, pd.DataFrame] = {}
        for ticker, rows in rows_by_ticker.items():
            if not rows:
                continue
            data = {
                "open": [r.open for r in rows],
                "high": [r.high for r in rows],
                "low": [r.low for r in rows],
                "close": [r.close for r in rows],
                "volume": [r.volume for r in rows],
            }
            index = pd.DatetimeIndex([r.date for r in rows])
            result[ticker] = pd.DataFrame(data, index=index)
        return result


def get_daily_bar_source() -> DailyBarSource:
    """FMP when the subscription is enabled (daily/weekly aggregates aren't
    plan-restricted, unlike BB+RSI's intraday feed -- see module
    docstring), Yahoo Finance fallback otherwise -- the ordinary
    settings.fmp_enabled toggle every other feature in this app uses,
    unlike clients/technical_sources.py's hard-forced single source."""
    return FMPDailyBarSource() if settings.fmp_enabled else YahooDailyBarSource()
