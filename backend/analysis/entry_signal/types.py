"""Shared dataclasses for the entry-signal engine (see engine.py) --
mirrors analysis/trend_structure/types.py's dataclass-based style for
structured returns.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EntrySignalResult:
    """One nightly scan's outcome for a ticker -- NOT just "the latest
    candle's own reading" (see engine.py::compute_entry_signal for why).

    as_of: the last candle actually evaluated this run, fired or not --
    always real once there's any history at all.

    fired: whether ANY candle evaluated this run (today's session
    candles) satisfied check_buy_signal.

    fired_at/pct_b/rsi/close/stop_price: the LATEST firing candle's own
    values -- all five are None together when `fired` is False. These are
    NOT "the current candle's reading" the way they were before this type
    grew fired_at/stop_price -- they describe whichever bar actually fired,
    which may not be the same bar as-of.
    """

    as_of: datetime
    fired: bool
    fired_at: datetime | None
    pct_b: float | None
    rsi: float | None
    close: float | None
    stop_price: float | None
