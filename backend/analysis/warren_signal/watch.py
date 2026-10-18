"""The Warren Signals watch table's update rules (docs/specs/warren-signals-page.md). Pure -- no DB, no FMP.

A watch row is a per-ticker note about the latest Warren arrows: what the on-chart instruction says, the entry the
current row state started from, and the stop that instruction implies. `advance` walks 2h candles oldest to newest,
applies each candle's arrows to the row (or creates it), and checks the stop against each candle's low. The arrows
themselves come from the existing replay (state_machine.py), unchanged: this module only reads them.

Rules, per candle (the stop in force BEFORE the candle's arrows is the one its low is tested against, so a stop set
on candle t is first tested on t+1, as the ThinkScript's `rawStopHit` needs `barsSinceYellow > 0`):

1. Breach: row active, a stop exists, low <= stop -> status "breached", breached_at = this candle; the stop and the
   last instruction are kept. A row with no stop cannot breach.
2. Up arrows (one per candle; Blue beats Yellow beats Gray, as the ThinkScript resets its yellow count on a Blue). On a
   BREACHED row every up arrow restarts the row as a new entry (Blue, Yellow, Gray):
   - Blue Up (type 2): no row, a breached row, or a row with no entry -> entry kind blue, entry = this candle's close, no stop,
     active (clears a breach). On an ACTIVE row with an entry it is not an action (2026-10-17): entry price, date and kind, stop,
     basis and status stay; only the latest arrow, the instruction (BLUE_UP_IN_TRADE, "BLUE UP - no change to an open trade") and
     last signal move. It still resets the first-Yellow-after-Blue counter, which lives in the arrow replay, so the next Yellow Up
     is type 4 (no action) and the one after it acts.
   - Yellow Up (type 3): fresh entry (no row, breached row, or a row that never had an entry) -> entry kind yellow,
     stop = 0.9 x this candle's low, basis "10%". On an active row with an entry -> stop = min(2nd LP, 0.9 x low),
     basis whichever is lower ("10%" on a tie, or when there is no 2nd LP); the entry is unchanged.
   - Gray Up (type 1), no open trade (no row, a breached row, or a row with no entry): a fresh GRAY entry (2026-10-17): entry kind
     gray, entry = this candle's close, stop = 0.9 x this candle's low, basis "10%". On an active row with an entry: no action,
     only the pill, the instruction (Gray Up, type 1) and the dates move.
   - Yellow Up that is the first after a Blue (type 4): no action on an existing active row, only the pill, the instruction (type 4) and the dates
     move; with no row it is treated as a fresh yellow entry. A Yellow Up on an active gray-entry row is a repeat Yellow
     (stop only; the gray entry is never replaced).
3. Down arrows (one per candle; Yellow Down beats Blue Down beats Gray Down, the ThinkScript's text order) apply only
   to an existing ACTIVE row; on a BREACHED row they are ignored entirely (2026-10-17: nothing changes, not even the latest
   arrow). On an active row the instruction text and the latest arrow update; the stop changes only on a row with an entry, and
   a down arrow is RAISE-ONLY (a floor, never a cut; 2026-10-17): Blue Down -> stop = max(current stop, 2nd LP) (no stop yet ->
   the 2nd LP); Yellow Down -> the same if the entry kind is yellow or gray (a blue entry: no action); Gray Down -> stop =
   max(current stop, entry price) if the entry kind is yellow or gray AND the entry price is BELOW the Gray Down candle's close
   (an entry at or above the close would put the stop above the market and breach on the next candle, so the row is left as it
   is, text only). When the new level is not higher there is no change at all: no stop move, no stop-age update, basis unchanged.
   The ThinkScript computes no stop for a Gray Down; this is a rule on the instruction text only. A blue entry takes no stop from
   a Gray Down ("GRAY DOWN on BLUE ENTRY = No Action" in the scripts). The armed repeat Yellow Up (rule 2) is the ONLY rule that
   can lower a stop.

4. Trailing (2026-10-16): after a candle's arrows, an ACTIVE row whose stop basis is LP asks for the 2nd LP as of that candle
   and, if it is higher than the stop, raises the stop to it (basis stays LP). It never lowers a stop and never touches a
   10% or entry stop. It runs on every candle, arrow or not, and the breach test always uses the stop as it stood BEFORE
   the candle.

Instruction text (2026-10-17): the instruction type always follows the arrow in the pill (Blue Up 2 / 5 in an open trade, Yellow Up 3 / 4
for a first Yellow after a Blue, Gray Up 1, Yellow Down 20, Blue Down 10, Gray Down 30); a breached row ignores a down arrow, pill and text together.

Stop age: `stop_moved_at` / `stop_moved_by` record the candle and the rule that last changed the stop VALUE (fresh entry,
repeat Yellow, Blue Down, Yellow Down, Gray Down, trail); re-setting the same value is not a move, and a stop that becomes
none (a Blue Up) clears both.

2nd LP = the SELECTED support below the close of the arrow candle (`lp_second`, supplied by the caller and called only where a rule
above needs it). Since 2026-10-18 (`WatchRules.lp_atr_gate`) the selection has an eligibility gate, `pick_support`: the 2nd-nearest
support is used only if it sits at least one daily ATR(14) below the candle close (`support <= close - 1.0 x ATR`); if it is too close
the walk goes down the kept supports (the 3rd; at most 3 are kept) and takes the first eligible one; the 1st is never used; if none is
eligible the selection is None, which every rule above already handles (Yellow Down, Blue Down and trailing leave the stop alone; the
repeat Yellow falls back to 0.9 x low). The daily ATR is the last COMPLETED session strictly before the candle's date; where it is
unavailable the gate is off for that use (the plain 2nd LP). One definition serves all four uses."""

