"""The Warren Signals watch table's update rules (docs/specs/warren-signals-page.md). Pure -- no DB, no FMP.

A watch row is a per-ticker note about the latest Warren arrows: what the on-chart instruction says, the entry the
current row state started from, and the stop that instruction implies. `advance` walks 2h candles oldest to newest,
applies each candle's arrows to the row (or creates it), and checks the stop against each candle's low. The arrows
themselves come from the existing replay (state_machine.py), unchanged: this module only reads them.

Rules, per candle (the stop in force BEFORE the candle's arrows is the one its low is tested against, so a stop set
on candle t is first tested on t+1, as the ThinkScript's `rawStopHit` needs `barsSinceYellow > 0`):

1. Breach: row active, a stop exists, low <= stop -> status "breached", breached_at = this candle; the stop and the
   last instruction are kept. A row with no stop cannot breach.
2. Up arrows (one per candle; Blue beats Yellow beats Gray, as the ThinkScript resets its yellow count on a Blue):
   - Blue Up (type 2): entry kind blue, entry = this candle's close, no stop, active (clears a breach).
   - Yellow Up (type 3): fresh entry (no row, breached row, or a row that never had an entry) -> entry kind yellow,
     stop = 0.9 x this candle's low, basis "10%". On an active row with an entry -> stop = min(2nd LP, 0.9 x low),
     basis whichever is lower ("10%" on a tie, or when there is no 2nd LP); the entry is unchanged.
   - Yellow Up that is the first after a Blue (type 4) and Gray Up (type 1): no action on an existing active row, only the
     dates (and the latest arrow) move. A Gray Up with no row creates one with no entry and no stop; a type-4 Yellow
     with no row is treated as a fresh yellow entry.
3. Down arrows (one per candle; Yellow Down beats Blue Down beats Gray Down, the ThinkScript's text order) apply only
   to an existing row: the instruction text and the latest arrow update; the stop changes only on an active row
   with an entry: Blue Down -> 2nd LP; Yellow Down -> 2nd LP if the entry kind is yellow; Gray Down -> the entry price
   if the entry kind is yellow. No tighten-only rule: a stop may move down.

2nd LP = the second-nearest support below the close of the arrow candle (`lp_second`, supplied by the caller and
called only where a rule above needs it)."""

from collections import defaultdict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import pandas as pd

from .instructions import (
    BLUE_DOWN,
    BLUE_UP,
    GRAY_DOWN,
    GRAY_UP,
    YELLOW_DOWN,
    YELLOW_UP,
    text_for,
)
from .state_machine import STOP_PERCENT
from .types import WarrenSignalEvent

STATUS_ACTIVE = "active"
STATUS_BREACHED = "breached"

BASIS_PCT = "10%"
BASIS_LP = "LP"
BASIS_ENTRY = "entry"
BASIS_NONE = "none"

ENTRY_BLUE = "blue"
ENTRY_YELLOW = "yellow"

# The 10% stop is `yellowEntryHeld * (1 - stopPercent / 100)` in the ThinkScript.
_STOP_FACTOR = 1 - STOP_PERCENT / 100


@dataclass(frozen=True)
class WatchState:
    """One watch row's content (everything except the bookkeeping columns: last_updated_at, removed_at, as_of).
    All times are naive America/New_York candle window starts, as the chart draws them."""

    profile: str
    latest_arrow_kind: str  # one of SIGNAL_KINDS: the latest arrow applied to the row, either direction
    latest_arrow_at: datetime
    instruction_type: int  # ToS numbering (instructions.py); never 100 (a breach keeps the last instruction)
    entry_kind: str | None  # "blue" | "yellow" | None (a row born from a Gray Up has no entry)
    entry_at: datetime | None
    entry_price: float | None  # close of the entry arrow's candle
    stop_price: float | None
    stop_basis: str  # "10%" | "LP" | "entry" | "none"
    status: str  # "active" | "breached"
    breached_at: datetime | None
    last_signal_at: datetime  # the latest UP arrow's candle (Blue, Yellow or Gray, type 4 included)

    @property
    def instruction_text(self) -> str:
        return text_for(self.instruction_type, self.profile)


LpSecond = Callable[[int], float | None]  # candle position -> the 2nd LP below that candle's close, or None


def _up_kind(kinds: Collection[str]) -> str | None:
    for kind in ("blue_up", "yellow_up", "gray_up"):
        if kind in kinds:
            return kind
    return None


