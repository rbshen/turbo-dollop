"""The instruction text the Technical Ideas table shows (docs/specs/warren-signals-page.md, "Instruction texts", 2026-10-19). Pure.

Display only, derived at read time from fields the row already stores: nothing here is written, and the stored `instruction_text` column (the
chart's wording, `instructions.text_for`) is left as the nightly job wrote it. The chart's own texts (`instructions.GENERIC_TEXTS` /
`PROFILED_TEXTS`) are not touched.

Two sets. The generic set (every ticker except SPY/QQQ/TQQQ/TECL) says what the row did: a new entry, or a stop raised / unchanged. "Raised" is
read from the stop age: the stop counts as raised when `stop_moved_at` is the candle of the latest arrow and `stop_moved_by` is the mover that
arrow's rule stamps. The profiled set keeps its short, arrow-type-only wording, with two corrections (Gray Down, repeat Yellow Up)."""

from datetime import datetime

from .instructions import (
    BLUE_DOWN,
    BLUE_UP,
    BLUE_UP_IN_TRADE,
    FIRST_YELLOW_UP,
    GENERIC_TEXTS,
    GRAY_DOWN,
    GRAY_UP,
    PROFILED_TEXTS,
    WATCH_ONLY_TEXTS,
    YELLOW_DOWN,
    YELLOW_UP,
    text_for,
)
from .types import ANY_TICKER
from .watch import (
    ENTRY_BLUE,
    ENTRY_GRAY,
    GRAY_DOWN_ENTRY_BUFFER,
    MOVED_BLUE_DOWN,
    MOVED_GRAY_DOWN,
    MOVED_YELLOW_DOWN,
    MOVED_YELLOW_UP_ENTRY,
    MOVED_YELLOW_UP_REPEAT,
)

_BUFFER_PCT = f"{GRAY_DOWN_ENTRY_BUFFER * 100:g}%"  # "1%": built from the rule's constant, not a second copy of it

# The generic set, one string per situation.
YELLOW_UP_NEW = "YELLOW UP - New entry. Stop set 10% below the candle low."
YELLOW_UP_RAISED = "YELLOW UP (repeat) - Stop raised."
YELLOW_UP_UNCHANGED = "YELLOW UP (repeat) - Stop unchanged, the new level is not higher."
FIRST_YELLOW_UP_NO_ACTION = "FIRST YELLOW UP AFTER BLUE ENTRY - No action."
BLUE_UP_NEW = "BLUE UP - New entry, no stop."
BLUE_UP_OPEN = "BLUE UP - No change to the open trade."
GRAY_UP_NEW = "GRAY UP - New entry (stopped out twice before, SPECULATIVE). Stop 10% below the candle low."
GRAY_UP_OPEN = "GRAY UP - No change to the open trade."
BLUE_DOWN_RAISED = "BLUE DOWN - Stop raised to the 2nd LP."
BLUE_DOWN_UNCHANGED = "BLUE DOWN - Stop unchanged."
YELLOW_DOWN_RAISED = "YELLOW DOWN - Stop raised to the 2nd LP."
YELLOW_DOWN_UNCHANGED = "YELLOW DOWN - Stop unchanged."
YELLOW_DOWN_BLUE_ENTRY = "YELLOW DOWN - No action (blue entry)."
GRAY_DOWN_RAISED = f"GRAY DOWN - Stop raised to entry + {_BUFFER_PCT}."
GRAY_DOWN_UNCHANGED = "GRAY DOWN - Stop unchanged."
GRAY_DOWN_BLUE_ENTRY = "GRAY DOWN - No action (blue entry)."

# The profiled set (SPY, QQQ, TQQQ, TECL): the chart's shortened wording, arrow type only, with the two statements the 2026-10-19 rules made false
# corrected: a Gray Down sets the stop to entry + 1% (was "entry"); a repeat Yellow Up never lowers the stop.
PROFILED_WATCH_TEXTS = {
    **PROFILED_TEXTS,
    GRAY_DOWN: f"GRAY DOWN: yellow entry = stop to entry + {_BUFFER_PCT}; blue entry = no action",
    YELLOW_UP: PROFILED_TEXTS[YELLOW_UP] + "; the stop is never lowered below the current stop",
}


def _stop_moved_by_arrow(latest_arrow_at: datetime, stop_moved_at: datetime | None, stop_moved_by: str | None, movers: tuple[str, ...]) -> bool:
    """True when the latest arrow's candle is the candle the stop last changed on, and the mover is that arrow's own rule. A trail that moved the
    stop on the same candle (the arrow itself not) stamps `trail`, so it reads as unchanged."""
    return stop_moved_at is not None and stop_moved_at == latest_arrow_at and stop_moved_by in movers


def watch_instruction_text(
    profile: str,
    instruction_type: int,
    latest_arrow_at: datetime,
    entry_kind: str | None,
    entry_at: datetime | None,
    stop_moved_at: datetime | None,
    stop_moved_by: str | None,
) -> str:
    """The text for one row. A situation the stored fields cannot place (no entry on an up arrow that implies one) falls back to the chart's text
    for the type, so a row always gets a string."""
    if profile != ANY_TICKER.name:
        return WATCH_ONLY_TEXTS[instruction_type] if instruction_type in WATCH_ONLY_TEXTS else PROFILED_WATCH_TEXTS.get(instruction_type, text_for(instruction_type, profile))

    def raised(*movers: str) -> bool:
        return _stop_moved_by_arrow(latest_arrow_at, stop_moved_at, stop_moved_by, movers)

    new_entry = entry_at is not None and entry_at == latest_arrow_at  # the arrow opened the trade (every fresh entry stamps its own candle)
    if instruction_type == YELLOW_UP:
        if new_entry:
            return YELLOW_UP_NEW
        # A repeat Yellow stamps yellow_up_repeat; yellow_up_entry is accepted too. The stored fields cannot tell a blue entry's FIRST stop from a
        # later raise (the old stop is not stored), so both read "Stop raised" -- true of either.
        return YELLOW_UP_RAISED if raised(MOVED_YELLOW_UP_REPEAT, MOVED_YELLOW_UP_ENTRY) else YELLOW_UP_UNCHANGED
    if instruction_type == FIRST_YELLOW_UP:
        return FIRST_YELLOW_UP_NO_ACTION
    if instruction_type in (BLUE_UP, BLUE_UP_IN_TRADE):
        return BLUE_UP_NEW if instruction_type == BLUE_UP and new_entry else BLUE_UP_OPEN
    if instruction_type == GRAY_UP:
        if new_entry and entry_kind == ENTRY_GRAY:
            return GRAY_UP_NEW
        return GRAY_UP_OPEN if entry_kind is not None else GENERIC_TEXTS[GRAY_UP]  # no entry recorded (a legacy row): the chart's text
    blue_entry = entry_kind == ENTRY_BLUE
    if instruction_type == BLUE_DOWN:
        return BLUE_DOWN_RAISED if raised(MOVED_BLUE_DOWN) else BLUE_DOWN_UNCHANGED
    if instruction_type == YELLOW_DOWN:
        if blue_entry:
            return YELLOW_DOWN_BLUE_ENTRY
        return YELLOW_DOWN_RAISED if raised(MOVED_YELLOW_DOWN) else YELLOW_DOWN_UNCHANGED
    if instruction_type == GRAY_DOWN:
        if blue_entry:
            return GRAY_DOWN_BLUE_ENTRY
        return GRAY_DOWN_RAISED if raised(MOVED_GRAY_DOWN) else GRAY_DOWN_UNCHANGED
    return text_for(instruction_type, profile)
