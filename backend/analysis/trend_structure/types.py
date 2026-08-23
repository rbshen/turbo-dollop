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
SmaCross = Literal["up", "down"]

# The ratio (margin/ATR) threshold for a "confirmed" swing -- shared between
# state_machine.py (a genuine trend_state flip) and classification.py (which
# LL swings are eligible to build the A/D Bullish Divergence trailing-3
# floor). Lives here, not in either of those two files, since state_machine
# imports FROM classification -- classification importing the constant back
# from state_machine would be circular.
CONFIRMED_RATIO = 1.0


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
    # A/D Bullish Divergence -- see classification.py's own docstring for the
    # full matching/comparison definition. True only for the ticker's MOST
    # RECENT confirmed LL swing; ad_divergence_swing_date is the matched
    # Chaikin Oscillator low's own bar date (None whenever the flag is False).
    ad_bullish_divergence: bool
    ad_divergence_swing_date: date | None
    # SMA (20/50/200) position tracking -- (close - SMA)/SMA*100 for the
    # latest bar, plus a prior-day-vs-current-day cross flag. See
    # sma_position.py::compute_sma_position for the full definition
    # (including why crossing compares prior-day SMA, not today's SMA
    # reused). None (both fields) whenever fewer than the SMA's own window
    # of bars exist yet; cross alone is None whenever there's no valid prior
    # bar to compare against, even if position_pct itself is real.
    sma20_position_pct: float | None
    sma20_cross: SmaCross | None
    sma50_position_pct: float | None
    sma50_cross: SmaCross | None
    sma200_position_pct: float | None
    sma200_cross: SmaCross | None
