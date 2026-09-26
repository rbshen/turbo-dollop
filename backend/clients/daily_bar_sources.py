"""Dual data-source adapter for DAILY ("1d" only) OHLCV bars, feeding
clients/shared_bars_cache.py's "1d" fetch step. Mirrors
clients/technical_sources.py's IntradayBarSource Protocol shape -- same
idea, applied here to the daily-bar fetch instead of the intraday one.
The 60m interval (Warren/BB+RSI) is served by FMPIntradaySource /
FMPIntradayWithFallback at the bottom of this module (P4, 2026-09-26): FMP
`/historical-chart/1hour` for US-listed tickers, Yahoo as the per-ticker /
group-off fallback and for non-US tickers.

FMP (`/historical-price-eod/full`, data group `daily_prices`) is the primary
daily-bar source for every US-LISTED ticker (P2, 2026-09-24; US = listing
exchange per the cached FMP profile, see core/tickers.py::is_us_listed --
not company domicile). Per ticker the chain is FMP -> Yahoo (FMPWithFallback): an FMP
error or empty answer for a ticker falls through to Yahoo Finance. Massive/Polygon was
removed in Phase 6a (2026-09-26). Non-US support (the P3 `daily_prices_intl` group and its
phantom-bar filter) was removed in the Phase 6a follow-up: non-US listings get no nightly
daily bars (route_by_source drops them). The daily_prices toggle OFF (or master
switch off) does NOT mean cache-only during P2-P5: FMP is skipped and Yahoo serves
(removed in P6b). Auto-fallback, never a hard job failure -- paired with
clients/shared_bars_cache.py's stale_ticker_count guard so a still-stale ticker after
every source tried is visible in the nightly job's own cron_heartbeat message, not silent.

BASIS: FMP `full` is split- AND spin-off-adjusted (not dividend-adjusted).
Yahoo is split-only, so ~30 tickers' pre-spin-off history differs
from split-only sources (see CLAUDE.md "Daily prices: FMP").
"""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Awaitable, Callable, Protocol

import httpx
import pandas as pd
from sqlalchemy import func, or_
from sqlmodel import Session, select

from clients.fmp_client import FMPGroupDisabledError, fmp_client
from clients.yahoo_client import yahoo_client
from core.data_groups import effective_state, get_snapshot
from core.db import engine
from core.models import FundamentalsCache, SharedBarsCache
from core.tickers import is_us_listed

logger = logging.getLogger(__name__)

DAILY_INTERVAL = "1d"

__all__ = [
    "DAILY_INTERVAL",
    "DailyBarSource",
    "FMPDailySource",
    "FMPWithFallback",
    "FMPIntradaySource",
    "FMPIntradayWithFallback",
    "non_fmp_intraday_tickers",
    "find_short_sessions",
    "fmp_intraday_rows_to_frame",
    "FallbackTickers",
    "describe_fallback",
    "YahooDailySource",
    "get_daily_bar_source",
    "route_by_source",
]


class FallbackTickers(list):
    """Out-parameter for DailyBarSource.get_daily_bars' `fallback_tickers`:
    every ticker in this call NOT served by the primary provider (FMP while
    the daily_prices group is live -- so the whole batch when it is off), with
    `.yahoo` the subset that ended up on Yahoo (every fallback ticker since
    Massive's removal, kept so callers' summaries are unchanged). A plain list to every existing caller (`len()`, `.extend()`);
    `describe()` is the one-line breakdown the nightly jobs put in their
    cron_heartbeat message."""

    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.yahoo: list[str] = []

    def describe(self) -> str:
        return describe_fallback(len(self), len(self.yahoo))


def describe_fallback(count: int, yahoo: int) -> str:
    """The heartbeat phrase for a run's FMP fallbacks: `count` tickers not
    served by FMP, `yahoo` of them ended on Yahoo (the only fallback)."""
    return f"{count} fell back from FMP to Yahoo"


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
        ticker THIS call did not get from FMP (Yahoo served it -- see
        FMPWithFallback below) -- an out-parameter rather than a
        return-shape change, so get_or_fetch_bars_batch's existing
        `dict[str, pd.DataFrame]` return type (many callers) doesn't need
        to change to thread this through. Only FMPWithFallback
        ever populates it; YahooDailySource accepts and ignores it.

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
    (so sector ETFs and ^GSPC are US). Callers fetch only the US half; non-US
    tickers are no longer supported by the bar jobs."""
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
    unchanged in behavior -- the fallback for every ticker FMP could not serve."""

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
            # DailyBarSource's own docstring).
            result.update({t: df.rename(columns=str.lower) for t, df in fetched.items()})
        return result


