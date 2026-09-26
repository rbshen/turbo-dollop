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
from sqlalchemy import delete, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.daily_bar_sources import (
    FMPIntradayWithFallback,
    YahooDailySource,
    get_daily_bar_source,
    non_fmp_intraday_tickers,
    route_by_source,
)
from clients.yahoo_client import yahoo_client
from core.data_groups import effective_state
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


# A row fetched at period "2y" starts at the first trading day on/after
# (today - 2y), so its stored span reads a few calendar days SHORT of the
# tier's nominal days (weekends/holidays at the boundary) -- this much slack
# lets the span still be recognized as that tier.
_TIER_SLACK_DAYS = 10


def _preserved_lookback_days(first_bar: datetime | None, last_bar: datetime | None, interval: str) -> int:
    """The lookback width an existing row was (effectively) fetched at, so
    a refetch triggered by a NARROWER consumer never shrinks it. Derived by
    snapping the row's stored span DOWN to a yfinance period tier, not by
    using the raw span (or today-minus-first-bar): stored bars are only ever
    appended, never dropped, so the raw span grows by a day every night --
    used directly, a "2y" row would snap up to a "5y" refetch after one
    night, and a "5y" one to "10y" a few years on, ratcheting every nightly
    download wider forever (caught by tests/
    test_shared_bars_cache_consumers.py::test_a_universe_only_widens_...).
    A tier is stable no matter how many bars have accumulated since."""
    if first_bar is None or last_bar is None:
        return 0
    span = (last_bar.date() - first_bar.date()).days + 1
    tier_days = 0
    for _, days in _period_steps(interval):
        if span >= days - _TIER_SLACK_DAYS:
            tier_days = days
    return tier_days or span


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


# How far back bars are KEPT, per interval -- consumed by prune_old_bars
# (run weekly from pipeline/prune_cache.py). Bars are only ever appended
# otherwise, so without this a row's stored span grows ~1yr/yr forever.
#
# Both windows sit above the widest fetch any consumer makes today (1d:
# Liquidity Zones' 4yr lookback, fetched at the "5y" tier; 60m: Warren's
# 730-day lookback, the "2y" tier) with a year of headroom, and BELOW the
# next period tier above that fetch (1d: "10y"; 60m has none), so a
# retained row's span always still snaps DOWN to the tier it was fetched
# at -- _preserved_lookback_days never reads a pruned-then-regrown row as
# a wider tier and ratchets the nightly download up. Both invariants are
# pinned by tests/test_shared_bars_cache_prune.py against the consumers'
# real LOOKBACK constants, so a new consumer asking for more than this
# retains fails CI rather than refetching its full window every night
# only to have the weekly prune trim it again.
#
# The 60m window is deliberately wider than any consumer needs today:
# Yahoo serves 60m history only ~730 days back, so a pruned 60m bar can
# never be re-fetched -- it is the only way this app could ever hold more
# intraday history than Yahoo will hand over in one request.
RETENTION_DAYS: dict[str, int] = {
    DAILY_INTERVAL: 6 * 365,
    INTRADAY_INTERVAL: 3 * 365,
}

# SQLite's bound-parameter cap is 999 on older builds; leave headroom for the
# interval/bar_time parameters that ride along with the ticker list.
_TICKER_CHUNK = 400


def _chunks(items: list[str]):
    for i in range(0, len(items), _TICKER_CHUNK):
        yield items[i : i + _TICKER_CHUNK]


def _cache_span(session: Session, tickers: list[str], interval: str) -> dict[str, tuple[datetime, datetime]]:
    """(first bar, last bar) per ticker that has any cached bars -- ONE
    grouped aggregate query per chunk, never loading the bars themselves.
    That is all the freshness and coverage checks need; a full-row load here
    (the first version hydrated every bar as an ORM object, twice per
    ticker) was measured at minutes per nightly run at Warren's volume."""
    span: dict[str, tuple[datetime, datetime]] = {}
    for chunk in _chunks(tickers):
        stmt = (
            select(SharedBarsCache.ticker, func.min(SharedBarsCache.bar_time), func.max(SharedBarsCache.bar_time))
            .where(SharedBarsCache.interval == interval, SharedBarsCache.ticker.in_(chunk))
            .group_by(SharedBarsCache.ticker)
        )
        for ticker, first_bar, last_bar in session.exec(stmt).all():
            span[ticker] = (first_bar, last_bar)
    return span


