"""Orchestration for the Warren Signals watch table (docs/specs/warren-signals-page.md): reads the 2h arrows from the
existing replay and replays them into `WarrenWatchRow` with analysis/warren_signal/watch.py.

STATELESS since 2026-10-17: every night each ticker's row is recomputed by replaying ALL its completed 2h candles from
REPLAY_ANCHOR on the bars as they are NOW, and the stored row is rewritten only if the result differs. The earlier cursor
design folded each session in once, from the 60m bars FMP serves the night right after it; those are provisional (the
newest session's prices and volumes are revised on later fetches), so a row could keep arrows and prices the final bars no
longer give (RMD, ADP, ROBO). `WarrenWatchCursor` is now only bookkeeping (the page's "as of").

The candles are built exactly as the Chart tab's 2H·90D range builds them (the fast builder, the forming candle
dropped, window-start index, the same volume-guarded replay for SPY/QQQ/TQQQ/TECL), so the arrows the table acts on
cannot drift from the chart. Candle times in the table are therefore window starts (09:30/11:30/13:30/15:30), which
differ from `WarrenSignalEvent.fired_at` (the window's LAST bar) for every window but the 15:30 one.

Seed and nightly are the same code. The replay starts at a FIXED anchor (not a sliding 12 months, which would change the
state of an open trade as the window moves), so an arrow near the start is not mistaken for a fresh entry when an earlier
trade existed. A ticker with no row gets one only if it had an up arrow in the last ROW_MONTHS (3): the long replay decides
the state, not whether a row exists. A removed row (`removed_at`) is replayed only from the removal on and stays removed
until an up arrow falls after it; the woken row keeps `replay_from` = the removal time, so later nights do not bring the
old trade back. The row and the cursor are written in one transaction."""

import logging
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import func, inspect
from sqlmodel import Session, select

from analysis.entry_signal.resample import build_2h_session_candles_fast, drop_forming_candles, index_by_window_start
from analysis.liquidity_zones.types import LiquidityZoneSettings
from analysis.warren_signal.state_machine import replay
from analysis.warren_signal.types import WarrenReplayResult
from analysis.warren_signal.indicators import compute_atr_wilder
from analysis.warren_signal.watch import WatchState, advance, pick_support, stop_trailed_since_arrow
from analysis.warren_signal.watch_text import watch_instruction_text
from clients.daily_bar_sources import _is_half_day
from clients.shared_bars_cache import _eastern_today, read_cached_completed_daily_bars
from core.db import engine
from core.models import WarrenWatchCursor, WarrenWatchRow
from core.tickers import normalize_ticker
from data.liquidity_zone_data import compute_liquidity_zones_2h
from data.warren_signal_data import profile_for, read_cached_daily_volume, signal_candles, volume_guard_applies

logger = logging.getLogger(__name__)

# The first run for a ticker replays this many months of candles back from its last completed candle (the state), and
# creates a row only if an up arrow falls in the last ROW_MONTHS of them.
SEED_MONTHS = 12
ROW_MONTHS = 3
# The fixed start of every replay: the first seed's as_of (2026-10-15 15:30) minus SEED_MONTHS. A constant so the state does not
# depend on the date; it must be moved forward before the cached 60m history (LOOKBACK_DAYS = 730) no longer leaves a 180-day
# warm-up before it (2027-04-17 at this value). anchor_headroom() below counts the days left and the admin banner warns from 300; the
# steps are the spec's "Re-anchor runbook" (docs/specs/warren-signals-page.md). EDITING THIS ON MAIN IS THE APPLY: the nightly cron imports
# the working tree and rewrites every row that differs, so change it on a branch and apply by hand.
REPLAY_ANCHOR = datetime(2025, 10, 15, 15, 30)
_UP_KINDS = ("blue_up", "yellow_up", "gray_up")

# How far back the page's "Last" price looks for a cached daily bar (a long weekend plus a delisting-style gap still finds one).
LAST_PRICE_LOOKBACK_DAYS = 30

_ET = ZoneInfo("America/New_York")


# The daily bars the LP gate's ATR reads: calendar days of cached 1d bars (about 960 completed sessions; Wilder smoothing needs a long run-in) and
# the sessions needed before ATR(14) exists.
DAILY_ATR_LOOKBACK_DAYS = 1400
DAILY_ATR_MIN_SESSIONS = 14


