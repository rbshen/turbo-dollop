"""Dual data-source adapter for DAILY ("1d" only) OHLCV bars, feeding
clients/shared_bars_cache.py's "1d" fetch step. Mirrors
clients/technical_sources.py's IntradayBarSource Protocol shape -- same
idea, applied here to the daily-bar fetch instead of the intraday one.
The 60m interval (Warren/BB+RSI) is untouched by this module and stays
exclusively Yahoo -- a separate, later migration phase (see
docs/massive_feasibility_investigation_2026-09-23.md's own "Starter
paid-plan verification" section for why intraday session-anchoring is a
materially different problem).

Massive/Polygon (clients/massive_client.py) is now the primary daily-bar
source for every US-listed ticker; Yahoo Finance stays wired in for
non-US tickers (core/tickers.py::is_non_us_ticker) and as an automatic
per-ticker fallback whenever Massive errors or returns no data for a
ticker it should otherwise cover (confirmed with the user: auto-fallback,
not a hard job failure -- paired with clients/shared_bars_cache.py's
stale_ticker_count guard so a still-stale ticker after both sources tried
is visible in the nightly job's own cron_heartbeat message, not silent)."""

import logging
from datetime import date, timedelta
from typing import Protocol

import pandas as pd
from sqlalchemy import func
from sqlmodel import Session, select

from clients.massive_client import massive_client
from clients.yahoo_client import yahoo_client
from core.config import settings
from core.db import engine
from core.models import SharedBarsCache
from core.tickers import from_massive_symbol, is_non_us_ticker, to_massive_symbol

logger = logging.getLogger(__name__)

DAILY_INTERVAL = "1d"

__all__ = [
    "DAILY_INTERVAL",
    "DailyBarSource",
    "YahooDailySource",
    "MassiveDailySource",
    "MassiveWithYahooFallback",
    "get_daily_bar_source",
    "route_by_source",
]


class DailyBarSource(Protocol):
    async def get_daily_bars(
        self, tickers_with_days: dict[str, int], auto_adjust: bool, reference: date | None = None
    ) -> dict[str, pd.DataFrame]:
        """`tickers_with_days`: {ticker: how many calendar days of daily
        history this ticker needs, counting back from today}. `reference`
        overrides "today" (default: date.today()) -- a plain testability
        seam, matching the same parameter clients/shared_bars_cache.py's
        own "as-of" functions already take. Returns {ticker: OHLCV
        DataFrame} (lowercase columns, naive DatetimeIndex) for every
        ticker real bars were found for -- a bad/delisted/no-data ticker is
        simply absent, not an error, matching
        clients/yahoo_client.py::YahooClient.get_history's own
        per-ticker-tolerant convention."""
        ...


