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
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session

from clients.fmp_client import fmp_client
from clients.yahoo_cache import get_or_fetch_price_history_batch
from core.cache import force_fetch, get_or_fetch
from core.config import settings
from core.db import engine

logger = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")
_MARKET_CLOSE_HOUR_ET = 16  # 4:00pm ET, ignored on minute precision -- see
# _most_recent_completed_trading_date's own docstring for why that's fine here.

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


def _most_recent_completed_trading_date(reference: datetime | None = None) -> date:
    """The most recent US/Eastern calendar date whose regular trading session
    has already closed, as of `reference` (default: now). Weekend-aware,
    deliberately NOT holiday-aware -- a real trading-calendar dependency was
    called out as a lower-value follow-up in
    docs/chart_tab_missing_bar_investigation_2026-09-18.md's "Proposed fix"
    section (option 2, which this implements), not required to close the
    live bug this function exists for. `reference` is assumed UTC if naive,
    matching this codebase's own `datetime.now()` convention elsewhere
    (core/cache.py) on a server whose system timezone is UTC."""
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    eastern_now = ref.astimezone(_EASTERN)
    session_date = eastern_now.date()
    if eastern_now.hour < _MARKET_CLOSE_HOUR_ET:
        session_date -= timedelta(days=1)
    while session_date.weekday() >= 5:  # Saturday=5, Sunday=6
        session_date -= timedelta(days=1)
    return session_date


def _last_bar_date(rows: list[dict]) -> date:
    return max(date.fromisoformat(r["date"]) for r in rows)


async def _fetch_fmp_daily_bars(ticker: str, from_date: date, to_date: date, lookback_years: int) -> pd.DataFrame:
    # Cache key incorporates the caller's actual lookback_years (not the
    # LOOKBACK_YEARS module constant) so D_6M/D_1Y ("2y"), D_2Y ("3y"), W_4Y
    # ("8y"), and Liquidity Zone ("4y") each get their own cache row instead
    # of colliding on one shared "4y" row regardless of how much history the
    # caller actually asked for -- confirmed live in production causing stale
    # reads, see CLAUDE.md's Liquidity Zone section.
    period = f"{lookback_years}y"
    fetch_fn = lambda: fmp_client.get_historical_price_eod(ticker, from_date.isoformat(), to_date.isoformat())  # noqa: E731
    with Session(engine) as session:
        data = await get_or_fetch(
            session,
            ticker,
            "historical_price_eod",
            period,
            fetch_fn,
            settings.daily_bar_staleness_days,
        )
        rows = data if isinstance(data, list) else []
        # daily_bar_staleness_days alone isn't enough: it's a flat 24h TTL
        # from fetched_at with no concept of market close, so a row fetched
        # any time before a trading day's close can still read as "fresh" a
        # full day later, regardless of when close actually happened in
        # between -- confirmed live (CLAUDE.md's Liquidity Zone section,
        # docs/chart_tab_missing_bar_investigation_2026-09-18.md) as the
        # same mechanism that hit the Chart tab. Fixed there by dropping
        # caching entirely (that feature is viewed many times a day, so the
        # cache bought little); kept here since this job runs the fetch
        # exactly once nightly regardless, so the cache is genuinely
        # load-bearing -- instead, treat a cache hit whose own last bar
        # predates the most recently completed session as stale and force a
        # live refetch, ignoring the TTL. Scoped to this one call site only:
        # get_or_fetch's own staleness_days contract, and daily_bar_
        # staleness_days's meaning for any other future consumer of
        # FMPDailyBarSource (there is currently none -- the Chart tab moved
        # off this cache entirely, see chart_data.py), are both unchanged.
        if rows and _last_bar_date(rows) < _most_recent_completed_trading_date():
            data = await force_fetch(session, ticker, "historical_price_eod", period, fetch_fn)
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
    through daily_bar_staleness_days-gated cache (a distinct, much tighter
    window than the general cache_staleness_days -- see that setting's own
    comment in core/config.py), PLUS a market-close-aware check on top (see
    _fetch_fmp_daily_bars) that forces a live refetch regardless of that TTL
    whenever the cached series doesn't yet reflect the most recently
    completed session -- so a steady-state nightly run (warm cache, and
    that cache's last bar genuinely already reflects last close) makes zero
    live FMP calls for most tickers."""

    async def get_daily_bars(self, tickers: list[str], lookback_years: int) -> dict[str, pd.DataFrame]:
        to_date = date.today()
        from_date = to_date - timedelta(days=365 * lookback_years)
        result: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            df = await _fetch_fmp_daily_bars(ticker, from_date, to_date, lookback_years)
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
