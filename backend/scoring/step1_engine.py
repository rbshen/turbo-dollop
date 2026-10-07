"""The neutral Step 1 (Financials) trend-assessment engine (docs/specs/financials.md, "The engine").

`assess_series(values, kind)` scores one metric's last 5-10 COMPLETED fiscal years (never a TTM point) from four parts: long-term
direction (a robust slope), a smooth dip penalty measured from a spike-robust peak, a check of the last completed fiscal year, and the
series kind (`dollar`: Revenue, Net Income, Operating Income, CFO, FCF, judged in fractions of the series' own median size, so scale
invariant; `ratio`: gross / operating / net margin, judged in percentage points, with a positivity ceiling). No metric name, company
type or second series enters. `classify_trend` (scoring/trend.py) is untouched: Steps 3 and 4 still use it.

Every threshold is a named constant in this one place (the "start" values of the design, chosen by prototype, not fitted).
"""

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from scoring.trend import TrendResult

DOLLAR = "dollar"
RATIO = "ratio"
KINDS = (DOLLAR, RATIO)


@dataclass(frozen=True)
class KindParams:
    """Every threshold that differs between the two series kinds. Sizes are fractions of the series' own median size (DOLLAR) or
    percentage points (RATIO)."""

    trend_full: float  # T: a trend at or above this per year scores 100
    trend_flat_score: float  # T: the score of a flat series (g = 0)
    trend_floor: float  # T: a trend at or below this per year scores TREND_FLOOR_SCORE (negative)
    label_trend: float  # +-this per year labels a series uptrend / decline (display and the Margins carve-out only)
    dip_lo: float  # a fall's excess over the typical decline starts to count as a dip here ...
    dip_hi: float  # ... and counts as a full dip (weight 1.0) here
    underwater_lo: float  # a year below the peak starts to count as "underwater" at this depth ...
    underwater_hi: float  # ... and counts as a full year here
    last_year_lo: float  # last completed fiscal year: a fresh fall starts to cut the score here ...
    last_year_hi: float  # ... and cuts it by LAST_YEAR_MAX_CUT here


DOLLAR_PARAMS = KindParams(
    trend_full=0.06,
    trend_flat_score=68.0,
    trend_floor=-0.15,
    label_trend=0.02,
    dip_lo=0.02,
    dip_hi=0.20,
    underwater_lo=0.02,
    underwater_hi=0.12,
    last_year_lo=0.10,
    last_year_hi=0.50,
)
RATIO_PARAMS = KindParams(
    trend_full=1.0,
    trend_flat_score=88.0,
    trend_floor=-3.0,
    label_trend=0.25,
    dip_lo=1.0,
    dip_hi=6.0,
    underwater_lo=1.0,
    underwater_hi=6.0,
    last_year_lo=2.0,
    last_year_hi=12.0,
)
PARAMS = {DOLLAR: DOLLAR_PARAMS, RATIO: RATIO_PARAMS}

TREND_FLOOR_SCORE = 30.0  # T at or below the floor trend, both kinds
BASE_FLOOR = 0.25  # DOLLAR: change and drawdown denominators never go below this fraction of S
DIP_WEIGHT_CAP = 3.0  # a single fall counts at most this many dips
PEAK_WINDOW = 2  # years either side of a year that decide whether it is a one-year spike
UNRESOLVED_FACTOR = 1.0  # K: how much an unrecovered dip counts beyond a recovered one
UNDERWATER_WEIGHT = 1.0  # K: weight of the years-underwater total
DISCOUNT_MAX = 80.0  # D(K) = DISCOUNT_MAX * (1 - exp(-(K / DISCOUNT_SCALE) ** DISCOUNT_POWER))
DISCOUNT_SCALE = 12.0
DISCOUNT_POWER = 1.5
LAST_YEAR_MAX_CUT = 0.6  # last completed fiscal year: the score is multiplied by 1 - cut * s
DIPS_LABEL_MIN_K = 0.25  # "_dips" is appended to the label from this burden up
# Positivity ceiling (RATIO only): a series whose latest value is at or below zero is capped at CEILING_AT_ZERO, falling linearly to
# 0 at CEILING_ZERO_LOSS points of loss. A positive latest value is not capped.
CEILING_AT_ZERO = 40.0
CEILING_ZERO_LOSS = 10.0

UPTREND, FLAT, DECLINE = "uptrend", "flat", "decline"
DIPS_SUFFIX = "_dips"
INSUFFICIENT = "insufficient_data"
ENGINE_PATTERNS = tuple(
    f"{shape}{suffix}" for shape in (UPTREND, FLAT, DECLINE) for suffix in ("", DIPS_SUFFIX)
) + (INSUFFICIENT,)


@dataclass(frozen=True)
class SeriesAssessment:
    pattern: str
    score: int
    g: float | None = None  # the long-term trend, per year, in the kind's units
    burden: float | None = None  # K, the dip burden
    ceiling: float | None = None  # the positivity ceiling C (RATIO), None when not applicable


_INSUFFICIENT = SeriesAssessment(INSUFFICIENT, 0)


def _ramp(value: float, lo: float, hi: float, top: float = 1.0) -> float:
    return float(min(max((value - lo) / (hi - lo), 0.0), top))


def _theil_sen_slope(y: np.ndarray) -> float:
    i, j = np.triu_indices(len(y), k=1)
    return float(np.median((y[j] - y[i]) / (j - i)))


