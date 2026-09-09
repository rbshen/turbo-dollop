"""Shared dataclasses for the entry-signal engine (see engine.py) --
mirrors analysis/trend_structure/types.py's dataclass-based style for
structured returns.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EntrySignalResult:
    """One signal check's outcome for the latest fully-formed candle.
    pct_b/rsi/close are None only when there weren't enough resampled
    candles yet to evaluate the check at all (see engine.py's own
    warmup guard) -- `fired` is always False in that case, never
    fabricated."""

    fired: bool
    pct_b: float | None
    rsi: float | None
    close: float | None
    as_of: datetime