from collections import defaultdict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime

import pandas as pd

from .instructions import (
    BLUE_DOWN,
    BLUE_UP,
    BLUE_UP_IN_TRADE,
    FIRST_YELLOW_UP,
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
ENTRY_GRAY = "gray"  # a Gray Up that opened a trade (2026-10-17): "two stop-outs in a row, higher risk"

# What last moved a stop (WatchState.stop_moved_by).
MOVED_YELLOW_UP_ENTRY = "yellow_up_entry"
MOVED_YELLOW_UP_REPEAT = "yellow_up_repeat"
MOVED_BLUE_DOWN = "blue_down"
MOVED_YELLOW_DOWN = "yellow_down"
MOVED_GRAY_DOWN = "gray_down"
MOVED_TRAIL = "trail"
MOVED_GRAY_UP_ENTRY = "gray_up_entry"
STOP_MOVED_BY = (
    MOVED_YELLOW_UP_ENTRY, MOVED_YELLOW_UP_REPEAT, MOVED_BLUE_DOWN, MOVED_YELLOW_DOWN, MOVED_GRAY_DOWN, MOVED_TRAIL,
    MOVED_GRAY_UP_ENTRY,
)


def stop_trailed_since_arrow(
    status: str, stop_price: float | None, stop_basis: str, stop_moved_by: str | None, stop_moved_at: datetime | None, latest_arrow_at: datetime
) -> bool:
    """Display flag (the Technical Ideas "LP" pill turns yellow): an ACTIVE row whose last stop move was a trail and no arrow has been
    recorded since. Same candle counts (the arrow is processed first, then the trail). Any later arrow clears it, including one that left the
    stop unchanged (Blue Up on an open trade, Gray Up on an active row, a no-op down arrow). Both stamps are candle window starts (naive ET)
    from the same candle index. False on a breached row, with no stop or no stop age, and for every basis other than LP."""
    return (
        status == STATUS_ACTIVE
        and stop_price is not None
        and stop_basis == BASIS_LP
        and stop_moved_by == MOVED_TRAIL
        and stop_moved_at is not None
        and latest_arrow_at <= stop_moved_at
    )


# The 10% stop is `yellowEntryHeld * (1 - stopPercent / 100)` in the ThinkScript.
_STOP_FACTOR = 1 - STOP_PERCENT / 100


@dataclass(frozen=True)
class WatchRules:
    """Switches for the arrow rules that changed on 2026-10-17, so the rebuild script can replay the PREVIOUS rules (its mismatch
    guard) and attribute a difference to one change. The defaults are the current rules."""

    gray_entry: bool = True  # a Gray Up with no open trade opens a gray entry
    ignore_breached_downs: bool = True  # a down arrow does nothing on a breached row
    gray_up_freezes_breached: bool = False  # the oldest rule: a Gray Up on a breached row moved only the latest arrow
    gray_down_raise_only: bool = True  # a Gray Down never lowers a stop (stop = max(stop, entry)); False = it set the stop to the entry price
    blue_up_in_trade_no_op: bool = True  # a Blue Up on an active row with an entry changes nothing about the trade; False = it replaced the entry (gray entries excepted)
    down_arrows_raise_only: bool = True  # Blue Down / Yellow Down: stop = max(stop, 2nd LP); False = the stop was set to the 2nd LP, lower or not
    text_follows_pill: bool = True  # the instruction type follows the arrow in the pill on every candle; False = a no-action up arrow (first Yellow after Blue, Gray Up on an open trade) left the old text
    lp_atr_gate: bool = True  # the selected LP must sit at least 1 x daily ATR(14) below the candle close (R1, walk down from the 2nd LP); False = the plain 2nd-nearest support


CURRENT_RULES = WatchRules()
# The rules on main before the LP gate (2026-10-18): what the stored rows were built under, so the rebuild guard replays them.
PREVIOUS_RULES = replace(CURRENT_RULES, lp_atr_gate=False)
# The rules before the raise-only down arrows / Blue Up no-op change (b19cbc4, 2026-10-17): for tests that pin that behaviour.
PRE_RAISE_ONLY_RULES = WatchRules(lp_atr_gate=False, blue_up_in_trade_no_op=False, down_arrows_raise_only=False, text_follows_pill=False)
# The rules before the Gray Down raise-only change (2026-10-17, earlier): for tests that pin that behaviour.
PRE_GRAY_RAISE_ONLY_RULES = replace(PRE_RAISE_ONLY_RULES, gray_down_raise_only=False)
# The rules before the gray-entry / breached-row change (2026-10-17, earliest): for tests that pin that behaviour.
LEGACY_RULES = WatchRules(
    gray_entry=False, ignore_breached_downs=False, gray_up_freezes_breached=True, gray_down_raise_only=False,
    blue_up_in_trade_no_op=False, down_arrows_raise_only=False, text_follows_pill=False, lp_atr_gate=False,
)

# The LP eligibility limit in daily ATRs (R1, 1 x ATR; the 2026-10-18 what-if's best family, see docs/decisions.md).
LP_GATE_ATR_MULTIPLE = 1.0


@dataclass(frozen=True)
class LpPick:
    """`pick_support`'s answer: the support the stop may use (None = none) and why: "eligible" (the 2nd LP passes), "walked" (a lower support
    passes), "none" (no kept support passes), "off" (no usable ATR: the plain 2nd LP), "short" (fewer than two supports: None, as before)."""

    value: float | None
    status: str


def pick_support(supports: Sequence[float], close: float, atr: float | None) -> LpPick:
    """The selected LP. `supports` are the kept supports below `close`, nearest first (at most 3). With a usable `atr` (finite, > 0): the 2nd
    support if it is at most `close - LP_GATE_ATR_MULTIPLE x atr` (equal is eligible), else the first lower support that is; the 1st is
    never used. Without a usable ATR the plain 2nd support."""
    if len(supports) < 2:
        return LpPick(None, "short")
    if atr is None or not atr > 0:  # unavailable (None, NaN) or degenerate
        return LpPick(float(supports[1]), "off")
    limit = close - LP_GATE_ATR_MULTIPLE * atr
    if supports[1] <= limit:
        return LpPick(float(supports[1]), "eligible")
    for support in supports[2:]:
        if support <= limit:
            return LpPick(float(support), "walked")
    return LpPick(None, "none")


@dataclass(frozen=True)
class WatchState:
    """One watch row's content (everything except the bookkeeping columns: last_updated_at, removed_at, as_of).
    All times are naive America/New_York candle window starts, as the chart draws them."""

    profile: str
    latest_arrow_kind: str  # one of SIGNAL_KINDS: the latest arrow applied to the row, either direction
    latest_arrow_at: datetime
    instruction_type: int  # ToS numbering (instructions.py); never 100 (a breach keeps the last instruction)
    entry_kind: str | None  # "blue" | "yellow" | "gray" | None (only a legacy row born from a Gray Up has no entry)
    entry_at: datetime | None
    entry_price: float | None  # close of the entry arrow's candle
    stop_price: float | None
    stop_basis: str  # "10%" | "LP" | "entry" | "none"
    status: str  # "active" | "breached"
    breached_at: datetime | None
    last_signal_at: datetime  # the latest UP arrow's candle (Blue, Yellow or Gray, type 4 included)
    stop_moved_at: datetime | None = None  # the candle that last changed the stop VALUE; None with no stop
    stop_moved_by: str | None = None  # one of STOP_MOVED_BY

    @property
    def instruction_text(self) -> str:
        return text_for(self.instruction_type, self.profile)


LpSecond = Callable[[int], float | None]  # candle position -> the 2nd LP below that candle's close, or None


def _with_stop(state: WatchState, stop: float, basis: str, ts: datetime, by: str) -> WatchState:
    """`state` with a new stop. Stamps stop_moved_at/by only when the stop VALUE changes (re-setting the same value is not a move)."""
    if state.stop_price is not None and stop == state.stop_price:
        return replace(state, stop_basis=basis)
    return replace(state, stop_price=stop, stop_basis=basis, stop_moved_at=ts, stop_moved_by=by)


def _text(rules: WatchRules, instruction_type: int) -> dict:
    """The instruction type a no-action up arrow sets: the arrow's own type, or nothing (the old text stays) under the previous rules."""
    return {"instruction_type": instruction_type} if rules.text_follows_pill else {}


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
    rules: WatchRules = CURRENT_RULES,
) -> WatchState:
    if kind == "blue_up":
        in_trade = state is not None and state.status == STATUS_ACTIVE and state.entry_kind is not None
        if rules.blue_up_in_trade_no_op and in_trade:
            # Not an action while a trade is open: entry, stop, basis and status stay; the arrow, text and dates move. (The first-Yellow-after-Blue
            # counter lives in the arrow replay, state_machine.py, and resets on every Blue regardless of the row.)
            return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts, instruction_type=BLUE_UP_IN_TRADE)
        if rules.gray_entry and state is not None and state.status == STATUS_ACTIVE and state.entry_kind == ENTRY_GRAY:
            # Previous rule: a gray trade keeps its entry and its stop for its whole life; the Blue only moves the arrow, instruction and date.
            return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts, instruction_type=BLUE_UP)
        return WatchState(profile, kind, ts, BLUE_UP, ENTRY_BLUE, ts, close, None, BASIS_NONE, STATUS_ACTIVE, None, ts)

    if kind == "yellow_up":
        fresh = state is None or state.status == STATUS_BREACHED or state.entry_kind is None
        if first_yellow and not fresh:
            # type 4: no action; the pill moves to Yellow Up and (since 2026-10-17) the text follows it ("FIRST YELLOW UP AFTER BLUE = NO ACTION")
            return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts, **_text(rules, FIRST_YELLOW_UP))
        ten_pct = low * _STOP_FACTOR
        if fresh:
            return WatchState(
                profile, kind, ts, YELLOW_UP, ENTRY_YELLOW, ts, close, ten_pct, BASIS_PCT, STATUS_ACTIVE, None, ts, ts, MOVED_YELLOW_UP_ENTRY
            )
        lp = lp_second(pos)
        stop, basis = (lp, BASIS_LP) if lp is not None and lp < ten_pct else (ten_pct, BASIS_PCT)
        moved = replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts, instruction_type=YELLOW_UP)
        return _with_stop(moved, stop, basis, ts, MOVED_YELLOW_UP_REPEAT)

    # gray_up (type 1)
    if rules.gray_entry:
        if state is None or state.status == STATUS_BREACHED or state.entry_kind is None:  # no open trade: a gray entry
            return WatchState(
                profile, kind, ts, GRAY_UP, ENTRY_GRAY, ts, close, low * _STOP_FACTOR, BASIS_PCT, STATUS_ACTIVE, None, ts, ts, MOVED_GRAY_UP_ENTRY
            )
        return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts, **_text(rules, GRAY_UP))  # an open trade: pill, text and dates only
    # Previous rule: no action on a row; a new row has no entry and no stop.
    if state is None:
        return WatchState(profile, kind, ts, GRAY_UP, None, None, None, None, BASIS_NONE, STATUS_ACTIVE, None, ts)
    if state.status == STATUS_BREACHED and rules.gray_up_freezes_breached:
        # "Stay out until Blue": the pill shows the Gray, but it is not a signal worth moving "Last signal" for.
        return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts)
    return replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, last_signal_at=ts)