def _write_rows(
    session: Session, ticker: str, interval: str, df: pd.DataFrame, fetched_at: datetime, replace: bool = False,
    source: str | None = None,
) -> None:
    """Upserts every bar in `df` in ONE executemany round trip. (A per-row
    execute loop, the shape YahooPriceCache._write_rows uses for a few
    hundred daily rows, was measured to dominate this module's cost at
    intraday volumes -- ~3,500 rows/ticker x ~100 tickers -- so it's
    batched here.)

    `df` must already have lowercase open/high/low/close/volume columns --
    this module's single normalized contract for every source (matching
    _load_frames' own read-side shape) since the 2026-09-23 Massive
    migration added a second provider whose own natural casing
    (clients/massive_client.py) differs from yfinance's native
    Open/High/Low/Close/Volume. Every caller of this function (both the
    "1d" DailyBarSource path, clients/daily_bar_sources.py, and the "60m"
    Yahoo-only path below) lowercases at its own fetch boundary before
    reaching here, so this function itself never branches on source.

    `source` is provenance ("fmp" | "yahoo"), only meaningful for "60m" rows (see
    SharedBarsCache.source); "1d" callers leave it None."""
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        # Re-express in Eastern wall-clock time before dropping tzinfo --
        # yfinance's intraday index is already America/New_York, so this
        # is a no-op in practice, but guards against a future caller
        # whose raw fetch came back in a different tz.
        index = index.tz_convert(_EASTERN).tz_localize(None)
    volume = df["volume"].fillna(0).astype("int64").tolist()
    values = [
        {
            "ticker": ticker, "interval": interval, "bar_time": bar_time, "open": o, "high": h, "low": low,
            "close": c, "volume": v, "fetched_at": fetched_at, "source": source,
        }
        for bar_time, o, h, low, c, v in zip(
            index.to_pydatetime(), df["open"].astype(float).tolist(), df["high"].astype(float).tolist(),
            df["low"].astype(float).tolist(), df["close"].astype(float).tolist(), volume,
        )
    ]
    if not values:
        return
    if replace:
        # A complete fresh history (FMP restated the past -- split, spin-off,
        # symbol reuse): drop this ticker's old rows and insert the new ones in
        # ONE transaction, so a failed insert never leaves a half-empty ticker.
        session.execute(delete(SharedBarsCache).where(SharedBarsCache.ticker == ticker, SharedBarsCache.interval == interval))
    stmt = sqlite_insert(SharedBarsCache)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "interval", "bar_time"],
        set_={c: getattr(stmt.excluded, c) for c in ("open", "high", "low", "close", "volume", "fetched_at", "source")},
    )
    session.execute(stmt, values)
    session.commit()


# A bar is only final once the session has closed. A row whose last bar is dated
# the most recently completed session but was WRITTEN before that session's close
# (+ settle) holds a provisional/partial bar (the 2026-09-23 15:50 ET run) and
# must be refetched -- the date-only check in _is_stale can't see that.
_CLOSE_SETTLE = timedelta(minutes=10)


def _provisional_last_bar_tickers(
    session: Session, tickers: list[str], span: dict[str, tuple[datetime, datetime]], reference: datetime
) -> set[str]:
    """Tickers (daily interval) whose newest write predates the close of their
    last bar's own session. max(fetched_at) stands in for "when the last bar
    was written": bars are only ever appended or overwritten by a fetch, so
    the newest write is the one that produced the last bar."""
    completed = _most_recent_completed_trading_date(reference)
    candidates = [t for t in tickers if t in span and span[t][1].date() >= completed]
    out: set[str] = set()
    for chunk in _chunks(candidates):
        stmt = (
            select(SharedBarsCache.ticker, func.max(SharedBarsCache.fetched_at))
            .where(SharedBarsCache.interval == DAILY_INTERVAL, SharedBarsCache.ticker.in_(chunk))
            .group_by(SharedBarsCache.ticker)
        )
        for ticker, fetched_at in session.exec(stmt).all():
            close = datetime.combine(span[ticker][1].date(), time(_MARKET_CLOSE_HOUR_ET), tzinfo=_EASTERN) + _CLOSE_SETTLE
            if fetched_at.astimezone(_EASTERN) < close:  # naive fetched_at = server-local time
                out.add(ticker)
    return out


