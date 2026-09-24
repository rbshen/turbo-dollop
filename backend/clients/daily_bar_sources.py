"""Dual data-source adapter for DAILY ("1d" only) OHLCV bars, feeding
clients/shared_bars_cache.py's "1d" fetch step. Mirrors
clients/technical_sources.py's IntradayBarSource Protocol shape -- same
idea, applied here to the daily-bar fetch instead of the intraday one.
The 60m interval (Warren/BB+RSI) is untouched by this module and stays
exclusively Yahoo -- a separate, later migration phase (see
docs/massive_feasibility_investigation_2026-09-23.md's own "Starter
paid-plan verification" section for why intraday session-anchoring is a
materially different problem).

FMP (`/historical-price-eod/full`, data group `daily_prices`) is the primary
daily-bar source for every US-LISTED ticker (P2, 2026-09-24; US = listing
exchange per the cached FMP profile, see core/tickers.py::is_us_listed --
not company domicile). Per ticker the chain is FMP -> Massive -> Yahoo
(FMPWithFallback): an FMP error or empty answer for a ticker falls through
to Massive/Polygon (clients/massive_client.py), which itself falls back to
Yahoo Finance (MassiveWithYahooFallback, unchanged). Non-US tickers never
touch FMP/Massive here -- they stay on Yahoo exactly as before. The
daily_prices toggle OFF (or master switch off) does NOT mean cache-only
during P2-P5: FMP is skipped and the rest of the chain serves (removed in
P6). Auto-fallback, never a hard job failure -- paired with
clients/shared_bars_cache.py's stale_ticker_count guard so a still-stale
ticker after every source tried is visible in the nightly job's own
cron_heartbeat message, not silent.

BASIS: FMP `full` is split- AND spin-off-adjusted (not dividend-adjusted).
Massive/Yahoo are split-only, so ~30 tickers' pre-spin-off history differs
from split-only sources (see CLAUDE.md "Daily prices: FMP").
"""

import asyncio
import json
import logging
import time
from datetime import date, timedelta
from typing import Protocol

import httpx
import pandas as pd
from sqlalchemy import func
from sqlmodel import Session, select

from clients.fmp_client import FMPGroupDisabledError, fmp_client
from clients.massive_client import massive_client
from clients.yahoo_client import yahoo_client
from core.config import settings
from core.data_groups import effective_state, get_snapshot
from core.db import engine
from core.models import FundamentalsCache, SharedBarsCache
from core.tickers import from_massive_symbol, is_us_listed, to_massive_symbol

logger = logging.getLogger(__name__)

DAILY_INTERVAL = "1d"

# Massive's `adjusted` flag means split-adjusted (see clients/massive_client.py),
# unlike yfinance's auto_adjust (dividend-adjusted). The DailyBarSource
# `auto_adjust` parameter is therefore deliberately NOT forwarded to Massive:
# the required basis is always split-adjusted, non-dividend-adjusted.
MASSIVE_SPLIT_ADJUSTED = True

__all__ = [
    "DAILY_INTERVAL",
    "DailyBarSource",
    "FMPDailySource",
    "FMPWithFallback",
    "FallbackTickers",
    "describe_fallback",
    "YahooDailySource",
    "MassiveDailySource",
    "MassiveWithYahooFallback",
    "get_daily_bar_source",
    "route_by_source",
]


class FallbackTickers(list):
    """Out-parameter for DailyBarSource.get_daily_bars' `fallback_tickers`:
    every ticker in this call NOT served by the primary provider (FMP while
    the daily_prices group is live -- so the whole batch when it is off), with
    `.yahoo` the subset that ended up on Yahoo (the rest were served by
    Massive). A plain list to every existing caller (`len()`, `.extend()`);
    `describe()` is the one-line breakdown the nightly jobs put in their
    cron_heartbeat message."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.yahoo: list[str] = []

    def describe(self) -> str:
        return describe_fallback(len(self), len(self.yahoo))


def describe_fallback(count: int, yahoo: int) -> str:
    """The heartbeat phrase for a run's FMP fallbacks: `count` tickers not
    served by FMP, `yahoo` of them ended on Yahoo, the rest on Massive."""
    return f"{count} fell back from FMP (Massive {max(count - yahoo, 0)}, Yahoo {yahoo})"


class DailyBarSource(Protocol):
    async def get_daily_bars(
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
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
        per-ticker-tolerant convention.

        `fallback_tickers`, when passed a list, gets extended with every
        ticker THIS call served from Yahoo instead of Massive (see
        MassiveWithYahooFallback below) -- an out-parameter rather than a
        return-shape change, so get_or_fetch_bars_batch's existing
        `dict[str, pd.DataFrame]` return type (many callers) doesn't need
        to change to thread this through. Only MassiveWithYahooFallback
        ever populates it; YahooDailySource/MassiveDailySource accept and
        ignore it -- neither is itself a fallback.

        `replace_tickers` (out-parameter, FMPWithFallback only): tickers whose
        returned frame is a COMPLETE fresh history that must REPLACE the cached
        rows (delete-then-insert) rather than be upserted over them -- a full
        FMP refetch after a split/spin-off/symbol-reuse restated the past.
        `full_refresh` (input): FMP path only -- skip the incremental overlap
        check and refetch every ticker's full window (the weekly resync).
        Every other source accepts and ignores both."""
        ...


