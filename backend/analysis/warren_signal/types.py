"""Shared dataclasses for the Warren RSI/ADX/WVF engine (see state_machine.py)
-- mirrors analysis/entry_signal/types.py's dataclass-based style for
structured returns.
"""

from dataclasses import dataclass
from datetime import datetime

# Every buy/sell arrow this engine can fire. Up-kinds are buy-side
# (scanOverSold3/scanOverSold4-derived), Down-kinds are sell-side
# (bear1/wvf+rsiOverbought/rsi84.75/rsiOverbought-derived). Order here has
# no semantic meaning -- membership is what matters (see
# state_machine.py::UP_KINDS).
SIGNAL_KINDS = ("blue_up", "yellow_up", "gray_up", "blue_down", "yellow_down", "gray_down")


@dataclass(frozen=True)
class WarrenSignalEvent:
    """One fired arrow. `stop_price` is the LIVE yellowStopPrice as of this
    bar (see state_machine.py's own module docstring for why this can differ
    from "the stop this specific event set") -- may be None if no yellow/gray
    entry has ever been held yet."""

    kind: str  # one of SIGNAL_KINDS
    fired_at: datetime
    close: float
    rsi: float | None
    stop_price: float | None


@dataclass(frozen=True)
class WarrenReplayResult:
    """One full nightly replay's outcome for a ticker -- NOT incremental
    state (see state_machine.py's own docstring): every field here is
    recomputed from scratch every run, from the full available history.

    events: every arrow that fired anywhere in the given history, in
    chronological order (oldest first) -- unlike TechnicalEntrySignal's own
    "latest fire only" semantics, this is the complete list; the caller
    (data/warren_signal_data.py) is responsible for both storing the full
    list (into WarrenSignalEvent) and deriving "latest state" from its tail.

    as_of: the last candle actually evaluated this run, regardless of
    whether anything fired on it.

    gray_suppressed/stop_count/live_stop_price: the state machine's own
    internal state AS OF THE LAST REPLAYED BAR -- i.e. the standing
    "current" reference for the next signal, independent of which bar the
    latest EVENT in `events` happens to have landed on. gray_suppressed
    mirrors yellowIsGray; stop_count mirrors stopCount; live_stop_price
    mirrors yellowStopPrice (None if no yellow/gray entry has ever been
    held)."""

    as_of: datetime
    events: list[WarrenSignalEvent]
    gray_suppressed: bool
    stop_count: int
    live_stop_price: float | None