def load_daily_bars(ticker: str, now: datetime | None = None) -> pd.DataFrame:
    """The ticker's COMPLETED daily bars from the cache (a pure read: no FMP call, no write; a live or provisional newest bar is already dropped by
    `read_cached_completed_daily_bars`). Empty when nothing is cached."""
    return read_cached_completed_daily_bars(normalize_ticker(ticker), DAILY_ATR_LOOKBACK_DAYS, reference=now)


def daily_atr_for_candles(candle_index: pd.DatetimeIndex, daily: pd.DataFrame | None) -> np.ndarray:
    """Daily ATR(14) (Wilder smoothing of the true range, which includes the overnight gap: `indicators.compute_atr_wilder`, the Chart tab's FVG
    helper) as of the last COMPLETED session strictly BEFORE each candle's date, one value per candle; NaN where it does not exist (no daily bars,
    or fewer than 14 completed sessions before that date). Only sessions before the candle's date are used, so a later daily bar can never change
    an earlier candle's value (no look-ahead; the candle's own session is not used even once it has closed)."""
    n = len(candle_index)
    if daily is None or daily.empty or not {"high", "low", "close"} <= set(daily.columns):
        return np.full(n, np.nan)
    atr = compute_atr_wilder(daily["high"], daily["low"], daily["close"]).to_numpy(dtype=float)
    sessions = pd.DatetimeIndex(daily.index).normalize()
    j = sessions.searchsorted(pd.DatetimeIndex(candle_index).normalize(), side="left") - 1  # position of the last session < the candle's date
    out = np.where(j >= DAILY_ATR_MIN_SESSIONS - 1, atr[np.clip(j, 0, None)], np.nan)
    return out


class SecondSupportLookup:
    """The support the stop may use as of a candle (`__call__`, the SELECTED LP): the Chart tab's 2h LP read (compute_liquidity_zones_2h, the shared
    LP settings; at most `max_lps_per_side` supports, nearest first) over the candles up to and including it, then `pick_support`'s eligibility
    gate with the daily ATR as of that candle (`atr`, one value per candle, see `daily_atr_for_candles`; None = no ATR for any candle, the gate is
    off). `plain(pos)` is the ungated 2nd-nearest support, which `advance` uses under rules with `lp_atr_gate` off. `calls` counts the LP
    computations made; `gate_stats` counts the selected-LP uses by `pick_support` status (plus "rejected": uses where the 2nd LP was not the answer)."""

    def __init__(self, candles: pd.DataFrame, settings: LiquidityZoneSettings, atr: np.ndarray | None = None):
        self._candles = candles
        self._closes = candles["close"].to_numpy(dtype=float)
        self._settings = settings
        self._atr = atr
        self._supports: dict[int, tuple[float, ...]] = {}
        self.calls = 0
        self.gate_stats: dict[str, int] = {"uses": 0, "eligible": 0, "walked": 0, "none": 0, "off": 0, "short": 0}

    def supports(self, pos: int) -> tuple[float, ...]:
        if pos not in self._supports:
            self.calls += 1
            support = compute_liquidity_zones_2h(self._candles.iloc[: pos + 1], self._settings).support
            self._supports[pos] = tuple(float(z.price) for z in support)
        return self._supports[pos]

    def plain(self, pos: int) -> float | None:
        """The 2nd-nearest support (None with fewer than two): the rule before the gate."""
        supports = self.supports(pos)
        return supports[1] if len(supports) >= 2 else None

    def __call__(self, pos: int) -> float | None:
        atr = None if self._atr is None else float(self._atr[pos])
        pick = pick_support(self.supports(pos), float(self._closes[pos]), atr if atr is not None and atr == atr else None)
        self.gate_stats["uses"] += 1
        self.gate_stats[pick.status] += 1
        return pick.value


