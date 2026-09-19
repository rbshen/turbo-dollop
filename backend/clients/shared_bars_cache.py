"""Shared, multi-interval Yahoo Finance bars cache -- one table
(core/models.py::SharedBarsCache) serving every consumer of a given
(ticker, interval) combination, replacing four independent fetch paths
that were confirmed (2026-09-18 investigation, see CLAUDE.md) to overlap:

  - interval="1d": Liquidity Zones (1yr Daily + 4yr Weekly, resampled
    locally from Daily -- see analysis/trend_structure/weinstein.py::
    resample_to_weekly) and Trend/Weinstein Stage (2yr).
  - interval="60m": Warren (2yr, the actual fetched granularity -- both
    Warren's and BB+RSI's own "2h" candles are built from these bars by
    resampling downstream, see analysis/entry_signal/resample.py::
    build_2h_session_candles; yfinance has no native "2h" interval) and
    BB+RSI (60d).

Two properties make this a genuine shared cache rather than four
independent ones with a common table:

1. **Growth to the maximum window ever requested**, not a fixed period per
   consumer. A request is served from cache only if the cache's own
   EARLIEST bar already reaches back far enough for that request's
   `lookback_days` -- otherwise a live fetch is triggered for
   `max(lookback_days requested, days of history already cached)`, so a
   wider consumer's own past fetch is never narrowed by a narrower one's
   read, and a narrower consumer's own fetch (when it's the one that ends
   up stale first) preserves whatever wider window a previous fetch
   established. In steady state this means, for any given ticker+interval,
   whichever of the two consumers happens to run first on a given night
   does the one live fetch; the other reads it back for free -- regardless
   of which one that happens to be. No cron-ordering assumption is baked
   in anywhere in this module.
2. **A close-aware freshness check, not a flat TTL.** This is the exact
   mechanism whose absence caused the whole staleness-bug chain in
   CLAUDE.md's Liquidity Zone/Chart tab sections -- a flat "fetched within
   the last N hours" check can't tell a row that's missing today's session
   from one that genuinely doesn't need refreshing yet. A row here is
   trusted only if its own LAST bar matches the most recently completed
   session for that row's interval (see _most_recent_completed_trading_date
   for daily/weekly, _most_recent_completed_intraday_bar_start for 60m) --
   otherwise a live refetch is forced regardless of when the row was last
   written.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.yahoo_client import yahoo_client
from core.db import engine
from core.models import SharedBarsCache

logger = logging.getLogger(__name__)

DAILY_INTERVAL = "1d"
INTRADAY_INTERVAL = "60m"

_EASTERN = ZoneInfo("America/New_York")
_MARKET_OPEN_ET = time(9, 30)
_MARKET_CLOSE_HOUR_ET = 16  # 4:00pm ET, ignored on minute precision, matching
# _most_recent_completed_trading_date's own established convention.

# Yahoo's own raw 60-minute bars are labeled by their START time and run
# 09:30/10:30/.../15:30 each trading day -- 7 bars, the LAST one only 30
# minutes (15:30-16:00, since the session itself closes at 16:00) --
# confirmed empirically against real yfinance output before writing this.
_INTRADAY_BAR_START_MINUTES = [0, 60, 120, 180, 240, 300, 360]
_INTRADAY_BAR_END_MINUTES = [60, 120, 180, 240, 300, 360, 390]

# yfinance's period enum, in ascending order, paired with the calendar-day
# span each value covers -- used to snap a requested lookback_days up to
# the nearest covering value, same "over-fetch a little rather than fetch
# at exact precision" convention already used throughout this codebase
# (see data/chart_data.py's own RANGE_CONFIG comment). Intraday (60m) bars
# have no "5y"/"10y"/"max" tier at all -- Yahoo's real 60m-interval history
# limit is ~730 calendar days (confirmed in the BB+RSI historical-backfill
# investigation), so requesting further back than that would silently
# return less than asked for regardless of the period string used.
_DAILY_PERIOD_STEPS: list[tuple[str, int]] = [
    ("1mo", 30), ("3mo", 90), ("6mo", 180), ("1y", 365), ("2y", 730), ("5y", 1825), ("10y", 3650),
]
_INTRADAY_PERIOD_STEPS: list[tuple[str, int]] = [
    ("1mo", 30), ("3mo", 90), ("6mo", 180), ("1y", 365), ("2y", 730),
]


def _period_steps(interval: str) -> list[tuple[str, int]]:
    if interval == DAILY_INTERVAL:
        return _DAILY_PERIOD_STEPS
    if interval == INTRADAY_INTERVAL:
        return _INTRADAY_PERIOD_STEPS
    raise ValueError(f"unsupported interval {interval!r}")


def _period_for(interval: str, lookback_days: int) -> str:
    for period, days in _period_steps(interval):
        if days >= lookback_days:
            return period
    return _period_steps(interval)[-1][0]  # clamp to the widest available tier


def _most_recent_completed_trading_date(reference: datetime | None = None) -> date:
    """The most recent US/Eastern calendar date whose regular trading
    session has already closed, as of `reference` (default: now).
    Weekend-aware, deliberately NOT holiday-aware -- ported verbatim from
    the now-deleted clients/daily_price_sources.py, which this module
    supersedes; that module's regression cases for this function were
    ported into tests/test_shared_bars_cache.py."""
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


def _most_recent_completed_intraday_bar_start(reference: datetime | None = None) -> datetime:
    """The start-timestamp (naive, US/Eastern -- matching this module's own
    storage convention, see SharedBarsCache's own docstring) of the most
    recently completed 60-minute intraday bar as of `reference` (default:
    now). Mirrors _most_recent_completed_trading_date's own weekday-aware,
    not-holiday-aware convention, generalized to bar-of-day granularity.

    Before today's first bar has fully elapsed (before 10:30 ET on a
    trading day, any time on a non-trading day, or before the session even
    opens) this falls back to the PRIOR trading day's own last (15:30)
    bar -- there is no partial/in-progress bar to report as "complete" yet
    today."""
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    eastern_now = ref.astimezone(_EASTERN)

    completed_offset_minutes: int | None = None
    if eastern_now.weekday() < 5:  # a weekday -- non-holiday-aware, see docstring
        open_dt = datetime.combine(eastern_now.date(), _MARKET_OPEN_ET, tzinfo=_EASTERN)
        if eastern_now >= open_dt:
            minutes_since_open = (eastern_now - open_dt).total_seconds() / 60
            for start, end in zip(_INTRADAY_BAR_START_MINUTES, _INTRADAY_BAR_END_MINUTES):
                if minutes_since_open >= end:
                    completed_offset_minutes = start

    if completed_offset_minutes is None:
        session_date = _most_recent_completed_trading_date(reference)
        completed_offset_minutes = _INTRADAY_BAR_START_MINUTES[-1]
    else:
        session_date = eastern_now.date()

    bar_start = datetime.combine(session_date, _MARKET_OPEN_ET, tzinfo=_EASTERN) + timedelta(minutes=completed_offset_minutes)
    return bar_start.replace(tzinfo=None)


def _is_stale(last_bar_time: datetime | None, interval: str, reference: datetime | None = None) -> bool:
    """True if `last_bar_time` (the cache's own most recent bar for this
    ticker+interval, or None for no cache at all) doesn't yet reflect the
    most recently completed session/bar as of `reference` -- the
    close-aware check this whole module exists to provide instead of a
    flat TTL."""
    if last_bar_time is None:
        return True
    if interval == DAILY_INTERVAL:
        return last_bar_time.date() < _most_recent_completed_trading_date(reference)
    if interval == INTRADAY_INTERVAL:
        return last_bar_time < _most_recent_completed_intraday_bar_start(reference)
    raise ValueError(f"unsupported interval {interval!r}")


def _load_cached_rows(session: Session, ticker: str, interval: str) -> list[SharedBarsCache]:
    return list(
        session.exec(
            select(SharedBarsCache)
            .where(SharedBarsCache.ticker == ticker, SharedBarsCache.interval == interval)
            .order_by(SharedBarsCache.bar_time)
        ).all()
    )


def _write_rows(session: Session, ticker: str, interval: str, df: pd.DataFrame, fetched_at: datetime) -> None:
    for row_time, row in df.iterrows():
        bar_time = row_time.to_pydatetime()
        if bar_time.tzinfo is not None:
            # Re-express in Eastern wall-clock time before dropping tzinfo --
            # yfinance's intraday index is already America/New_York, so this
            # is a no-op in practice, but guards against a future caller
            # whose raw fetch came back in a different tz.
            bar_time = bar_time.astimezone(_EASTERN).replace(tzinfo=None)
        open_ = float(row["Open"])
        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])
        volume = int(row["Volume"]) if not pd.isna(row["Volume"]) else 0
        stmt = sqlite_insert(SharedBarsCache).values(
            ticker=ticker,
            interval=interval,
            bar_time=bar_time,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            fetched_at=fetched_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "interval", "bar_time"],
            set_={"open": open_, "high": high, "low": low, "close": close, "volume": volume, "fetched_at": fetched_at},
        )
        session.execute(stmt)
    session.commit()


def _rows_to_frame(rows: list[SharedBarsCache], interval: str) -> pd.DataFrame:
    """Lowercase-column OHLCV DataFrame, indexed by bar_time -- tz-localized
    back to America/New_York for interval="60m" (analysis/entry_signal/
    resample.py::build_2h_session_candles requires a tz-aware index), left
    naive for interval="1d" (every daily-bar consumer -- data/
    trend_analysis_data.py, analysis/liquidity_zones/ -- already expects a
    naive DatetimeIndex, matching YahooPriceCache's own long-standing
    shape)."""
    data = {
        "open": [r.open for r in rows],
        "high": [r.high for r in rows],
        "low": [r.low for r in rows],
        "close": [r.close for r in rows],
        "volume": [r.volume for r in rows],
    }
    index = pd.DatetimeIndex([r.bar_time for r in rows])
    if interval == INTRADAY_INTERVAL:
        index = index.tz_localize(_EASTERN)
    return pd.DataFrame(data, index=index)


def _eastern_today(reference: datetime | None = None) -> date:
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return ref.astimezone(_EASTERN).date()


async def get_or_fetch_bars_batch(
    tickers: list[str],
    interval: str,
    lookback_days: int,
    auto_adjust: bool = False,
    force: bool = False,
    reference: datetime | None = None,
) -> dict[str, pd.DataFrame]:
    """Batch, cache-first read of raw OHLCV bars for `interval`
    ("1d"/"60m"), growing the cache to whatever the widest requester has
    ever needed and refetching whenever a row's own last bar no longer
    reflects the most recently completed session/bar (see module
    docstring for both mechanisms in full). Returns each ticker's bars
    trimmed to its OWN requested `lookback_days` window, even though the
    cache itself may hold more -- "each consumer slices what it needs" per
    the design this implements.

    force=True always live-fetches every requested ticker regardless of
    freshness or coverage -- kept for parity with the equivalent escape
    hatch the (since removed) yahoo_cache batch function had, for any
    future caller that genuinely needs a guaranteed-live read.
    None of the four consumers wired into this module today need it: the
    growth+freshness design above is already self-correcting regardless of
    which of two overlapping consumers happens to run first on a given
    night, which is exactly the property that made the old per-feature
    force=True (clients/daily_price_sources.py, since deleted) necessary in
    the first place.

    reference overrides "now" (default: datetime.now(timezone.utc)) -- a
    plain testability seam, matching the same parameter every other
    "as-of" function in this module already takes, rather than needing to
    monkeypatch this module's own `datetime` import."""
    if not tickers:
        return {}

    now = reference or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = _eastern_today(now)
    # "lookback_days=N" means N calendar days INCLUDING today -- e.g.
    # lookback_days=1 is satisfied by a single bar dated today itself, not
    # one dated yesterday. Used identically below for both the
    # insufficient-coverage check and the final trim, so a ticker that's
    # freshly fetched is never immediately re-flagged as insufficient by a
    # stricter definition than the one that decided it was wide enough.
    needed_start = today - timedelta(days=max(lookback_days - 1, 0))

    with Session(engine) as session:
        cached_by_ticker = {t: _load_cached_rows(session, t, interval) for t in tickers}

    to_fetch: dict[str, int] = {}
    for t in tickers:
        rows = cached_by_ticker[t]
        existing_width_days = (today - rows[0].bar_time.date()).days + 1 if rows else 0
        if force:
            to_fetch[t] = max(lookback_days, existing_width_days)
            continue
        if not rows:
            to_fetch[t] = lookback_days
            continue
        stale = _is_stale(rows[-1].bar_time, interval, now)
        insufficient = rows[0].bar_time.date() > needed_start
        if stale or insufficient:
            to_fetch[t] = max(lookback_days, existing_width_days)

    if to_fetch:
        # yfinance's multi-ticker download takes ONE period per call, so
        # tickers are grouped by the period their own need snaps to -- one
        # call per distinct period (in practice at most two or three), not
        # one call per ticker and not one call at the widest period for
        # everyone. The latter would make a full-universe Trend run
        # re-download ~570 tickers at 5y just because the ~100 that are
        # also Liquidity Zone tickers happen to be that wide.
        by_period: dict[str, list[str]] = {}
        for ticker, days in to_fetch.items():
            by_period.setdefault(_period_for(interval, days), []).append(ticker)
        fetched_at = datetime.now()
        for period, group in by_period.items():
            fetched = await yahoo_client.get_history(group, period=period, interval=interval, auto_adjust=auto_adjust)
            with Session(engine) as session:
                for ticker, df in fetched.items():
                    if df is not None and not df.empty:
                        _write_rows(session, ticker, interval, df, fetched_at)

    with Session(engine) as session:
        rows_by_ticker = {t: _load_cached_rows(session, t, interval) for t in tickers}

    result: dict[str, pd.DataFrame] = {}
    for t in tickers:
        rows = rows_by_ticker[t]
        if not rows:
            continue
        frame = _rows_to_frame(rows, interval)
        frame = frame[frame.index.date >= needed_start]
        if not frame.empty:
            result[t] = frame
    return result


async def get_or_fetch_bars(
    ticker: str,
    interval: str,
    lookback_days: int,
    auto_adjust: bool = False,
    force: bool = False,
    reference: datetime | None = None,
) -> pd.DataFrame:
    """Single-ticker convenience wrapper over get_or_fetch_bars_batch --
    used by on-demand (non-nightly-batch) callers, e.g. the standalone
    Trend Analysis API endpoint. Returns an empty DataFrame (never
    None/raised) when there's no data at all, matching this codebase's
    established per-ticker-tolerant convention."""
    result = await get_or_fetch_bars_batch(
        [ticker], interval, lookback_days, auto_adjust=auto_adjust, force=force, reference=reference
    )
    return result.get(ticker, pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))