def _profile_exchanges(tickers: list[str]) -> dict[str, str]:
    """{ticker: listing exchange} from the cached FMP /profile rows
    (FundamentalsCache "profile"/"latest") -- a pure local read, no FMP call.
    A ticker with no cached profile (sector ETFs, ^GSPC, a never-viewed
    symbol) is simply absent."""
    out: dict[str, str] = {}
    if not tickers:
        return out
    with Session(engine) as session:
        for i in range(0, len(tickers), 400):
            chunk = tickers[i : i + 400]
            stmt = select(FundamentalsCache.ticker, FundamentalsCache.raw_json).where(
                FundamentalsCache.statement_type == "profile",
                FundamentalsCache.period == "latest",
                FundamentalsCache.ticker.in_(chunk),
            )
            for ticker, raw in session.exec(stmt).all():
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                row = payload[0] if isinstance(payload, list) and payload else payload
                exchange = row.get("exchange") if isinstance(row, dict) else None
                if exchange:
                    out[ticker] = str(exchange)
    return out


def route_by_source(tickers_with_days: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """Splits a {ticker: days} map into (us_listed, non_us) by LISTING
    EXCHANGE (core/tickers.py::is_us_listed, off the cached FMP profile) --
    not company domicile: an NYSE-listed ADR is US, an HKSE listing is not.
    A ticker with no cached profile falls back to the dot-suffix check
    (so sector ETFs and ^GSPC are US). Non-US tickers are never attempted on
    FMP or Massive here (Massive is US-market-only, confirmed in the
    feasibility investigation §2j; FMP's plan tier for this group covers US
    only)."""
    exchanges = _profile_exchanges(list(tickers_with_days))
    us: dict[str, int] = {}
    non_us: dict[str, int] = {}
    for ticker, days in tickers_with_days.items():
        (us if is_us_listed(ticker, exchanges.get(ticker)) else non_us)[ticker] = days
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
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        if not tickers_with_days:
            return {}
        by_period: dict[str, list[str]] = {}
        for ticker, days in tickers_with_days.items():
            by_period.setdefault(_yahoo_period_for(days), []).append(ticker)
        result: dict[str, pd.DataFrame] = {}
        for period, group in by_period.items():
            fetched = await yahoo_client.get_history(group, period=period, interval=DAILY_INTERVAL, auto_adjust=auto_adjust)
            # yfinance's own native Open/High/Low/Close/Volume casing ->
            # this Protocol's normalized lowercase contract (see
            # DailyBarSource's own docstring) -- MassiveDailySource's
            # underlying clients/massive_client.py already returns
            # lowercase natively, so this is the one source that needs an
            # explicit rename to honor the shared contract.
            result.update({t: df.rename(columns=str.lower) for t, df in fetched.items()})
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
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
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
                to_massive_symbol(ticker), today - timedelta(days=days), today, adjusted=MASSIVE_SPLIT_ADJUSTED
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
                grouped = await self._client.get_grouped_daily(day, adjusted=MASSIVE_SPLIT_ADJUSTED)
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
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        try:
            result = await self._massive.get_daily_bars(tickers_with_days, auto_adjust, reference=reference)
        except Exception:
            logger.warning(
                "Massive daily-bar fetch failed entirely for %d ticker(s); falling back to Yahoo for all of them",
                len(tickers_with_days),
            )
            if fallback_tickers is not None:
                fallback_tickers.extend(tickers_with_days)
            return await self._yahoo.get_daily_bars(tickers_with_days, auto_adjust, reference=reference)

        missing = {t: d for t, d in tickers_with_days.items() if t not in result or result[t].empty}
        if missing:
            logger.info("Massive returned no data for %d ticker(s); falling back to Yahoo for them", len(missing))
            if fallback_tickers is not None:
                fallback_tickers.extend(missing)
            fallback = await self._yahoo.get_daily_bars(missing, auto_adjust, reference=reference)
            result.update(fallback)
        return result


# ---------------------------------------------------------------------------
# FMP (primary for US-listed tickers)
# ---------------------------------------------------------------------------

# Days of already-cached history re-requested each night so the new call
# OVERLAPS what we hold: the last cached bar is always overwritten (it may
# have been written mid-session), and every earlier overlapping close is
# compared to the cache -- a mismatch means the provider restated history
# (split / spin-off / symbol reuse) and that ticker gets a full refetch.
FMP_OVERLAP_DAYS = 7
FMP_OVERLAP_TOLERANCE = 0.005  # 0.5% -- finalised bars agree to ~0.1%; any real restatement is far larger
FMP_MIN_FULL_BARS = 20  # a "full" answer with fewer bars never replaces existing rows
# Fraction of the plan's documented per-minute cap we allow ourselves.
FMP_RATE_FRACTION = 0.5
FMP_PLAN_REQUESTS_PER_MIN = {"Starter": 300, "Premium": 750, "Ultimate": 3000}
FMP_CONCURRENCY = 10
_OHLCV = ["open", "high", "low", "close", "volume"]


def fmp_rows_to_frame(rows) -> pd.DataFrame:
    """FMP /historical-price-eod/full rows (newest first: date, open, high,
    low, close, volume, ...) -> the DailyBarSource contract (lowercase OHLCV,
    naive ascending DatetimeIndex). Rows without a usable close are dropped;
    an unusable/empty payload is an empty frame."""
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=_OHLCV)
    df = pd.DataFrame(rows)
    if "date" not in df or "close" not in df:
        return pd.DataFrame(columns=_OHLCV)
    for col in _OHLCV:
        if col not in df:
            df[col] = 0 if col == "volume" else df["close"]
    df = df.assign(date=pd.to_datetime(df["date"]).dt.normalize()).dropna(subset=["close"])
    df = df.drop_duplicates(subset="date").set_index("date").sort_index()
    df.index = pd.DatetimeIndex(df.index)
    df["volume"] = df["volume"].fillna(0)
    return df[_OHLCV]