def _apply_down(
    state: WatchState, kind: str, ts: datetime, pos: int, close: float, lp_second: LpSecond, rules: WatchRules = CURRENT_RULES
) -> WatchState:
    itype = {"yellow_down": YELLOW_DOWN, "blue_down": BLUE_DOWN, "gray_down": GRAY_DOWN}[kind]
    moved = replace(state, latest_arrow_kind=kind, latest_arrow_at=ts, instruction_type=itype)
    if state.status != STATUS_ACTIVE or state.entry_kind is None:
        return moved  # nothing to tighten on a breached row or one with no entry
    if kind == "gray_down":
        if state.entry_kind in (ENTRY_YELLOW, ENTRY_GRAY) and state.entry_price is not None and state.entry_price < close:
            if rules.gray_down_raise_only and state.stop_price is not None and state.stop_price >= state.entry_price:
                return moved  # already at or above the entry: a Gray Down never lowers a stop (and moves no stop age)
            return _with_stop(moved, state.entry_price, BASIS_ENTRY, ts, MOVED_GRAY_DOWN)
        return moved
    if kind == "yellow_down" and state.entry_kind not in (ENTRY_YELLOW, ENTRY_GRAY):
        return moved
    lp = lp_second(pos)
    if lp is None:
        return moved
    if rules.down_arrows_raise_only and state.stop_price is not None and lp <= state.stop_price:
        return moved  # a floor, never a cut: the 2nd LP is not higher than the stop (no stop move, no stop-age change, basis unchanged)
    return _with_stop(moved, lp, BASIS_LP, ts, MOVED_YELLOW_DOWN if kind == "yellow_down" else MOVED_BLUE_DOWN)