def _existing_span(tickers: list[str]) -> dict[str, tuple[date, date]]:
    """(first bar date, last bar date) per ticker already in SharedBarsCache for
    interval="1d" -- one grouped query (not clients/shared_bars_cache.py::_cache_span,
    which would be a circular import)."""
    if not tickers:
        return {}
    with Session(engine) as session:
        stmt = (
            select(SharedBarsCache.ticker, func.min(SharedBarsCache.bar_time), func.max(SharedBarsCache.bar_time))
            .where(SharedBarsCache.interval == DAILY_INTERVAL, SharedBarsCache.ticker.in_(tickers))
            .group_by(SharedBarsCache.ticker)
        )
        return {t: (first.date(), last.date()) for t, first, last in session.exec(stmt).all()}


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
# A cache whose first bar starts within this many days of the requested window's
# start still counts as covering it (weekends/holidays at the boundary; a row
# fetched at "5y" starts a few days short of 1825 days, and the boundary moves a
# day every night) -- otherwise every ticker would be refetched in full nightly.
FMP_COVERAGE_SLACK_DAYS = 10
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
    """FMP-backed DailyBarSource. `group` names the data group whose toggle gates
    it (`daily_prices` by default). Per ticker:

    - full window (`from = today - days`): never cached, cached history
      narrower than requested, or `full_refresh` (the weekly resync). The
      result is reported in `replace_tickers` so the cache REPLACES that
      ticker's rows.
    - otherwise incremental, OVERLAPPING: `from = last cached bar - 7d`. The
      overlapping closes (all but the last cached bar, which is always
      overwritten) must match the cache within 0.5%; if not, the provider has
      restated history (split, spin-off, symbol reuse) and the ticker is
      refetched over its full window and replaced.

    Returns {} outright while its group is not live (off, master
    off, above plan, restricted) -- FMPWithFallback then serves the whole
    batch from its fallback (Yahoo). An empty 200 (delisted symbol) or an HTTP error
    for a ticker just leaves it out of the result (its fallback decides);
    error accounting toward the group's Failing chip is FMPClient.get's job.
    Requests are paced to FMP_RATE_FRACTION of the plan's documented rate."""

    def __init__(self, client=fmp_client, group: str = "daily_prices") -> None:
        self._client = client
        self._group = group

    async def get_daily_bars(
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: date | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        if not tickers_with_days or not effective_state(self._group)[0]:
            return {}
        today = reference or date.today()
        span = _existing_span(list(tickers_with_days))
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
                    rows = await self._client.get_historical_price_eod(
                        ticker, start.isoformat(), today.isoformat(), group=self._group
                    )
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
            needed_start = today - timedelta(days=max(days - 1, 0) - FMP_COVERAGE_SLACK_DAYS)
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
    """FMP first, then Yahoo, per ticker (see the
    module docstring). Every ticker FMP did not deliver -- an empty/erroring
    answer, or the whole batch while the daily_prices group is off -- goes to
    the fallback and is recorded in `fallback_tickers` (with the Yahoo subset
    in its `.yahoo`, when the caller passed a FallbackTickers) so the job's
    heartbeat can say "N fell back from FMP to Yahoo"."""

    def __init__(self, fmp: DailyBarSource | None = None, fallback: DailyBarSource | None = None) -> None:
        self._fmp = fmp or FMPDailySource()
        self._fallback = fallback or YahooDailySource()

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
        logger.info("FMP served %d/%d ticker(s); %d fall back to Yahoo", len(result), len(tickers_with_days), len(missing))
        fallback = await self._fallback.get_daily_bars(missing, auto_adjust, reference=reference)
        if fallback_tickers is not None:
            fallback_tickers.extend(missing)
            if isinstance(fallback_tickers, FallbackTickers):
                fallback_tickers.yahoo.extend(missing)  # Yahoo is the only fallback: everything missing is Yahoo's
        result.update(fallback)
        return result


def get_daily_bar_source() -> DailyBarSource:
    """FMP first (daily_prices group), then Yahoo."""
    return FMPWithFallback()


# ---------------------------------------------------------------------------
# P4: intraday (60m) bars -- Warren and BB+RSI
# ---------------------------------------------------------------------------
# FMP `/historical-chart/1hour` (data group `intraday_bars`): regular-trading-hours
# bars only, labelled by bar START (09:30..15:30 -- the same labelling the Yahoo
# rows carry), timestamps naive strings in ET, newest first. Prices are split-
# adjusted and NOT dividend-adjusted (checked against IBKR/FAST splits and VZ/O
# dividends, 2026-09-26). `extended=true` is never requested (clock-anchored bars).

INTRADAY_MAX_PAGES = 40  # ~9 pages cover 730 days; the cap only stops a runaway loop
INTRADAY_OVERLAP_DAYS = 3
INTRADAY_PAGE_DONE_DAYS = 6  # a page whose oldest bar is within this of `from` reached it (weekend/holiday slack)
INTRADAY_MIN_FULL_BARS = 20
_RTH_FIRST, _RTH_LAST = dtime(9, 30), dtime(15, 30)
SESSION_BARS, HALF_DAY_BARS = 7, 4


def _is_half_day(d: date) -> bool:
    """NYSE early close (13:00): the day after Thanksgiving, Dec 24 and Jul 3 when they are
    weekdays. (Full holidays have no bars, so they never reach the check.)"""
    if d.weekday() >= 5:
        return False
    if (d.month, d.day) in ((12, 24), (7, 3)):
        return True
    if d.month == 11 and d.weekday() == 4:  # a Friday in Nov: the day after the 4th Thursday
        return 23 <= d.day <= 29
    return False


def find_short_sessions(frame: pd.DataFrame, completed_bar_start: datetime | None = None) -> list[tuple[date, int, int]]:
    """Sessions in a naive-ET hourly frame with fewer bars than expected (7; 4 on half-days) as
    (date, bars, expected). The session still in progress (its date is `completed_bar_start`'s and
    that bar isn't the session's last) is skipped -- it is legitimately short."""
    if frame.empty:
        return []
    out: list[tuple[date, int, int]] = []
    for d, count in pd.Series(1, index=frame.index).groupby(frame.index.date).sum().items():
        expected = HALF_DAY_BARS if _is_half_day(d) else SESSION_BARS
        if count >= expected:
            continue
        if completed_bar_start is not None and d == completed_bar_start.date():
            last_start = dtime(9 + expected - 1, 30)
            if completed_bar_start.time() < last_start:
                continue
        out.append((d, int(count), expected))
    return out


def fmp_intraday_rows_to_frame(rows, completed_bar_start: datetime | None = None) -> pd.DataFrame:
    """FMP /historical-chart/1hour rows (newest first, naive-ET `date` strings) -> the module's
    lowercase-OHLCV contract, a naive-ET ascending DatetimeIndex. Keeps only weekday RTH bars
    (09:30..15:30 starts) and drops any bar after `completed_bar_start` (a live/partial one)."""
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame(columns=_OHLCV)
    df = pd.DataFrame(rows)
    if "date" not in df or "close" not in df:
        return pd.DataFrame(columns=_OHLCV)
    for col in _OHLCV:
        if col not in df:
            df[col] = 0 if col == "volume" else df["close"]
    df = df.assign(date=pd.to_datetime(df["date"])).dropna(subset=["close"])
    df = df.drop_duplicates(subset="date").set_index("date").sort_index()
    df.index = pd.DatetimeIndex(df.index)
    df["volume"] = df["volume"].fillna(0)
    df = df[_OHLCV]
    tod = df.index.time
    keep = (df.index.dayofweek < 5) & pd.Series([_RTH_FIRST <= t <= _RTH_LAST for t in tod], index=df.index).to_numpy()
    df = df[keep]
    if completed_bar_start is not None:
        df = df[df.index <= pd.Timestamp(completed_bar_start)]
    return df


def non_fmp_intraday_tickers(session: Session, tickers: list[str]) -> set[str]:
    """Tickers (of `tickers`) with at least one cached "60m" row NOT tagged source="fmp" -- a
    Yahoo-era row (NULL, pre-P4) or a Yahoo fallback write. Tickers with no cached row at all are
    not in the result. Two callers: FMPIntradaySource (such a ticker is fully replaced, never
    layered) and the cache's fetch selection (such a ticker is fetched even if fresh and wide)."""
    if not tickers:
        return set()
    return set(
        session.exec(
            select(SharedBarsCache.ticker)
            .where(
                SharedBarsCache.interval == "60m", SharedBarsCache.ticker.in_(tickers),
                or_(SharedBarsCache.source.is_(None), SharedBarsCache.source != "fmp"),
            )
            .distinct()
        ).all()
    )


class FMPIntradaySource:
    """FMP-backed 60m source (group `intraday_bars`). Per ticker:

    - FULL fetch (paginated newest-first by moving `to` to the oldest bar returned): never
      cached, cached history narrower than requested, `full_refresh`, or the cached rows are
      not ALL FMP-sourced (SharedBarsCache.source != "fmp" -- Yahoo-era rows must be replaced,
      never layered under FMP bars). Starts at the earlier of the requested window and the
      cached first bar, so nothing already held is lost. Reported in `replace_tickers`.
    - otherwise INCREMENTAL, overlapping: `from = last cached bar - 3d`; the overlapping closes
      (other than the last cached bar) must match the cache within 0.5%, else FMP restated
      history and the ticker is refetched in full and replaced.

    Returns {} while the group is not live -- FMPIntradayWithFallback then serves the whole batch
    from Yahoo (never cache-only). A ticker with an error / empty / thin answer is simply left
    out. Sessions with fewer bars than expected are logged and kept in `short_sessions`."""

    def __init__(self, client=fmp_client) -> None:
        self._client = client
        self.short_sessions: dict[str, list[tuple[date, int, int]]] = {}

    @staticmethod
    def _cache_state(tickers: list[str]) -> tuple[dict[str, tuple[datetime, datetime]], set[str]]:
        with Session(engine) as session:
            spans = {
                t: (lo, hi)
                for t, lo, hi in session.exec(
                    select(SharedBarsCache.ticker, func.min(SharedBarsCache.bar_time), func.max(SharedBarsCache.bar_time))
                    .where(SharedBarsCache.interval == "60m", SharedBarsCache.ticker.in_(tickers))
                    .group_by(SharedBarsCache.ticker)
                ).all()
            }
            non_fmp = non_fmp_intraday_tickers(session, tickers)
        return spans, non_fmp

    async def get_intraday_bars(
        self,
        tickers_with_days: dict[str, int],
        reference: datetime | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
    ) -> dict[str, pd.DataFrame]:
        if not tickers_with_days or not effective_state("intraday_bars")[0]:
            return {}
        # Lazy import: clients.shared_bars_cache imports this module.
        from clients.shared_bars_cache import _eastern_today, _most_recent_completed_intraday_bar_start

        today = _eastern_today(reference)
        completed = _most_recent_completed_intraday_bar_start(reference)
        spans, non_fmp = self._cache_state(list(tickers_with_days))
        plan_rate = FMP_PLAN_REQUESTS_PER_MIN.get(get_snapshot().fmp_plan, 300)
        pacer = _Pacer(60.0 / (plan_rate * FMP_RATE_FRACTION))
        sem = asyncio.Semaphore(FMP_CONCURRENCY)
        stop = False
        result: dict[str, pd.DataFrame] = {}
        replaced: list[str] = []

        async def fetch(ticker: str, start: date) -> pd.DataFrame | None:
            nonlocal stop
            rows_all: list = []
            to, oldest = today, None
            for _ in range(INTRADAY_MAX_PAGES):
                if stop:
                    return None
                async with sem:
                    await pacer.wait()
                    try:
                        rows = await self._client.get_historical_chart_1hour(ticker, start.isoformat(), to.isoformat())
                    except FMPGroupDisabledError:
                        stop = True  # group went off mid-run: everything left falls through
                        return None
                    except (httpx.HTTPError, ValueError):
                        logger.warning("FMP intraday fetch failed for %s; falling back", ticker)
                        return None  # never a partial history
                if not isinstance(rows, list) or not rows:
                    break
                rows_all.extend(rows)
                try:
                    page_oldest = min(pd.to_datetime(r["date"]) for r in rows)
                except (KeyError, ValueError, TypeError):
                    return None
                if oldest is not None and page_oldest >= oldest:
                    break  # no progress
                oldest = page_oldest
                if (page_oldest.date() - start).days <= INTRADAY_PAGE_DONE_DAYS:
                    break
                to = page_oldest.date()
            else:
                logger.warning("FMP intraday paging for %s hit the %d-page cap", ticker, INTRADAY_MAX_PAGES)
            frame = fmp_intraday_rows_to_frame(rows_all, completed)
            return frame if not frame.empty else None

        def restated(ticker: str, frame: pd.DataFrame, last_bar: datetime) -> bool:
            start = last_bar - timedelta(days=INTRADAY_OVERLAP_DAYS)
            with Session(engine) as session:
                cached = {
                    pd.Timestamp(bt): close
                    for bt, close in session.exec(
                        select(SharedBarsCache.bar_time, SharedBarsCache.close).where(
                            SharedBarsCache.interval == "60m", SharedBarsCache.ticker == ticker,
                            SharedBarsCache.bar_time >= start,
                        )
                    ).all()
                }
            last_ts = pd.Timestamp(last_bar)
            for ts, close in frame["close"].items():
                old = cached.get(ts)
                if old is None or ts >= last_ts or not old:
                    continue
                if abs(float(close) / float(old) - 1.0) > FMP_OVERLAP_TOLERANCE:
                    return True
            return False

        async def one(ticker: str, days: int) -> None:
            first_bar, last_bar = spans.get(ticker, (None, None))
            window_start = today - timedelta(days=days)
            needed_start = today - timedelta(days=max(days - 1, 0) - FMP_COVERAGE_SLACK_DAYS)
            full = (
                full_refresh or first_bar is None or ticker in non_fmp or first_bar.date() > needed_start
            )
            if full:
                start = min(window_start, first_bar.date()) if first_bar is not None else window_start
                frame = await fetch(ticker, start)
            else:
                frame = await fetch(ticker, last_bar.date() - timedelta(days=INTRADAY_OVERLAP_DAYS))
                if frame is not None and restated(ticker, frame, last_bar):
                    logger.info("FMP restated %s's overlapping intraday history; refetching in full", ticker)
                    frame = await fetch(ticker, min(window_start, first_bar.date()))
                    full = True
            if frame is None:
                return
            if full and len(frame) < INTRADAY_MIN_FULL_BARS:
                logger.warning("FMP full intraday history for %s has only %d bars; falling back", ticker, len(frame))
                return
            short = find_short_sessions(frame, completed)
            if short:
                self.short_sessions[ticker] = short
                logger.warning(
                    "FMP intraday %s: %d session(s) with fewer bars than expected (e.g. %s)",
                    ticker, len(short), ", ".join(f"{d} {n}/{e}" for d, n, e in short[:3]),
                )
            result[ticker] = frame
            if full:
                replaced.append(ticker)

        await asyncio.gather(*(one(t, d) for t, d in tickers_with_days.items()))
        if replace_tickers is not None:
            replace_tickers.extend(replaced)
        return result


IntradayFallback = Callable[[dict[str, int], bool], Awaitable[dict[str, pd.DataFrame]]]


class FMPIntradayWithFallback:
    """FMP first, then `fallback` (Yahoo, injected by clients/shared_bars_cache.py, which owns
    the yfinance period logic) for every ticker FMP did not deliver -- per ticker, and the whole
    batch while `intraday_bars` is off. Tickers FMP served are added to `fmp_served` so the
    cache can tag their rows; those that fell back go to `fallback_tickers`."""

    def __init__(self, fallback: IntradayFallback, fmp: FMPIntradaySource | None = None) -> None:
        self._fmp = fmp or FMPIntradaySource()
        self._fallback = fallback

    async def get_intraday_bars(
        self,
        tickers_with_days: dict[str, int],
        auto_adjust: bool,
        reference: datetime | None = None,
        fallback_tickers: list[str] | None = None,
        replace_tickers: list[str] | None = None,
        full_refresh: bool = False,
        fmp_served: set[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        try:
            result = await self._fmp.get_intraday_bars(
                tickers_with_days, reference=reference, replace_tickers=replace_tickers, full_refresh=full_refresh
            )
        except Exception:
            logger.warning("FMP intraday fetch failed entirely for %d ticker(s); falling back", len(tickers_with_days), exc_info=True)
            result = {}
            if replace_tickers is not None:
                replace_tickers.clear()
        if fmp_served is not None:
            fmp_served.update(result)
        missing = {t: d for t, d in tickers_with_days.items() if t not in result or result[t].empty}
        if not missing:
            return result
        logger.info("FMP served %d/%d intraday ticker(s); %d fall back to Yahoo", len(result), len(tickers_with_days), len(missing))
        fallback = await self._fallback(missing, auto_adjust)
        if fallback_tickers is not None:
            fallback_tickers.extend(missing)
            if isinstance(fallback_tickers, FallbackTickers):
                fallback_tickers.yahoo.extend(missing)
        result.update(fallback)
        return result
