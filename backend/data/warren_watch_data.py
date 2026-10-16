"""Orchestration for the Warren Signals watch table (docs/specs/warren-signals-page.md): reads the 2h arrows from the
existing replay, folds them into `WarrenWatchRow` with analysis/warren_signal/watch.py, and keeps `WarrenWatchCursor`
so a rerun is a no-op.

The candles are built exactly as the Chart tab's 2H·90D range builds them (the fast builder, the forming candle
dropped, window-start index, the same volume-guarded replay for SPY/QQQ/TQQQ/TECL), so the arrows the table acts on
cannot drift from the chart. Candle times in the table are therefore window starts (09:30/11:30/13:30/15:30), which
differ from `WarrenSignalEvent.fired_at` (the window's LAST bar) for every window but the 15:30 one.

Seed and nightly are the same code: a ticker with no cursor reads the last SEED_MONTHS of candles, one with a cursor reads
the candles after it. The cursor and the row are written in one transaction."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlmodel import Session, select

from analysis.entry_signal.resample import build_2h_session_candles_fast, drop_forming_candles, index_by_window_start
from analysis.liquidity_zones.types import LiquidityZoneSettings
from analysis.warren_signal.state_machine import replay
from analysis.warren_signal.types import WarrenReplayResult
from analysis.warren_signal.watch import WatchState, advance
from clients.daily_bar_sources import _is_half_day
from core.db import engine
from core.models import WarrenWatchCursor, WarrenWatchRow
from core.tickers import normalize_ticker
from data.liquidity_zone_data import compute_liquidity_zones_2h
from data.warren_signal_data import profile_for, read_cached_daily_volume, signal_candles, volume_guard_applies

logger = logging.getLogger(__name__)

# The first run for a ticker reads this many months of candles back from its last completed candle.
SEED_MONTHS = 3

_ET = ZoneInfo("America/New_York")


class SecondSupportLookup:
    """The 2nd LP as of a candle: the second-nearest support below that candle's close, from the Chart tab's 2h LP read
    (compute_liquidity_zones_2h, the shared LP settings) over the candles up to and including it. None when fewer than
    two supports exist (including a `max_lps_per_side` below 2). `calls` counts the LP computations made."""

    def __init__(self, candles: pd.DataFrame, settings: LiquidityZoneSettings):
        self._candles = candles
        self._settings = settings
        self._cache: dict[int, float | None] = {}
        self.calls = 0

    def __call__(self, pos: int) -> float | None:
        if pos not in self._cache:
            self.calls += 1
            support = compute_liquidity_zones_2h(self._candles.iloc[: pos + 1], self._settings).support
            self._cache[pos] = float(support[1].price) if len(support) >= 2 else None
        return self._cache[pos]


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
    candles_read: int


def _state_from_row(row: WarrenWatchRow) -> WatchState:
    return WatchState(
        row.profile, row.latest_arrow_kind, row.latest_arrow_at, row.instruction_type, row.entry_kind, row.entry_at,
        row.entry_price, row.stop_price, row.stop_basis, row.status, row.breached_at, row.last_signal_at,
    )


def _content(state: WatchState) -> tuple:
    return (
        state.profile, state.latest_arrow_kind, state.latest_arrow_at, state.instruction_type, state.entry_kind, state.entry_at,
        state.entry_price, state.stop_price, state.stop_basis, state.status, state.breached_at, state.last_signal_at,
    )


def _row_values(state: WatchState) -> dict:
    return {
        "profile": state.profile, "latest_arrow_kind": state.latest_arrow_kind, "latest_arrow_at": state.latest_arrow_at,
        "instruction_type": state.instruction_type, "instruction_text": state.instruction_text, "entry_kind": state.entry_kind,
        "entry_at": state.entry_at, "entry_price": state.entry_price, "stop_price": state.stop_price, "stop_basis": state.stop_basis,
        "status": state.status, "breached_at": state.breached_at, "last_signal_at": state.last_signal_at,
    }


def update_warren_watch(
    ticker: str,
    bars: pd.DataFrame,
    settings: LiquidityZoneSettings,
    now: datetime | None = None,
    daily_volume: pd.Series | None = None,
) -> WatchUpdate:
    """Fold the ticker's new completed 2h candles into its watch row. `bars` are the raw 60m bars (the shared cache's
    frame). Raises ValueError when no completed candle can be built. Idempotent: a second call with the same bars
    reads no candle and writes nothing but an unchanged `as_of`."""
    ticker = normalize_ticker(ticker)
    now = now or datetime.now(timezone.utc)
    candles = completed_candles(bars, now)
    if candles.empty:
        raise ValueError("No completed 2h candles")
    as_of = candles.index[-1].to_pydatetime()
    wall = datetime.now()

    with Session(engine) as session:
        row = session.get(WarrenWatchRow, ticker)
        cursor = session.get(WarrenWatchCursor, ticker)
        removed_at = row.removed_at if row is not None else None

        after = cursor.processed_through if cursor is not None else (pd.Timestamp(as_of) - pd.DateOffset(months=SEED_MONTHS)).to_pydatetime()
        if removed_at is not None and removed_at > after:
            after = removed_at  # arrows at or before the removal are ignored
        state = _state_from_row(row) if row is not None and removed_at is None else None

        lookup = SecondSupportLookup(candles, settings)
        read = int(len(candles) - candles.index.searchsorted(pd.Timestamp(after), side="right"))
        new_state = state
        if read > 0:
            result = watch_replay(ticker, candles, daily_volume)
            new_state = advance(
                state, candles, result.events, result.first_yellow_after_blue_at, profile_for(ticker).name, after, lookup
            )
            if new_state is not None:
                new_state = replace(new_state, profile=profile_for(ticker).name)

        if new_state is None:
            outcome = "removed" if row is not None else "no_row"
        elif row is None or removed_at is not None:
            session.merge(WarrenWatchRow(ticker=ticker, last_updated_at=wall, removed_at=None, as_of=as_of, **_row_values(new_state)))
            outcome = "created"
        elif _content(new_state) != _content(state):
            for field, value in _row_values(new_state).items():
                setattr(row, field, value)
            row.last_updated_at, row.as_of = wall, as_of
            session.add(row)
            outcome = "changed"
        else:
            if row.as_of != as_of:
                row.as_of = as_of
                session.add(row)
            outcome = "unchanged"

        if cursor is None or cursor.processed_through < as_of:
            session.merge(WarrenWatchCursor(ticker=ticker, processed_through=as_of, updated_at=wall))
        session.commit()
    return WatchUpdate(outcome, lookup.calls, max(read, 0))


def remove_watch_row(ticker: str, now_et: datetime | None = None) -> bool:
    """Soft-delete a ticker's row: sets removed_at (naive America/New_York, comparable with candle times). Arrows on
    candles that started at or before it are ignored from then on. False when the ticker has no row or it is already
    removed. No endpoint calls this yet (phase 2)."""
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