def _load_frames(session: Session, tickers: list[str], interval: str, start: date) -> dict[str, pd.DataFrame]:
    """Lowercase-column OHLCV DataFrame per ticker, only bars dated on/after
    `start` (the caller's own window, trimmed in SQL rather than after
    loading everything the cache holds), read as plain column tuples rather
    than ORM objects. Indexed by bar_time -- tz-localized back to
    America/New_York for interval="60m" (analysis/entry_signal/resample.py::
    build_2h_session_candles requires a tz-aware index), left naive for
    interval="1d" (every daily-bar consumer -- data/trend_analysis_data.py,
    analysis/liquidity_zones/ -- already expects a naive DatetimeIndex,
    matching YahooPriceCache's own long-standing shape)."""
    start_dt = datetime.combine(start, time.min)
    columns = ["ticker", "bar_time", "open", "high", "low", "close", "volume"]
    frames: dict[str, pd.DataFrame] = {}
    for chunk in _chunks(tickers):
        stmt = (
            select(
                SharedBarsCache.ticker, SharedBarsCache.bar_time, SharedBarsCache.open, SharedBarsCache.high,
                SharedBarsCache.low, SharedBarsCache.close, SharedBarsCache.volume,
            )
            .where(SharedBarsCache.interval == interval, SharedBarsCache.ticker.in_(chunk), SharedBarsCache.bar_time >= start_dt)
            .order_by(SharedBarsCache.ticker, SharedBarsCache.bar_time)
        )
        rows = session.exec(stmt).all()
        if not rows:
            continue
        df = pd.DataFrame.from_records(rows, columns=columns)
        for ticker, group in df.groupby("ticker", sort=False):
            frame = group.drop(columns="ticker").set_index("bar_time")
            frame.index = pd.DatetimeIndex(frame.index)
            if interval == INTRADAY_INTERVAL:
                frame.index = frame.index.tz_localize(_EASTERN)
            frames[ticker] = frame
    return frames


def _eastern_today(reference: datetime | None = None) -> date:
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return ref.astimezone(_EASTERN).date()


def intraday_source_labels(tickers: list[str]) -> dict[str, str]:
    """"fmp" | "yahoo" per ticker: what its cached 60m bars actually are. "fmp" only if EVERY
    cached 60m row is FMP's; anything else (Yahoo-era/fallback rows, non-US tickers, no rows)
    reads "yahoo". Used by the Warren / BB+RSI jobs to label the signal rows they write."""
    with Session(engine) as session:
        non_fmp = non_fmp_intraday_tickers(session, tickers)
        cached = set(
            session.exec(
                select(SharedBarsCache.ticker).where(
                    SharedBarsCache.interval == INTRADAY_INTERVAL, SharedBarsCache.ticker.in_(tickers)
                ).distinct()
            ).all()
        ) if tickers else set()
    return {t: "fmp" if t in cached and t not in non_fmp else "yahoo" for t in tickers}


async def _fetch_yahoo_intraday(to_fetch: dict[str, int], auto_adjust: bool) -> dict[str, pd.DataFrame]:
    """The Yahoo 60m fetch -- the fallback for FMP intraday. yfinance's multi-ticker download takes ONE period per call, so tickers are grouped
    by the period their own need snaps to -- one call per distinct period, not one per ticker."""
    by_period: dict[str, list[str]] = {}
    for ticker, days in to_fetch.items():
        by_period.setdefault(_period_for(INTRADAY_INTERVAL, days), []).append(ticker)
    fetched: dict[str, pd.DataFrame] = {}
    for period, group in by_period.items():
        batch = await yahoo_client.get_history(group, period=period, interval=INTRADAY_INTERVAL, auto_adjust=auto_adjust)
        # yfinance's native Open/High/Low/Close/Volume casing -> this module's lowercase
        # write-boundary contract (see _write_rows).
        fetched.update({t: df.rename(columns=str.lower) for t, df in batch.items()})
    return fetched