def _trend(y: np.ndarray) -> float:
    """Part 1: the mean of two robust whole-window estimates, per year."""
    n = len(y)
    w = min(3, n // 2)
    drift = (float(np.median(y[-w:])) - float(np.median(y[:w]))) / (n - w)
    return (_theil_sen_slope(y) + drift) / 2


def _trend_score(g: float, p: KindParams) -> float:
    if g >= p.trend_full:
        return 100.0
    if g >= 0:
        return p.trend_flat_score + (100.0 - p.trend_flat_score) * g / p.trend_full
    if g <= p.trend_floor:
        return TREND_FLOOR_SCORE
    return p.trend_flat_score - (p.trend_flat_score - TREND_FLOOR_SCORE) * g / p.trend_floor


def _changes(y: np.ndarray, kind: str) -> np.ndarray:
    delta = np.diff(y)
    if kind == RATIO:
        return delta
    return delta / np.maximum(np.abs(y[:-1]), BASE_FLOOR)


def _peak_candidates(y: np.ndarray, lift: float) -> np.ndarray:
    """A year counts toward a peak only up to the highest of its up-to-2 neighbours each side plus one year of the series' own growth,
    so a one-year spike is clipped to its neighbours while a repeated high, a plateau and a high before a recovered dip stay peaks.
    The first and last year are never capped."""
    n = len(y)
    cand = y.copy()
    for s in range(1, n - 1):
        near = np.concatenate((y[max(0, s - PEAK_WINDOW) : s], y[s + 1 : s + 1 + PEAK_WINDOW]))
        cand[s] = min(y[s], float(near.max()) + lift)
    return cand


def _years_underwater(y: np.ndarray, cand: np.ndarray, g: float, kind: str, p: KindParams) -> float:
    n = len(y)
    total = 0.0
    if kind == RATIO:
        decay = min(0.0, g)
        for t in range(n):
            peak = max(cand[s] + decay * (t - s) for s in range(t + 1))
            total += _ramp(peak - y[t], p.underwater_lo, p.underwater_hi)
        return total
    base = max(0.0, 1.0 + min(0.0, g))
    positive = [s for s in range(n) if cand[s] > 0]
    for t in range(n):
        peaks = [cand[s] * base ** (t - s) for s in positive if s <= t]
        if not peaks:
            continue
        peak = max(peaks)
        total += _ramp((peak - y[t]) / max(abs(peak), BASE_FLOOR), p.underwater_lo, p.underwater_hi)
    return total


def assess_series_detail(values: Sequence[float], kind: str) -> SeriesAssessment:
    """`values`: finite numbers, oldest first, completed fiscal years only (the caller removes missing values). `kind` is passed in by
    the caller (never inferred from a name). Fewer than 2 points, or a DOLLAR series whose median size is 0, is `insufficient_data`."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2:
        return _INSUFFICIENT
    p = PARAMS[kind]
    if kind == DOLLAR:
        size = float(np.median(np.abs(x)))
        if size == 0:
            return _INSUFFICIENT
        y = x / size
    else:
        y = x

    g = _trend(y)
    c = _changes(y, kind)
    excess = np.maximum(0.0, -c - max(0.0, -g))  # excess[t - 1] is the excess drop into year t
    weight = np.clip((excess - p.dip_lo) / (p.dip_hi - p.dip_lo), 0.0, DIP_WEIGHT_CAP)

    cand = _peak_candidates(y, max(0.0, g))
    unresolved = np.zeros(n - 1)
    running_peak = cand[0]
    for t in range(1, n):
        if y[t] < running_peak:
            unresolved[t - 1] = 1.0 - _ramp(y[-1] - y[t], 0.0, running_peak - y[t])
        running_peak = max(running_peak, cand[t])
    burden = float(np.sum(weight * (1.0 + UNRESOLVED_FACTOR * unresolved))) + UNDERWATER_WEIGHT * _years_underwater(
        y, cand, g, kind, p
    )

    discount = DISCOUNT_MAX * (1.0 - math.exp(-((burden / DISCOUNT_SCALE) ** DISCOUNT_POWER)))
    last_cut = 1.0 - LAST_YEAR_MAX_CUT * _ramp(float(excess[-1]), p.last_year_lo, p.last_year_hi)
    raw = min(max(max(0.0, _trend_score(g, p) - discount) * last_cut, 0.0), 100.0)

    ceiling = None
    if kind == RATIO:
        ceiling = CEILING_AT_ZERO * max(0.0, 1.0 + float(x[-1]) / CEILING_ZERO_LOSS) if x[-1] <= 0 else None
        if ceiling is not None:
            raw = min(raw, ceiling)

    shape = UPTREND if g >= p.label_trend else DECLINE if g <= -p.label_trend else FLAT
    pattern = shape + (DIPS_SUFFIX if burden >= DIPS_LABEL_MIN_K else "")
    return SeriesAssessment(pattern, int(round(raw)), g, burden, ceiling)


def assess_series(values: Sequence[float], kind: str) -> TrendResult:
    """`(pattern, score 0-100)`: the engine's public result (the labels are `uptrend`, `flat`, `decline`, each with an optional `_dips`,
    plus `insufficient_data`; they never change a score)."""
    result = assess_series_detail(values, kind)
    return TrendResult(result.pattern, result.score)
