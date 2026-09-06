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
WeinsteinStage = Literal["base", "advance", "top", "decline"]

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
    # HH/HL/LH/LL -- added for the Technical tab's Reversal/Trend
    # Continuation checklists (2026-09-06), which need to know WHICH kind of
    # swing last_confirmed_swing/warning_swing actually is, not just its
    # ratio/magnitude. Always populated for a freshly computed swing (every
    # ClassifiedSwing carries a classification); SwingDetailOut's own copy
    # of this field is nullable purely for the pre-existing-row migration
    # safety reason documented there.
    classification: Classification


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


@dataclass(frozen=True)
class WeinsteinStageResult:
    """Stan Weinstein's classic 4-stage (Base/Advance/Top/Decline) reading,
    computed on WEEKLY bars (see weinstein.py) -- a fully independent second
    lens from the daily-bar swing/BOS engine above (TrendStructureResult),
    not merged into it, since it needs an extra benchmark series and
    operates on a different (weekly, resampled) timeframe entirely. See
    weinstein.py's own module docstring for the full mechanism.

    stage is None (and every other field None/False) only when there's too
    little daily history to produce even MIN_WEEKS_REQUIRED weekly bars yet
    (e.g. a recent IPO) -- mirrors sma_position.py's graceful-degradation
    convention, never an exception.
    """

    stage: WeinsteinStage | None
    # UNLIKE every other field on this dataclass, always a real int, even
    # when stage is None -- "how many weekly bars WERE available" is exactly
    # the point of this field, populated in both the thin-history
    # early-return and the full-compute path. Lets a caller distinguish
    # "never computed at all" (a persisted row where this column itself is
    # NULL -- see models.py::TrendAnalysis's own comment) from "a real
    # compute ran and genuinely found fewer than MIN_WEEKS_REQUIRED weeks"
    # (this field holds that real, sub-threshold count) -- found necessary
    # after a real incident where a stale, never-reprocessed row's NULL
    # stage was indistinguishable in the UI from a genuine data gap.
    weeks_available: int
    # The first week of the CURRENT stage, walked back from the latest
    # available week. stage_since_is_lower_bound=True means the stage never
    # differed anywhere in the available (post-bootstrap) history -- the
    # true start predates the fetch window, so this date is a lower bound,
    # not a precise transition date. Always False when stage is None too.
    stage_since_date: date | None
    stage_since_is_lower_bound: bool
    ma_slope_pct: float | None
    vs_ma_pct: float | None
    volume_ratio: float | None
    mansfield_rs: float | None
    # A single-run, week-over-week read straight off the just-computed
    # weekly stage series (mirrors the Pine source's own `breakout` plot):
    # true only when the latest week just transitioned INTO "advance" with
    # both volume and relative-strength confirmation. Deliberately NOT the
    # same concept as TrendAnalysis.weinstein_stage_changed (an
    # across-nightly-runs comparison computed in the DB-aware orchestration
    # layer, see data/trend_analysis_data.py) -- always a real bool, never
    # None, even when stage is None (reads False).
    breakout_confirmed: bool