def _completed_session() -> date:
    # Lazy import: clients.shared_bars_cache imports this module.
    from clients.shared_bars_cache import _most_recent_completed_trading_date

    return _most_recent_completed_trading_date()


class _Pacer:
    """Spaces request STARTS at least `interval` seconds apart across
    concurrent tasks (the shared FMPClient singleton's own pacing is left
    alone -- other jobs use it)."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


class FMPDailySource:
    """FMP-backed DailyBarSource for US-listed tickers. Per ticker:

    - full window (`from = today - days`): never cached, cached history
      narrower than requested, or `full_refresh` (the weekly resync). The
      result is reported in `replace_tickers` so the cache REPLACES that
      ticker's rows.
    - otherwise incremental, OVERLAPPING: `from = last cached bar - 7d`. The
      overlapping closes (all but the last cached bar, which is always
      overwritten) must match the cache within 0.5%; if not, the provider has
      restated history (split, spin-off, symbol reuse) and the ticker is
      refetched over its full window and replaced.

    Returns {} outright while the daily_prices group is not live (off, master
    off, above plan, restricted) -- FMPWithFallback then serves the whole
    batch from Massive/Yahoo. An empty 200 (delisted symbol) or an HTTP error
    for a ticker just leaves it out of the result (its fallback decides);
    error accounting toward the group's Failing chip is FMPClient.get's job.
    Requests are paced to FMP_RATE_FRACTION of the plan's documented rate."""

    def __init__(self, client=fmp_client) -> None:
        self._client = client

    async def get_daily_bars(
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        if not tickers_with_days or not effective_state("daily_prices")[0]:
            return {}
        today = reference or date.today()
        span = MassiveDailySource._existing_span(list(tickers_with_days))
        plan_rate = FMP_PLAN_REQUESTS_PER_MIN.get(get_snapshot().fmp_plan, 300)
        pacer = _Pacer(60.0 / (plan_rate * FMP_RATE_FRACTION))
        sem = asyncio.Semaphore(FMP_CONCURRENCY)
        stop = False
        result: dict[str, pd.DataFrame] = {}
        replaced: list[str] = []

        async def fetch(ticker: str, start: date) -> pd.DataFrame | None:
            nonlocal stop
            if stop:
                return None
            async with sem:
                await pacer.wait()
                try:
                    rows = await self._client.get_historical_price_eod(ticker, start.isoformat(), today.isoformat())
                except FMPGroupDisabledError:
                    stop = True  # group went off mid-run: everything left falls through
                    return None
                except (httpx.HTTPError, ValueError):
                    logger.warning("FMP daily-bar fetch failed for %s; falling back", ticker)
                    return None
            frame = fmp_rows_to_frame(rows)
            if frame.empty:
                return None
            # A bar dated after the most recent COMPLETED session is a live,
            # partial one (FMP serves it mid-session): never store it as a bar.
            frame = frame[frame.index <= pd.Timestamp(_completed_session())]
            return frame if not frame.empty else None

        async def one(ticker: str, days: int) -> None:
            full_start = today - timedelta(days=days)
            first_bar, last_bar = span.get(ticker, (None, None))
            needed_start = today - timedelta(days=max(days - 1, 0))
            if full_refresh or first_bar is None or first_bar > needed_start:
                frame = await fetch(ticker, full_start)
                full = True
            else:
                frame = await fetch(ticker, last_bar - timedelta(days=FMP_OVERLAP_DAYS))
                full = False
                if frame is not None and self._restated(ticker, frame, last_bar):
                    logger.info("FMP restated %s's overlapping history; refetching its full window", ticker)
                    frame = await fetch(ticker, full_start)
                    full = True
            if frame is None:
                return
            if full and len(frame) < FMP_MIN_FULL_BARS and first_bar is not None:
                logger.warning("FMP full history for %s has only %d bars; keeping cached rows", ticker, len(frame))
                return
            result[ticker] = frame
            if full:
                replaced.append(ticker)

        await asyncio.gather(*(one(t, d) for t, d in tickers_with_days.items()))
        if replace_tickers is not None:
            replace_tickers.extend(replaced)
        return result

    @staticmethod
    def _restated(ticker: str, frame: pd.DataFrame, last_bar: date) -> bool:
        """True if any bar the frame shares with the cache (other than the
        cache's own last bar) differs by more than FMP_OVERLAP_TOLERANCE."""
        start = pd.Timestamp(last_bar) - pd.Timedelta(days=FMP_OVERLAP_DAYS)
        with Session(engine) as session:
            stmt = select(SharedBarsCache.bar_time, SharedBarsCache.close).where(
                SharedBarsCache.interval == DAILY_INTERVAL,
                SharedBarsCache.ticker == ticker,
                SharedBarsCache.bar_time >= start.to_pydatetime(),
            )
            cached = {pd.Timestamp(bt).normalize(): close for bt, close in session.exec(stmt).all()}
        last_ts = pd.Timestamp(last_bar)
        for ts, close in frame["close"].items():
            old = cached.get(ts)
            if old is None or ts >= last_ts or not old:
                continue
            if abs(float(close) / float(old) - 1.0) > FMP_OVERLAP_TOLERANCE:
                return True
        return False


class FMPWithFallback:
    """FMP first, then the existing Massive->Yahoo chain, per ticker (see the
    module docstring). Every ticker FMP did not deliver -- an empty/erroring
    answer, or the whole batch while the daily_prices group is off -- goes to
    the fallback and is recorded in `fallback_tickers` (with the Yahoo subset
    in its `.yahoo`, when the caller passed a FallbackTickers) so the job's
    heartbeat can say "N fell back from FMP (Massive M, Yahoo Y)"."""

    def __init__(self, fmp: DailyBarSource | None = None, fallback: DailyBarSource | None = None) -> None:
        self._fmp = fmp or FMPDailySource()
        self._massive_enabled = settings.massive_enabled if fallback is None else True
        self._fallback = fallback or (MassiveWithYahooFallback() if settings.massive_enabled else YahooDailySource())

    async def get_daily_bars(
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        try:
            result = await self._fmp.get_daily_bars(
                tickers_with_days, auto_adjust, reference=reference, replace_tickers=replace_tickers,
                full_refresh=full_refresh,
            )
        except Exception:
            logger.warning("FMP daily-bar fetch failed entirely for %d ticker(s); falling back", len(tickers_with_days), exc_info=True)
            result = {}
        missing = {t: d for t, d in tickers_with_days.items() if t not in result or result[t].empty}
        if not missing:
            return result
        logger.info("FMP served %d/%d ticker(s); %d fall back to Massive/Yahoo", len(result), len(tickers_with_days), len(missing))
        yahoo: list[str] = []
        fallback = await self._fallback.get_daily_bars(missing, auto_adjust, reference=reference, fallback_tickers=yahoo)
        if not self._massive_enabled:
            yahoo = list(missing)  # Yahoo-only fallback: everything missing is Yahoo's
        if fallback_tickers is not None:
            fallback_tickers.extend(missing)
            if isinstance(fallback_tickers, FallbackTickers):
                fallback_tickers.yahoo.extend(yahoo)
        result.update(fallback)
        return result


def get_daily_bar_source() -> DailyBarSource:
    """FMP first (daily_prices group, US-listed only -- see route_by_source),
    then Massive->Yahoo when settings.massive_enabled, else Yahoo (the
    MASSIVE_ENABLED=false lever now only shapes the fallback chain). Only
    ever called for US-listed tickers -- non-US tickers always go straight
    to a plain YahooDailySource, regardless of any flag."""
    return FMPWithFallback()
