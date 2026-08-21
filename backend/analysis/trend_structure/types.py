"""Shared dataclasses for the trend-structure engine (see engine.py) --
mirrors analysis/ma_magnet's dataclass-based style for structured returns.
See CLAUDE.md's "Trend structure analysis (Technical)" section for the full
methodology these types represent.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

SwingKind = Literal["high", "low"]
TrendState = Literal["uptrend", "downtrend"]
MagnitudeTier = Literal["weak", "confirmed", "strong"]
Regime = Literal["trending", "range-bound"]
Classification = Literal["HH", "HL", "LH", "LL"]


@dataclass(frozen=True)
class SwingPoint:
    """A single fractal swing high or low, before classification."""

    date: date
    price: float
    kind: SwingKind


@dataclass(frozen=True)
class SwingDetail:
    """A classified swing's full detail -- used for both
    last_confirmed_swing and warning_swing in TrendStructureResult."""

    date: date
    price: float
    margin: float
    atr: float
    ratio: float


@dataclass(frozen=True)
class TrendStructureResult:
    trend_state: TrendState
    # None only when the swing history is too thin to have ever produced a
    # weak-confirmed-or-stronger swing yet (see state_machine.py) -- not a
    # case the spec enumerates, but one a short/thin real history can hit.
    magnitude_tier: MagnitudeTier | None
    persistence_count: int
    bars_since_confirmation: int | None
    last_confirmed_swing: SwingDetail | None
    warning_flag: bool
    warning_swing: SwingDetail | None
    efficiency_ratio: float | None
    regime: Regime | None
    blended_score: float
    bar_level: int