def route_by_source(tickers_with_days: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """Splits a {ticker: days} map into (us_eligible, non_us) using
    core/tickers.py::is_non_us_ticker -- the dot-suffix check. Non-US
    tickers are never attempted on Massive at all (confirmed US-market-only
    in the feasibility investigation §2j)."""
    us: dict[str, int] = {}
    non_us: dict[str, int] = {}
    for ticker, days in tickers_with_days.items():
        (non_us if is_non_us_ticker(ticker) else us)[ticker] = days
    return us, non_us


# yfinance's period enum -- the same tiering idea as
# clients/shared_bars_cache.py's own _DAILY_PERIOD_STEPS, kept as a small,
# separate copy here rather than imported from there: shared_bars_cache.py
# imports THIS module (for routing), so the reverse import would be
# circular. This is a small, stable, Yahoo-API-specific detail (which
# period string covers N days), not worth a shared module for a handful of
# lines duplicated in exactly one other, already-tested place.
_DAILY_PERIOD_STEPS: list[tuple[str, int]] = [
    ("1mo", 30), ("3mo", 90), ("6mo", 180), ("1y", 365), ("2y", 730), ("5y", 1825), ("10y", 3650),
]


def _yahoo_period_for(days: int) -> str:
    for period, tier_days in _DAILY_PERIOD_STEPS:
        if tier_days >= days:
            return period
    return _DAILY_PERIOD_STEPS[-1][0]  # clamp to the widest available tier


class YahooDailySource:
    """Today's exact daily-bar fetch mechanism (period-bucketed batch
    yf.download calls), moved out of clients/shared_bars_cache.py
    unchanged in behavior -- used directly for non-US tickers, and as
    MassiveWithYahooFallback's own fallback for any US ticker Massive
    couldn't serve."""

    async def get_daily_bars(
        self, tickers_with_days: dict[str, int], auto_adjust: bool, reference: date | None = None
    ) -> dict[str, pd.DataFrame]:
        if not tickers_with_days:
            return {}
        by_period: dict[str, list[str]] = {}
        for ticker, days in tickers_with_days.items():
            by_period.setdefault(_yahoo_period_for(days), []).append(ticker)
        result: dict[str, pd.DataFrame] = {}
        for period, group in by_period.items():
            fetched = await yahoo_client.get_history(group, period=period, interval=DAILY_INTERVAL, auto_adjust=auto_adjust)
            result.update(fetched)
        return result


# A ticker missing more than this many days' worth of bars gets a full
# per-ticker range refetch instead of being chased day-by-day through
# grouped-daily -- bounds the grouped-daily loop below to a handful of
# calls even after a multi-day Massive outage, and matches this module's
# own "insufficient vs. merely stale" split that
# clients/shared_bars_cache.py's freshness check already reasons about.
_BACKFILL_RECENCY_SLACK_DAYS = 5


class MassiveDailySource:
    """Massive/Polygon-backed DailyBarSource. Per ticker in the batch:

    - Never-cached or genuinely too-narrow existing history (the
      'insufficient' case), or a ticker that just split -- one per-ticker
      `/v2/aggs/ticker/.../range/1/day/...` call for its full requested
      window (no pagination expected within a 5y window, confirmed in the
      feasibility investigation).
    - Otherwise merely stale (has enough depth, just missing the last few
      trading days) -- one `/v2/aggs/grouped/.../{date}` call PER MISSING
      CALENDAR DAY, shared across every ticker missing that day, rather
      than one call per ticker (the investigation's Part 3 recommendation:
      grouped-daily is a single whole-US-market call).

    A recent split (checked once per run via massive_client.get_recent_splits,
    no per-ticker call) forces the affected ticker onto the backfill path
    regardless of its existing depth, so a post-split cache never mixes
    pre- and post-split scale silently."""

    def __init__(self, client=massive_client) -> None:
        self._client = client

    async def get_daily_bars(
        self, tickers_with_days: dict[str, int], auto_adjust: bool, reference: date | None = None
    ) -> dict[str, pd.DataFrame]:
        if not tickers_with_days:
            return {}
        today = reference or date.today()

        split_tickers = await self._recently_split_tickers(today)
        existing_span = self._existing_span(list(tickers_with_days))

        needs_backfill: list[str] = []
        needs_incremental: list[str] = []
        for ticker, days in tickers_with_days.items():
            first_bar, last_bar = existing_span.get(ticker, (None, None))
            needed_start = today - timedelta(days=max(days - 1, 0))
            if ticker in split_tickers or first_bar is None or first_bar > needed_start:
                needs_backfill.append(ticker)
            elif (today - last_bar).days > _BACKFILL_RECENCY_SLACK_DAYS:
                needs_backfill.append(ticker)
            else:
                needs_incremental.append(ticker)

        result: dict[str, pd.DataFrame] = {}
        for ticker in needs_backfill:
            days = tickers_with_days[ticker]
            df = await self._client.get_daily_bars(
                to_massive_symbol(ticker), today - timedelta(days=days), today, adjusted=auto_adjust
            )
            if not df.empty:
                result[ticker] = df

        if needs_incremental:
            result.update(await self._fill_incremental(needs_incremental, existing_span, today, auto_adjust))

        return result

    async def _fill_incremental(
        self, tickers: list[str], existing_span: dict[str, tuple[date, date]], today: date, auto_adjust: bool
    ) -> dict[str, pd.DataFrame]:
        oldest_last_bar = min(existing_span[t][1] for t in tickers)
        candidate_days = [oldest_last_bar + timedelta(days=i) for i in range(1, (today - oldest_last_bar).days + 1)]

        by_ticker: dict[str, list[pd.DataFrame]] = {}
        for day in candidate_days:
            try:
                grouped = await self._client.get_grouped_daily(day, adjusted=auto_adjust)
            except Exception:
                logger.warning("Massive grouped-daily fetch failed for %s; %d ticker(s) stay stale this run", day, len(tickers))
                continue
            if not grouped:
                continue
            for ticker in tickers:
                if day <= existing_span[ticker][1]:
                    continue  # this ticker already has a bar on/after this day
                bar = grouped.get(to_massive_symbol(ticker))
                if bar is not None:
                    by_ticker.setdefault(ticker, []).append(bar)

        return {ticker: pd.concat(frames).sort_index() for ticker, frames in by_ticker.items()}

    async def _recently_split_tickers(self, today: date) -> set[str]:
        # A week of lookback is ample -- a split older than that would
        # already have triggered a backfill (which fully replaces the
        # ticker's cached history) on a prior night.
        since = today - timedelta(days=7)
        try:
            splits = await self._client.get_recent_splits(since)
        except Exception:
            logger.warning("Massive splits check failed; proceeding without split-triggered refetch this run")
            return set()
        return {from_massive_symbol(s["ticker"]) for s in splits if s.get("ticker")}

    @staticmethod
    def _existing_span(tickers: list[str]) -> dict[str, tuple[date, date]]:
        """(first bar date, last bar date) per ticker already in
        SharedBarsCache for interval="1d" -- a small, self-contained query
        (not clients/shared_bars_cache.py::_cache_span, to avoid a circular
        import; see that function's own docstring for the equivalent
        reasoning on why this stays a single grouped query rather than a
        per-ticker one)."""
        if not tickers:
            return {}
        with Session(engine) as session:
            stmt = (
                select(SharedBarsCache.ticker, func.min(SharedBarsCache.bar_time), func.max(SharedBarsCache.bar_time))
                .where(SharedBarsCache.interval == DAILY_INTERVAL, SharedBarsCache.ticker.in_(tickers))
                .group_by(SharedBarsCache.ticker)
            )
            return {t: (first.date(), last.date()) for t, first, last in session.exec(stmt).all()}


class MassiveWithYahooFallback:
    """Tries Massive for the whole batch; on a total failure (network/HTTP
    error surviving MassiveClient's own retries) falls back to Yahoo for
    everything. On a partial result (some tickers came back empty -- e.g.
    an OTC symbol Massive doesn't cover, see core/tickers.py::
    is_non_us_ticker's own docstring), falls back to Yahoo per-ticker only
    for the tickers Massive didn't deliver. Confirmed with the user as the
    intended fallback policy (auto-fallback, logged, never a hard job
    failure) -- clients/shared_bars_cache.py's stale_ticker_count is the
    guard that keeps a still-stale ticker after both attempts visible."""

    def __init__(self, massive: DailyBarSource | None = None, yahoo: DailyBarSource | None = None) -> None:
        self._massive = massive or MassiveDailySource()
        self._yahoo = yahoo or YahooDailySource()

    async def get_daily_bars(
        self, tickers_with_days: dict[str, int], auto_adjust: bool, reference: date | None = None
    ) -> dict[str, pd.DataFrame]:
        try:
            result = await self._massive.get_daily_bars(tickers_with_days, auto_adjust, reference=reference)
        except Exception:
            logger.warning(
                "Massive daily-bar fetch failed entirely for %d ticker(s); falling back to Yahoo for all of them",
                len(tickers_with_days),
            )
            return await self._yahoo.get_daily_bars(tickers_with_days, auto_adjust, reference=reference)

        missing = {t: d for t, d in tickers_with_days.items() if t not in result or result[t].empty}
        if missing:
            logger.info("Massive returned no data for %d ticker(s); falling back to Yahoo for them", len(missing))
            fallback = await self._yahoo.get_daily_bars(missing, auto_adjust, reference=reference)
            result.update(fallback)
        return result


def get_daily_bar_source() -> DailyBarSource:
    """Massive+Yahoo-fallback when settings.massive_enabled, else Yahoo
    outright -- the MASSIVE_ENABLED=false rollback lever, no code revert
    needed. Only ever called for US-eligible tickers (see route_by_source)
    -- non-US tickers always go straight to a plain YahooDailySource,
    regardless of this flag."""
    return MassiveWithYahooFallback() if settings.massive_enabled else YahooDailySource()