def completed_candles(bars: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """The ticker's completed 2h candles, window-start indexed (naive America/New_York) -- the Chart tab's series."""
    if bars is None or bars.empty:
        return pd.DataFrame()
    candles = drop_forming_candles(build_2h_session_candles_fast(bars), now, is_half_day=_is_half_day)
    return index_by_window_start(candles) if not candles.empty else candles


def watch_replay(ticker: str, candles: pd.DataFrame, daily_volume: pd.Series | None = None) -> WarrenReplayResult:
    """The Warren replay the watch reads: the same call the Chart tab's 2H range makes (profile + volume guard)."""
    ticker = normalize_ticker(ticker)
    if volume_guard_applies(ticker) and daily_volume is None:
        daily_volume = read_cached_daily_volume(ticker)
    return replay(signal_candles(ticker, candles, daily_volume), profile_for(ticker))


@dataclass(frozen=True)
class WatchUpdate:
    """What one ticker's update did: `outcome` is "created", "changed" (content moved), "unchanged" (only as_of or
    nothing), "no_row" (no up arrow yet) or "removed" (a removed row nothing newer woke)."""

    outcome: str
    lp_calls: int
    candles_read: int  # the candles replayed (everything after the replay start)
    changes: dict = field(default_factory=dict)  # {field: (stored, new)} for a "changed" row; {"<new row>": ...} for a created one
    lp_gate: dict = field(default_factory=dict)  # SecondSupportLookup.gate_stats of this ticker's replay (uses, eligible, walked, none, off, short)
    daily_atr: bool = True  # False when the ticker had no usable daily ATR for any candle (no daily bars cached, or fewer than 14 sessions)


def _has_recent_up(events, as_of: datetime) -> bool:
    """An up arrow (Blue, Yellow or Gray) on a candle after `as_of - ROW_MONTHS` -- the seed's row-creation rule."""
    cutoff = (pd.Timestamp(as_of) - pd.DateOffset(months=ROW_MONTHS)).to_pydatetime()
    return any(e.kind in _UP_KINDS and e.fired_at > cutoff for e in events)


def _state_from_row(row: WarrenWatchRow) -> WatchState:
    return WatchState(
        row.profile, row.latest_arrow_kind, row.latest_arrow_at, row.instruction_type, row.entry_kind, row.entry_at,
        row.entry_price, row.stop_price, row.stop_basis, row.status, row.breached_at, row.last_signal_at,
        row.stop_moved_at, row.stop_moved_by,
    )


def _content(state: WatchState) -> tuple:
    return (
        state.profile, state.latest_arrow_kind, state.latest_arrow_at, state.instruction_type, state.entry_kind, state.entry_at,
        state.entry_price, state.stop_price, state.stop_basis, state.status, state.breached_at, state.last_signal_at,
        state.stop_moved_at, state.stop_moved_by,
    )


def _row_values(state: WatchState) -> dict:
    return {
        "profile": state.profile, "latest_arrow_kind": state.latest_arrow_kind, "latest_arrow_at": state.latest_arrow_at,
        "instruction_type": state.instruction_type, "instruction_text": state.instruction_text, "entry_kind": state.entry_kind,
        "entry_at": state.entry_at, "entry_price": state.entry_price, "stop_price": state.stop_price, "stop_basis": state.stop_basis,
        "stop_moved_at": state.stop_moved_at, "stop_moved_by": state.stop_moved_by,
        "status": state.status, "breached_at": state.breached_at, "last_signal_at": state.last_signal_at,
    }


_STATE_FIELDS = (
    "profile", "latest_arrow_kind", "latest_arrow_at", "instruction_type", "entry_kind", "entry_at", "entry_price", "stop_price",
    "stop_basis", "status", "breached_at", "last_signal_at", "stop_moved_at", "stop_moved_by",
)


def _load_row(session: Session, ticker: str) -> WarrenWatchRow | None:
    """The ticker's row. Reads even a database that does not have the newest columns yet (a dry run against a file `init_db` has
    not migrated): then only the columns that exist are selected and the missing ones read as None."""
    present = {c["name"] for c in inspect(session.get_bind()).get_columns(WarrenWatchRow.__tablename__)}
    if {c.name for c in WarrenWatchRow.__table__.c} <= present:
        return session.get(WarrenWatchRow, ticker)
    cols = [c for c in WarrenWatchRow.__table__.c if c.name in present]
    found = session.exec(select(*cols).where(WarrenWatchRow.ticker == ticker)).first()
    return None if found is None else WarrenWatchRow.model_construct(**dict(zip([c.name for c in cols], found)))


def update_warren_watch(
    ticker: str,
    bars: pd.DataFrame,
    settings: LiquidityZoneSettings,
    now: datetime | None = None,
    daily_volume: pd.Series | None = None,
    dry_run: bool = False,
    daily: pd.DataFrame | None = None,
) -> WatchUpdate:
    """Recompute the ticker's watch row from scratch: replay every completed 2h candle after REPLAY_ANCHOR (or after the removal /
    `replay_from` of a removed or woken row) on `bars` (the shared cache's raw 60m frame; no download here) and write the row only
    if the result differs from the stored one. Raises ValueError when no completed candle can be built. Idempotent: a second call
    on the same bars writes nothing but an unchanged `as_of`. `dry_run` computes and reports (`changes`) and writes nothing. `daily` = the completed daily bars for the LP gate's ATR (default: read
    from the cache, no network; see `load_daily_bars`)."""
    ticker = normalize_ticker(ticker)
    now = now or datetime.now(timezone.utc)
    candles = completed_candles(bars, now)
    if candles.empty:
        raise ValueError("No completed 2h candles")
    as_of = candles.index[-1].to_pydatetime()
    wall = datetime.now()
    profile = profile_for(ticker).name
    atr = daily_atr_for_candles(candles.index, load_daily_bars(ticker, now) if daily is None else daily)  # a cache read (no network), before the row session opens

    with Session(engine) as session:
        row = _load_row(session, ticker)
        cursor = session.get(WarrenWatchCursor, ticker)
        removed_at = row.removed_at if row is not None else None

        after = REPLAY_ANCHOR
        for cut in (getattr(row, "replay_from", None), removed_at):  # a woken row replays from its removal; a removed one too
            if cut is not None and cut > after:
                after = cut
        stored = _state_from_row(row) if row is not None and removed_at is None else None

        lookup = SecondSupportLookup(candles, settings, atr)
        first = int(candles.index.searchsorted(pd.Timestamp(after), side="right"))
        read = len(candles) - first
        atr_ok = bool(np.isfinite(atr[first:]).any())  # False = the gate is off for every candle this replay reads
        result = watch_replay(ticker, candles, daily_volume)
        new_state = advance(None, candles, result.events, result.first_yellow_after_blue_at, profile, after, lookup)
        if new_state is not None:
            new_state = replace(new_state, profile=profile)

        changes: dict = {}
        if row is None:
            create = new_state is not None and _has_recent_up(result.events, as_of)  # a first row needs an up arrow in the last 3 months
            outcome = "created" if create else "no_row"
        elif removed_at is not None:
            outcome = "created" if new_state is not None else "removed"  # only an up arrow after the removal wakes it
        elif new_state is None:
            outcome = "unchanged"  # the replay gives no row (history revised away): keep what is stored, never delete
        elif _content(new_state) != _content(stored):
            outcome = "changed"
            changes = {f: (getattr(stored, f), getattr(new_state, f)) for f in _STATE_FIELDS if getattr(stored, f) != getattr(new_state, f)}
        else:
            outcome = "unchanged"
        if outcome == "created":
            changes = {"<new row>": (None, _brief(new_state))}

        if not dry_run:
            if outcome == "created":
                values = _row_values(new_state)
                session.merge(
                    WarrenWatchRow(ticker=ticker, last_updated_at=wall, removed_at=None, as_of=as_of, replay_from=removed_at, **values)
                )
            elif outcome == "changed":
                for name, value in _row_values(new_state).items():
                    setattr(row, name, value)
                row.last_updated_at, row.as_of = wall, as_of
                session.add(row)
            elif outcome == "unchanged" and row is not None and removed_at is None and row.as_of != as_of:
                row.as_of = as_of
                session.add(row)
            if cursor is None or cursor.processed_through < as_of:
                session.merge(WarrenWatchCursor(ticker=ticker, processed_through=as_of, updated_at=wall))
            session.commit()
    return WatchUpdate(outcome, lookup.calls, max(read, 0), changes, dict(lookup.gate_stats), atr_ok)


# Anchor headroom (docs/specs/warren-signals-page.md, "Anchor headroom and re-anchor runbook"): the days of cached 60m history before REPLAY_ANCHOR
# in the slice the nightly step reads. The slice start moves forward one day a day, so headroom falls one day a day until the anchor is moved. The
# 2026-10-18 sliding-start test: arrows start flipping at about 270 days, so "warning" below 300 and "urgent" below 270; the 180-day event write
# gate warm-up is the hard deadline.
ANCHOR_WARNING_DAYS = 300
ANCHOR_URGENT_DAYS = 270
ANCHOR_DEADLINE_DAYS = 180


@dataclass(frozen=True)
class AnchorHeadroom:
    """`days` = anchor date minus the nightly slice's first date; `level` "none" | "warning" | "urgent". The dates are the first day the level
    holds (days below 300 / below 270) and the day `days` reaches 180; a date already passed stays in the past."""

    days: int
    level: str
    anchor: datetime
    slice_start: date
    warning_date: date
    urgent_date: date
    deadline_date: date


def anchor_headroom(
    now: datetime | None = None,
    anchor: datetime | None = None,
    warning_days: int = ANCHOR_WARNING_DAYS,
    urgent_days: int = ANCHOR_URGENT_DAYS,
    deadline_days: int = ANCHOR_DEADLINE_DAYS,
) -> AnchorHeadroom:
    """How much warm-up history the fixed replay anchor has left. The slice start is the nightly step's own (reconcile_warren_events.nightly_bars_start:
    ET today minus LOOKBACK_DAYS - 1), so this follows LOOKBACK_DAYS; the first candle is the first session on or after it (up to 3 days later), so
    the figure can read up to 3 days high. A pure computation: no DB, no FMP. The threshold arguments are test seams (the defaults are the rule)."""
    from pipeline.backfills.reconcile_warren_events import nightly_bars_start  # lazy: that module imports the nightly job, which imports this one

    now = now or datetime.now(timezone.utc)
    anchor = anchor or REPLAY_ANCHOR
    slice_start = nightly_bars_start(now)
    today = _eastern_today(now)
    days = (anchor.date() - slice_start).days
    level = "urgent" if days < urgent_days else "warning" if days < warning_days else "none"
    return AnchorHeadroom(
        days=days, level=level, anchor=anchor, slice_start=slice_start,
        warning_date=today + timedelta(days=days - warning_days + 1),
        urgent_date=today + timedelta(days=days - urgent_days + 1),
        deadline_date=today + timedelta(days=days - deadline_days),
    )


def _brief(state: WatchState) -> str:
    stop = "no stop" if state.stop_price is None else f"stop {state.stop_price:.2f} {state.stop_basis}"
    entry = "no entry" if state.entry_price is None else f"{state.entry_kind} entry {state.entry_price:.2f} {state.entry_at:%Y-%m-%d %H:%M}"
    return f"{entry}; {stop}; {state.status}; latest {state.latest_arrow_kind} {state.latest_arrow_at:%Y-%m-%d %H:%M}"


def remove_watch_row(ticker: str, now_et: datetime | None = None) -> bool:
    """Soft-delete a ticker's row: sets removed_at (naive America/New_York, comparable with candle times). Arrows on
    candles that started at or before it are ignored from then on. False when the ticker has no row or it is already
    removed. Called by DELETE /api/technical-ideas/warren/{ticker} (admin)."""
    ticker = normalize_ticker(ticker)
    now_et = now_et or datetime.now(_ET).replace(tzinfo=None)
    with Session(engine) as session:
        row = session.get(WarrenWatchRow, ticker)
        if row is None or row.removed_at is not None:
            return False
        row.removed_at = now_et
        session.add(row)
        session.commit()
    return True


def list_watch_rows(include_removed: bool = False) -> list[WarrenWatchRow]:
    with Session(engine) as session:
        stmt = select(WarrenWatchRow).order_by(WarrenWatchRow.ticker)
        if not include_removed:
            stmt = stmt.where(WarrenWatchRow.removed_at.is_(None))
        return list(session.exec(stmt).all())



# The four 2h window starts of a full session; an early close (13:00) has only those that start before it.
_WINDOW_STARTS = (time(9, 30), time(11, 30), time(13, 30), time(15, 30))


def _window_starts_between(after: datetime, through: datetime) -> list[datetime]:
    """Every 2h window start in (after, through], naive America/New_York, from the NYSE calendar (holidays and early
    closes respected). A calendar read, not a bars read, so the page endpoint stays cache-only and write-free."""
    from helpers.trading_calendar import xnys_sessions  # lazy: loads pandas_market_calendars (~0.9 s)

    starts: list[datetime] = []
    for day, _, close in xnys_sessions(after.date(), through.date()):
        close_t = close.time()
        starts.extend(
            datetime.combine(day, t) for t in _WINDOW_STARTS if t < close_t and after < datetime.combine(day, t) <= through
        )
    return starts


def _to_et_naive(wall: datetime) -> datetime:
    """The row's `last_updated_at` is naive server-local wall clock; return it as naive America/New_York."""
    return wall.astimezone(_ET).replace(tzinfo=None)


def pl_pct(last_price: float | None, entry_price: float | None) -> float | None:
    """P/L as a fraction: (last - entry) / entry. None without a last price or an entry."""
    if last_price is None or not entry_price:
        return None
    return (last_price - entry_price) / entry_price


def row_pl_pct(status: str, last_price: float | None, entry_price: float | None, stop_price: float | None) -> float | None:
    """The page's P/L %. An ACTIVE row is marked to the latest daily close; a BREACHED row is frozen at its stop,
    (stop - entry) / entry, an estimate of the exit (no gap through the stop), so it does not move with the price. None without an entry,
    or on a breached row without a stop."""
    if status == "breached":
        return pl_pct(stop_price, entry_price)
    return pl_pct(last_price, entry_price)


def stop_distance_pct(last_price: float | None, stop_price: float | None) -> float | None:
    """Distance to the stop as a fraction of the last price: (last - stop) / last. Positive = price above the stop, negative =
    already below it. None without a last price or a stop."""
    if not last_price or stop_price is None:
        return None
    return (last_price - stop_price) / last_price


def latest_daily_close(ticker: str) -> tuple[float | None, date | None]:
    """The ticker's latest completed DAILY close and its date, from the cached 1d bars (a pure read: no FMP call, no write).
    (None, None) when nothing is cached."""
    frame = read_cached_completed_daily_bars(normalize_ticker(ticker), LAST_PRICE_LOOKBACK_DAYS)
    if frame.empty or "close" not in frame.columns:
        return None, None
    close = frame["close"].dropna()
    if close.empty:
        return None, None
    return float(close.iloc[-1]), close.index[-1].date()


def watch_table() -> dict:
    """The page's read of the stored table: every non-removed row plus the table's `as_of` (the last completed 2h candle any
    ticker has been folded through; falls back to the rows' own `as_of`). Reads only; no FMP, no write. Row dicts carry the
    latest arrow split into colour and direction, and two ages in 2h candles up to `as_of`: since the latest arrow's candle
    (`age_bars`) and since the latest UP arrow's candle (`last_signal_age_bars`). Candle times are window starts (naive ET)."""
    with Session(engine) as session:
        rows = list(session.exec(select(WarrenWatchRow).where(WarrenWatchRow.removed_at.is_(None)).order_by(WarrenWatchRow.ticker)).all())
        cursor_max = session.exec(select(func.max(WarrenWatchCursor.processed_through))).one()
    as_of = cursor_max or max((r.as_of for r in rows), default=None)

    ages: dict[datetime, int] = {}
    if as_of is not None and rows:
        stamps = {r.latest_arrow_at for r in rows} | {r.last_signal_at for r in rows}
        starts = pd.DatetimeIndex(_window_starts_between(min(stamps) - timedelta(days=1), as_of))
        for stamp in stamps:
            ages[stamp] = int(len(starts) - starts.searchsorted(pd.Timestamp(stamp), side="right"))

    last_closes = {r.ticker: latest_daily_close(r.ticker) for r in rows}
    out = []
    for r in rows:
        color, _, direction = r.latest_arrow_kind.partition("_")
        last_price, last_price_date = last_closes[r.ticker]
        out.append(
            {
                "ticker": r.ticker, "profile": r.profile, "latest_arrow_color": color, "latest_arrow_direction": direction,
                "latest_arrow_at": r.latest_arrow_at, "instruction_type": r.instruction_type,
                "instruction_text": watch_instruction_text(
                    r.profile, r.instruction_type, r.latest_arrow_at, r.entry_kind, r.entry_at, r.stop_moved_at, r.stop_moved_by
                ),
                "entry_kind": r.entry_kind, "entry_at": r.entry_at, "entry_price": r.entry_price, "stop_price": r.stop_price,
                "stop_basis": r.stop_basis,
                "stop_moved_at": r.stop_moved_at, "stop_moved_by": r.stop_moved_by,
                "stop_trailed_since_arrow": stop_trailed_since_arrow(
                    r.status, r.stop_price, r.stop_basis, r.stop_moved_by, r.stop_moved_at, r.latest_arrow_at
                ),
                "last_price": last_price, "last_price_date": last_price_date,
                "pl_pct": row_pl_pct(r.status, last_price, r.entry_price, r.stop_price), "stop_distance_pct": stop_distance_pct(last_price, r.stop_price),
                "status": r.status, "breached_at": r.breached_at, "last_signal_at": r.last_signal_at,
                "last_updated_at": _to_et_naive(r.last_updated_at),
                "age_bars": ages.get(r.latest_arrow_at), "last_signal_age_bars": ages.get(r.last_signal_at),
            }
        )
    return {"as_of": as_of, "rows": out}