def _down_kind(kinds: Collection[str]) -> str | None:
    for kind in ("yellow_down", "blue_down", "gray_down"):
        if kind in kinds:
            return kind
    return None


def _apply_up(
    state: WatchState | None,
    kind: str,
    first_yellow: bool,
    profile: str,
    ts: datetime,
    pos: int,
    low: float,
    close: float,
    lp_second: LpSecond,
) -> WatchState:
    if kind == "blue_up":
        return WatchState(profile, kind, ts, BLUE_UP, ENTRY_BLUE, ts, close, None, BASIS_NONE, STATUS_ACTIVE, None, ts)

    if kind == "yellow_up":
        fresh = state is None or state.status == STATUS_BREACHED or state.entry_kind is None
        if first_yellow and not fresh:
            return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts)  # type 4: no action
        ten_pct = low * _STOP_FACTOR
        if fresh:
            return WatchState(profile, kind, ts, YELLOW_UP, ENTRY_YELLOW, ts, close, ten_pct, BASIS_PCT, STATUS_ACTIVE, None, ts)
        lp = lp_second(pos)
        stop, basis = (lp, BASIS_LP) if lp is not None and lp < ten_pct else (ten_pct, BASIS_PCT)
        return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts, instruction_type=YELLOW_UP, stop_price=stop, stop_basis=basis)

    # gray_up (type 1): no action on a row; a new row has no entry and no stop.
    if state is None:
        return WatchState(profile, kind, ts, GRAY_UP, None, None, None, None, BASIS_NONE, STATUS_ACTIVE, None, ts)
    return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts)


def _apply_down(state: WatchState, kind: str, ts: datetime, pos: int, lp_second: LpSecond) -> WatchState:
    itype = {"yellow_down": YELLOW_DOWN, "blue_down": BLUE_DOWN, "gray_down": GRAY_DOWN}[kind]
    moved = replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, instruction_type=itype)
    if state.status != STATUS_ACTIVE or state.entry_kind is None:
        return moved  # nothing to tighten on a breached row or one with no entry
    if kind == "gray_down":
        if state.entry_kind == ENTRY_YELLOW and state.entry_price is not None:
            return replace(moved, stop_price=state.entry_price, stop_basis=BASIS_ENTRY)
        return moved
    if kind == "yellow_down" and state.entry_kind != ENTRY_YELLOW:
        return moved
    lp = lp_second(pos)
    return replace(moved, stop_price=lp, stop_basis=BASIS_LP) if lp is not None else moved


def advance(
    state: WatchState | None,
    candles: pd.DataFrame,
    events: Sequence[WarrenSignalEvent],
    first_yellow_after_blue_at: Collection[datetime],
    profile: str,
    after: datetime | None,
    lp_second: LpSecond,
) -> WatchState | None:
    """Fold the candles stamped after `after` (all of them when None) into `state` (None = no row). `candles` needs
    low and close columns and a naive DatetimeIndex; `events` carry fired_at stamps from that same index. Returns the
    state after the last candle (None if no up arrow has created a row)."""
    arrows: dict[datetime, set[str]] = defaultdict(set)
    for e in events:
        arrows[e.fired_at].add(e.kind)
    first_yellows = set(first_yellow_after_blue_at)

    index = candles.index
    lows = candles["low"].to_numpy()
    closes = candles["close"].to_numpy()
    start = 0 if after is None else int(index.searchsorted(pd.Timestamp(after), side="right"))
    for pos in range(start, len(index)):
        ts = index[pos].to_pydatetime()
        if state is not None and state.status == STATUS_ACTIVE and state.stop_price is not None and lows[pos] <= state.stop_price:
            state = replace(state, status=STATUS_BREACHED, breached_at=ts)
        kinds = arrows.get(ts)
        if not kinds:
            continue
        up = _up_kind(kinds)
        if up is not None:
            # Type 4 = the Yellow Up that is the first since the last Blue (a same-candle Blue already took precedence).
            state = _apply_up(state, up, up == "yellow_up" and ts in first_yellows, profile, ts, pos, float(lows[pos]), float(closes[pos]), lp_second)
        down = _down_kind(kinds)
        if down is not None and state is not None:
            state = _apply_down(state, down, ts, pos, lp_second)
    return state
