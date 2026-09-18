"""Daily EOD OHLCV bar fetch for Liquidity Zone (LP) detection (see
analysis/liquidity_zones/, data/liquidity_zone_data.py).

**Yahoo Finance only, unconditionally, non-dividend-adjusted (2026-09-18).**
This module used to be a dual-source adapter (`DailyBarSource` protocol,
`FMPDailyBarSource`/`YahooDailyBarSource`, `get_daily_bar_source()` picking
between them via `settings.fmp_enabled`) -- FMP's daily EOD endpoint isn't
plan-restricted the way BB+RSI's intraday feed is, so this used to follow
the ordinary FMP-when-enabled/Yahoo-fallback pattern every other feature in
this app uses. That branch is removed entirely: Liquidity Zones is one of
six technical-analysis features (alongside Chart, Weinstein Stage, Trend,
Warren, BB+RSI) moved to Yahoo-only, regardless of FMP_ENABLED, so a paused
FMP subscription can never affect what price levels this feature detects.
`get_daily_bars` below passes `auto_adjust=False` explicitly to
`clients/yahoo_cache.py::get_or_fetch_price_history_batch` -- Yahoo's own
default (True, still used by Price/Quote's unrelated fallback and by
Momentum) is split/dividend-adjusted, which showed a confirmed ~1-7%
divergence vs. FMP's raw closes for dividend-heavy tickers (O/UNH/F);
support/resistance levels should reflect actually-traded prices, not a
retroactively-rescaled series.

This also retires the entire FMPDailyBarSource machinery this module used
to carry -- the market-close-aware freshness check
(`_most_recent_completed_trading_date`), the `FundamentalsCache`-backed
`get_or_fetch`/`force_fetch` plumbing, and `daily_bar_staleness_days` (now
unused anywhere in the codebase, removed from core/config.py) -- all of
that existed specifically to keep FMP's own cached daily-bar rows honest
about market close, a problem that doesn't exist for this module's new
sole path: `get_or_fetch_price_history_batch` already has its own
staleness handling (Settings.yahoo_price_cache_staleness_days, see
clients/yahoo_cache.py), unchanged by this rewrite.
"""

import pandas as pd

from clients.yahoo_cache import get_or_fetch_price_history_batch

# /historical-price-eod/full silently capped at 5000 rows regardless of the
# from/to span requested (an FMP-specific limit from this module's earlier
# dual-source days) -- kept as the lookback window Liquidity Zone's nightly
# job requests, since 4 calendar years of daily bars comfortably covers
# both this feature's Daily (1yr) and Weekly (4yr, resampled locally)
# lookback needs from a single fetch per ticker.
LOOKBACK_YEARS = 4

# yfinance's period enum has no "4y" value (1d/5d/1mo/3mo/6mo/1y/2y/5y/
# 10y/ytd/max only) -- data/liquidity_zone_data.py trims the fetched frame
# down to the trailing LOOKBACK_YEARS window before use, so requesting one
# enum value up costs nothing extra.
_YAHOO_FETCH_PERIOD = "5y"


async def get_daily_bars(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """One batch call via clients.yahoo_cache.get_or_fetch_price_history_batch
    (already used by pipeline/nightly_trend_calculation.py) -- Yahoo has a
    real multi-ticker download, unlike FMP's old per-ticker endpoint this
    module no longer calls.

    force=True: this shared cache's staleness check is time-based (was
    this ticker's cache refreshed recently?), not coverage-based (does the
    cache actually hold LOOKBACK_YEARS of history?) -- every ticker this
    function is called with is also covered by pipeline/
    nightly_trend_calculation.py's own full-universe fetch (period="2y"),
    which runs 15 minutes earlier in cron. Without forcing a live fetch
    here, that earlier, shorter fetch would leave this ticker's cache
    "fresh" by the time this job runs, silently serving ~2 years of
    history instead of the ~5 requested and truncating the Weekly (4yr)
    timeframe every night. See get_or_fetch_price_history_batch's own
    docstring for the full mechanism -- forcing is cheap here since this
    function's own population (the W1-W5 watchlist union, capped at 500
    tickers total) is small."""
    rows_by_ticker = await get_or_fetch_price_history_batch(tickers, period=_YAHOO_FETCH_PERIOD, auto_adjust=False, force=True)
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
