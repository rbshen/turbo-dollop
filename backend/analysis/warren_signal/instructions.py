"""The Warren action-text note shown on the Chart tab's 2H·90D range: which instruction applies to the latest
signal, and whether it has expired. Pure -- it reads a WarrenReplayResult and the replayed candle times, nothing
else.

Ported from the ToS `instructionType` chain (rp_RSI_WVF_*STUDY.ts, "INSTRUCTION EVENT TRACKER"), with two
deliberate deviations (docs/decisions.md 2026-10-06):

1. Type 4 ("first yellow up after blue") is shown on the first-yellow ARROW bar itself, replacing type 3 there. ToS
   evaluates it from a state flag on the bars AFTER the arrow (one bar late) and re-asserts it over later down-arrow
   text. Here it is never late and never overwrites anything.
2. A stop hit (type 100) restarts the countdown. ToS's own instructionBar ignores stop hits, so its text expires
   10 bars after the last arrow even if a stop hit fired later.

Age is counted in positions of the completed 2h candle series, as ToS BarNumber does: the signal bar has age 0 and the
text is visible while age <= INSTRUCTION_MAX_AGE_BARS (30), gone from age 31. Each signal (any of the six arrows, a
stop hit, or type 4) replaces the current text and restarts the countdown.

Two text sets: the shortened "profiled" set for SPY/QQQ/TQQQ/TECL, and the "generic" set (the Any-Ticker ToS wording
verbatim, except type 4) for every other ticker. Both entry branches (yellow entry / blue entry) stay in the string:
the engine keeps no entry-type state."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .types import ANY_TICKER, WarrenReplayResult

INSTRUCTION_MAX_AGE_BARS = 30

# Instruction types, ToS numbering.
STOP_HIT = 100
GRAY_DOWN = 30
YELLOW_DOWN = 20
BLUE_DOWN = 10
FIRST_YELLOW_UP = 4
YELLOW_UP = 3
BLUE_UP = 2
GRAY_UP = 1

TYPE_KIND = {
    STOP_HIT: "stop_hit",
    GRAY_DOWN: "gray_down",
    YELLOW_DOWN: "yellow_down",
    BLUE_DOWN: "blue_down",
    FIRST_YELLOW_UP: "first_yellow_up",
    YELLOW_UP: "yellow_up",
    BLUE_UP: "blue_up",
    GRAY_UP: "gray_up",
}

# Tone per type (ToS colours): 100 red, 30/1 gray, 20/4/3 yellow, 10/2 blue.
TYPE_TONE = {
    STOP_HIT: "red",
    GRAY_DOWN: "gray",
    YELLOW_DOWN: "yellow",
    BLUE_DOWN: "blue",
    FIRST_YELLOW_UP: "yellow",
    YELLOW_UP: "yellow",
    BLUE_UP: "blue",
    GRAY_UP: "gray",
}

_STOP_HIT_TEXT = "STOP HIT = EXIT OR RESET"

PROFILED_TEXTS = {
    STOP_HIT: _STOP_HIT_TEXT,
    GRAY_DOWN: "GRAY DOWN: yellow entry = stop to entry; blue entry = no action",
    YELLOW_DOWN: "YELLOW DOWN: yellow entry = stop to 2nd LP; blue entry = no action",
    BLUE_DOWN: "BLUE DOWN = stop to 2nd LP",
    FIRST_YELLOW_UP: "FIRST YELLOW UP AFTER BLUE = NO ACTION",
    YELLOW_UP: "YELLOW UP: new entry = 10% stop; already in trade = stop to 2nd LP or 10% below candle low, whichever is lower",
    BLUE_UP: "BLUE UP = ENTRY, NO STOP",
    GRAY_UP: "GRAY UP = NO ACTION (stopped out twice); stay out until BLUE UP",
}

# The Any-Ticker ToS strings verbatim; only type 4 differs (the profiled meaning, "no action", is authoritative).
GENERIC_TEXTS = {
    STOP_HIT: _STOP_HIT_TEXT,
    GRAY_DOWN: "GRAY DOWN - Adjust stop accordingly.",
    YELLOW_DOWN: "YELLOW DOWN - Adjust stop accordingly.",
    BLUE_DOWN: "BLUE DOWN - Adjust stop accordingly.",
    FIRST_YELLOW_UP: "FIRST YELLOW UP ARROW AFTER BLUE ENTRY - NO ACTION",
    YELLOW_UP: "YELLOW UP INITIAL ENTRY - Use appropriate stop.",
    BLUE_UP: "BLUE UP - Use appropriate stop.",
    GRAY_UP: "GRAY UP - NO ACTION. Stopped out twice.",
}


def text_for(instruction_type: int, profile_name: str) -> str:
    """The wording for one type: the shortened set for every named per-ticker profile, the generic set for the
    ANY-TICKER profile."""
    return (GENERIC_TEXTS if profile_name == ANY_TICKER.name else PROFILED_TEXTS)[instruction_type]


def instruction_type_for_bar(
    *, stop_hit: bool, yellow_down: bool, blue_down: bool, gray_down: bool, yellow_up: bool, first_yellow_up: bool, blue_up: bool, gray_up: bool
) -> int | None:
    """The ToS priority chain for ONE bar: stop hit, then yellow-down, blue-down, gray-down, then yellow-up (type 4
    instead of 3 on a first-yellow-after-blue arrow bar), blue-up, gray-up. None when nothing fired."""
    if stop_hit:
        return STOP_HIT
    if yellow_down:
        return YELLOW_DOWN
    if blue_down:
        return BLUE_DOWN
    if gray_down:
        return GRAY_DOWN
    if yellow_up:
        return FIRST_YELLOW_UP if first_yellow_up else YELLOW_UP
    if blue_up:
        return BLUE_UP
    if gray_up:
        return GRAY_UP
    return None


@dataclass(frozen=True)
class WarrenInstruction:
    """The current action text. `time` is the signal candle's timestamp; `bars_since` its age (0 = the latest
    completed candle); `bars_left` how many more candles it stays visible (0 on its last visible candle)."""

    type: int
    kind: str
    text: str
    tone: str
    time: datetime
    bars_since: int
    bars_left: int


def current_instruction(
    result: WarrenReplayResult, candle_times: Sequence[datetime], profile_name: str = ANY_TICKER.name
) -> WarrenInstruction | None:
    """The instruction in force after the last candle of `candle_times` (the completed 2h series the replay ran
    over, forming candle already dropped), or None when there has been no signal or the latest one has expired
    (age > INSTRUCTION_MAX_AGE_BARS). `result` must come from a replay of exactly those candles."""
    if not candle_times:
        return None
    kinds_by_time: dict[datetime, set[str]] = {}
    for e in result.events:
        kinds_by_time.setdefault(e.fired_at, set()).add(e.kind)
    stop_hits = set(result.stop_hit_at)
    first_yellows = set(result.first_yellow_after_blue_at)

    n = len(candle_times)
    # Only the last INSTRUCTION_MAX_AGE_BARS + 1 candles can carry a live text; scan newest first.
    for age in range(min(n, INSTRUCTION_MAX_AGE_BARS + 1)):
        t = candle_times[n - 1 - age]
        kinds = kinds_by_time.get(t, set())
        itype = instruction_type_for_bar(
            stop_hit=t in stop_hits,
            yellow_down="yellow_down" in kinds,
            blue_down="blue_down" in kinds,
            gray_down="gray_down" in kinds,
            yellow_up="yellow_up" in kinds,
            first_yellow_up=t in first_yellows,
            blue_up="blue_up" in kinds,
            gray_up="gray_up" in kinds,
        )
        if itype is not None:
            return WarrenInstruction(
                type=itype,
                kind=TYPE_KIND[itype],
                text=text_for(itype, profile_name),
                tone=TYPE_TONE[itype],
                time=t,
                bars_since=age,
                bars_left=INSTRUCTION_MAX_AGE_BARS - age,
            )
    return None