def _trail(state: WatchState, ts: datetime, pos: int, lp_second: LpSecond) -> tuple[WatchState, float | None]:
    """Raise an ACTIVE LP-basis stop to the 2nd LP as of this candle when that is higher. Returns the state and the old stop
    when it moved (None otherwise). LP is asked for only here, only for such a row."""
    if state.status != STATUS_ACTIVE or state.stop_basis != BASIS_LP or state.stop_price is None:
        return state, None
    lp = lp_second(pos)
    if lp is None or lp <= state.stop_price:
        return state, None
    return _with_stop(state, lp, BASIS_LP, ts, MOVED_TRAIL), state.stop_price


def advance(
    state: WatchState | None,
    candles: pd.DataFrame,
    events: Sequence[WarrenSignalEvent],
    first_yellow_after_blue_at: Collection[datetime],
    profile: str,
    after: datetime | None,
    lp_second: LpSecond,
    trail: bool = True,
    trail_log: list | None = None,
    rules: WatchRules = CURRENT_RULES,
) -> WatchState | None:
    """Fold the candles stamped after `after` (all of them when None) into `state` (None = no row). `candles` needs
    low and close columns and a naive DatetimeIndex; `events` carry fired_at stamps from that same index. Returns the
    state after the last candle (None if no up arrow has created a row). `trail=False` replays the rules without the
    trailing stop (the rebuild script's guard); `trail_log`, when given, collects (ts, old stop, new stop) per trail move; `rules`
    selects the arrow rules (CURRENT_RULES, or PREVIOUS_RULES / PRE_RAISE_ONLY_RULES / LEGACY_RULES for the rebuild's guard and tests)."""
    if not rules.lp_atr_gate:  # a gated lookup (data/warren_watch_data.py::SecondSupportLookup) carries the plain 2nd LP as `.plain`; any other callable is used as it is
        lp_second = getattr(lp_second, "plain", lp_second)
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
        if kinds:
            up = _up_kind(kinds)
            if up is not None:
                # Type 4 = the Yellow Up that is the first since the last Blue (a same-candle Blue already took precedence).
                state = _apply_up(state, up, up == "yellow_up" and ts in first_yellows, profile, ts, pos, float(lows[pos]), float(closes[pos]), lp_second, rules)
            down = _down_kind(kinds)
            # A breached row ignores down arrows completely (judged after this candle's up arrow, which may have restarted it).
            if down is not None and state is not None and not (rules.ignore_breached_downs and state.status == STATUS_BREACHED):
                state = _apply_down(state, down, ts, pos, float(closes[pos]), lp_second, rules)
        if trail and state is not None:
            state, old_stop = _trail(state, ts, pos, lp_second)
            if old_stop is not None and trail_log is not None:
                trail_log.append((ts, old_stop, state.stop_price))
    return state