async def get_or_fetch_bars_batch(
    tickers: list[str],
    interval: str,
    lookback_days: int,
    auto_adjust: bool = False,
    force: bool = False,
    reference: datetime | None = None,
    fallback_tickers: list[str] | None = None,
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
    monkeypatch this module's own `datetime` import.

    fallback_tickers, when passed a list, gets extended with every "1d"
    US-listed ticker this call did NOT get from FMP (Yahoo served
    it instead; pass a clients.daily_bar_sources.FallbackTickers to also get
    the Yahoo subset) -- clients/daily_bar_sources.py::FMPWithFallback
    -- an out-parameter, not a return-shape change, so this function's
    `dict[str, pd.DataFrame]` return type (many callers) is unaffected.
    For interval="60m" it likewise gets the US-listed tickers FMP intraday
    did not serve (Yahoo did). Non-US tickers are not fetched at all. Lets a caller report a per-run fallback count -- e.g. via
    its own cron_heartbeat message, alongside stale_ticker_count below --
    without this module needing to know anything about cron reporting
    itself."""
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
        span_by_ticker = _cache_span(session, tickers, interval)
        provisional = (
            _provisional_last_bar_tickers(session, tickers, span_by_ticker, now) if interval == DAILY_INTERVAL else set()
        )

    to_fetch: dict[str, int] = {}
    for t in tickers:
        first_bar, last_bar = span_by_ticker.get(t, (None, None))
        existing_width_days = _preserved_lookback_days(first_bar, last_bar, interval)
        if force:
            to_fetch[t] = max(lookback_days, existing_width_days)
            continue
        if last_bar is None:
            to_fetch[t] = lookback_days
            continue
        stale = _is_stale(last_bar, interval, now) or t in provisional
        insufficient = first_bar.date() > needed_start
        if stale or insufficient:
            to_fetch[t] = max(lookback_days, existing_width_days)

    if interval == INTRADAY_INTERVAL and not force and effective_state("intraday_bars")[0]:
        # P4 provenance trigger: a US-listed ticker whose cached 60m rows are not ALL FMP's
        # (Yahoo-era NULL rows, or a Yahoo fallback re-tag) is fetched even when its cache is
        # fresh and wide -- FMPIntradaySource then replaces it in full. Self-completing and
        # loop-free: a successful replace leaves every row "fmp", so the ticker drops out.
        # Skipped while the group is off (everything would fall to Yahoo and re-tag "yahoo"
        # every run) and for non-US tickers (no 60m bars at all since Phase 6a).
        candidates = [t for t in tickers if t in span_by_ticker and t not in to_fetch]
        with Session(engine) as session:
            legacy = non_fmp_intraday_tickers(session, candidates)
        if legacy:
            us_legacy, _ = route_by_source({t: 0 for t in legacy})
            for t in us_legacy:
                to_fetch[t] = max(lookback_days, _preserved_lookback_days(*span_by_ticker[t], interval))

    if to_fetch:
        fetched_at = datetime.now()
        fetched: dict[str, pd.DataFrame] = {}
        replace_tickers: list[str] = []
        fmp_served: set[str] = set()
        if interval == DAILY_INTERVAL:
            # FMP is the primary daily-bar source for every US-LISTED ticker
            # (clients/daily_bar_sources.py::FMPWithFallback), with a per-
            # ticker Yahoo fallback (whole-batch while the
            # daily_prices group is off). Non-US tickers (route_by_source:
            # listing exchange off the cached profile, dot-suffix when there
            # is none) go FMP (daily_prices_intl, phantom bars removed) -> Yahoo. force
            # (e.g. the weekly Sunday resync) makes FMP refetch each ticker's
            # full window instead of the incremental overlap.
            us_tickers, non_us_tickers = route_by_source(to_fetch)
            if us_tickers:
                fetched.update(
                    await get_daily_bar_source().get_daily_bars(
                        us_tickers, auto_adjust, reference=today, fallback_tickers=fallback_tickers,
                        replace_tickers=replace_tickers, full_refresh=force,
                    )
                )
            if non_us_tickers:
                fetched.update(
                    await get_daily_bar_source(non_us=True).get_daily_bars(
                        non_us_tickers, auto_adjust, reference=today, fallback_tickers=fallback_tickers,
                        replace_tickers=replace_tickers, full_refresh=force,
                    )
                )
        else:
            # interval == INTRADAY_INTERVAL (P4): FMP `/historical-chart/1hour` first for
            # US-listed tickers (clients/daily_bar_sources.py::FMPIntradayWithFallback), Yahoo
            # per ticker when FMP delivers nothing and for the whole batch while `intraday_bars`
            # is off. Non-US tickers get NO 60m bars (Phase 6a: non-US support dropped; their
            # Yahoo-only 60m path was removed) -- a cached non-US row is left as is, never
            # refreshed. Every write is tagged with its provenance so a ticker whose cached
            # rows are not all FMP's is fully replaced on its next FMP fetch.
            us_tickers, _non_us_ignored = route_by_source(to_fetch)
            if us_tickers:
                fetched.update(
                    await FMPIntradayWithFallback(fallback=_fetch_yahoo_intraday).get_intraday_bars(
                        us_tickers, auto_adjust, reference=now, fallback_tickers=fallback_tickers,
                        replace_tickers=replace_tickers, full_refresh=force, fmp_served=fmp_served,
                    )
                )
        with Session(engine) as session:
            for ticker, df in fetched.items():
                if df is not None and not df.empty:
                    source = None
                    if interval == INTRADAY_INTERVAL:
                        source = "fmp" if ticker in fmp_served else "yahoo"
                    _write_rows(session, ticker, interval, df, fetched_at, replace=ticker in replace_tickers, source=source)

    with Session(engine) as session:
        return _load_frames(session, tickers, interval, needed_start)


def prune_old_bars(reference: datetime | None = None, dry_run: bool = False) -> dict[str, int]:
    """Deletes bars older than RETENTION_DAYS[interval], measured back from
    today (US/Eastern), per bar -- never whole rows. Returns the number of
    bars deleted (or that would be, under dry_run) per interval.

    Per-bar, not drop-and-refetch: the tail being trimmed is the OLDEST end
    only, so every survivor's freshness (its LAST bar) is untouched, and
    _cache_span's MIN/MAX simply reads the trimmed first bar -- there is no
    state kept anywhere else that could disagree with what's left. A ticker
    whose every bar is past the window (delisted, or long off every
    watchlist) loses its whole row, which is the point.

    Measured from today, not from each ticker's own last bar, so an
    abandoned ticker can't sit on stale bars indefinitely; the one-year
    headroom in RETENTION_DAYS makes a multi-week Yahoo outage a non-event."""
    today = _eastern_today(reference)
    deleted: dict[str, int] = {}
    with Session(engine) as session:
        for interval, days in RETENTION_DAYS.items():
            cutoff = datetime.combine(today - timedelta(days=days), time.min)
            stale = (SharedBarsCache.interval == interval, SharedBarsCache.bar_time < cutoff)
            if dry_run:
                deleted[interval] = session.exec(select(func.count()).select_from(SharedBarsCache).where(*stale)).one()
                continue
            deleted[interval] = session.execute(delete(SharedBarsCache).where(*stale)).rowcount
        session.commit()
    return deleted


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


def stale_ticker_count(tickers: list[str], interval: str, reference: datetime | None = None) -> tuple[int, list[str]]:
    """Read-only, call AFTER a get_or_fetch_bars_batch attempt: how many of
    `tickers` still don't reflect the most recently completed session/bar
    for `interval`, despite that fetch attempt (FMP down AND its Yahoo
    fallback also came up empty, a data-provider-wide gap like the
    2026-09-22 Yahoo Close incident, or simply a ticker never requested).

    This is the stale-data guard every migrated nightly job (Trend,
    Liquidity Zones, Sector Heatmap, Momentum) calls right after its own
    get_or_fetch_bars_batch call, reporting the result via the existing
    CronRunContext.message (see core/cron_health.py) -- no schema or
    frontend change, this reuses the message field the Settings "Status"
    Scheduled Jobs table already renders. Deliberately does NOT escalate to
    a heartbeat failure on its own -- a handful of stale tickers is normal
    (delistings, a thin provider gap); Market Breadth's own MIN_COVERAGE/
    InsufficientCoverageError gate is untouched and stays the one job that
    fails loudly on genuine insufficiency. Closes the "4 of 5 jobs silently
    reported cron success while computing on a session-old bar" gap found
    in docs/yahoo_close_data_gap_investigation_2026-09-23.md, without the
    materially bigger bars_as_of-to-frontend wiring that doc's own fix
    option 3 flagged as a separate follow-up."""
    if not tickers:
        return 0, []
    with Session(engine) as session:
        span_by_ticker = _cache_span(session, tickers, interval)
    stale = [t for t in tickers if _is_stale(span_by_ticker.get(t, (None, None))[1], interval, reference)]
    return len(stale), stale
