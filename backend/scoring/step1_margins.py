"""The Step 1 Margins engine: gross, operating and net margin scored on their own, then blended (docs/specs/financials.md, "Margins").

Margins are the one Step 1 metric judged RELATIVE to their own level, so this module is separate from the shared dollar/ratio engine
(scoring/step1_engine.py), which Revenue, Net Income, Operating Income, CFO and FCF keep untouched. It reuses only that engine's
metric-neutral helpers (the robust trend and the dip discount curve). Everything here reads COMPLETED fiscal years, with one capped
exception: a TTM nudge of at most +-TTM_CAP points per series.

Per series (`assess_margin_series`), in this order:

1. One-off-year clamp: an isolated outlier year (never the first or the latest) is pulled into its neighbours' range.
2. Boom-bust cap: a multi-year boom that has faded back to the pre-boom baseline keeps half its excess.
3. Units: every margin is judged against its own level = max(median |x|, LEVEL_FLOOR) points.
4. Trend score T (flat 88, +2% of level a year 100, -7% a year or worse 30), with a recent-slope blend that only ever pulls DOWN.
5. Older dips (age 2 and up) cost a decaying dip burden through the shared discount curve.
6. ONE recent-fall charge, the largest of four measures (not their sum): recent slope, recent dips (last two years, x3), the latest
   year below its 5-year average, and the last-year fall. When the series has not fallen below its own median (8+ years), the
   charge is capped (fade cap).
7. TTM nudge, soft floor (a profitable series never scores 0-10), positivity ceiling (a latest value at or below zero is capped).

Combination (`classify_margins`): Margins = 0.5 x Gross + 0.5 x max(Net, Operating), capped by a loss-making ceiling when neither net
nor operating margin is positive in the latest year. There is no min() and no gross hard cap.

Every threshold is a named constant here. No I/O.
"""

import math
from dataclasses import dataclass, field

import numpy as np

from scoring.step1_engine import (
    CEILING_AT_ZERO,
    CEILING_ZERO_LOSS,
    DECLINE,
    DISCOUNT_MAX,
    DISCOUNT_POWER,
    DISCOUNT_SCALE,
    FLAT,
    INSUFFICIENT,
    UPTREND,
    _theil_sen_slope,
    _trend,
)
from scoring.trend import TrendResult

DIPS_SUFFIX = "_dips"

# --- Units and trend score ------------------------------------------------------------------------------------------------------
LEVEL_FLOOR = 5.0  # a margin is judged relative to max(median |x|, LEVEL_FLOOR) points
TREND_FULL = 0.02  # T: +2% of level a year or better scores 100
TREND_FLAT_SCORE = 88.0  # T: a flat series
TREND_FLOOR = -0.07  # T: -7% of level a year or worse scores TREND_FLOOR_SCORE
TREND_FLOOR_SCORE = 30.0
LABEL_TREND = 0.0125  # +-this per year labels a series uptrend / decline (display and the Utility carve-out only)
DIPS_LABEL_MIN_K = 0.25  # "_dips" is appended to the label from this burden up

# --- Recent-slope blend ----------------------------------------------------------------------------------------------------------
RECENT_WINDOW = 4  # the last 4 completed years
RECENT_MIN_POINTS = 6  # the blend needs this many points
RECENT_DEADBAND = 0.015  # a recent slope better than -1.5% of level a year is ignored (it never lowers an uptrend)
RECENT_BLEND = 0.9  # weight of the recent slope when it is worse than the deadband

# --- Dips ------------------------------------------------------------------------------------------------------------------------
DIP_LO = 0.04  # a fall's excess over the trend counts as a dip from 4% of level ...
DIP_HI = 0.20  # ... and as a full dip at 20%
DIP_WEIGHT_CAP = 3.0  # one fall counts at most this many dips
RECENT_DIP_AGE = 1  # a dip into one of the last two years is "recent" (age 0 = the last change)
RECENT_DIP_MULT = 3.0  # recent dips are charged x3 inside the single recent-fall charge
DIP_HALF_LIFE_YEARS = 4.0  # older dips (age 2 and up) decay with this half-life: 0.5 ** ((age - 2) / half-life)

# --- The single recent-fall charge -----------------------------------------------------------------------------------------------
AVG_YEARS = 5  # the below-average measure: 5 completed years ending at the latest
AVG_BAND_REL = 0.05  # tolerance band = max(5% of the average, AVG_BAND_MIN)
AVG_BAND_MIN = 0.5
AVG_MAX_CUT = 20.0  # points, reached at a further AVG_SPAN shortfall (relative to the average)
AVG_SPAN = 0.25
LAST_LO = 0.05  # last-year fall (excess over trend) starts to cut at 5% of level ...
LAST_HI = 0.30  # ... and cuts the full LAST_CUT at 30%
LAST_CUT = 0.5  # at most half of the score
FADE_MIN_YEARS = 8  # fade cap: the window needs this many years ...
FADE_FLOOR = 1.0  # ... and the latest year at or above FADE_FLOOR x the series median ...
FADE_CAP = 35.0  # ... then the recent-fall charge is at most this many points

# --- One-off-year clamp ----------------------------------------------------------------------------------------------------------
CLAMP_MIN_YEARS = 5
CLAMP_NEIGHBOURS = 2  # years each side that define the neighbours' range
CLAMP_MIN_REL = 0.75  # an outlier sits outside its neighbours' range by at least this share of the series level ...
CLAMP_MIN_SPREAD = 1.5  # ... and by at least this multiple of the neighbours' own spread
CLAMP_MAX_YEARS = 2  # at most this many clamped years per series

# --- Boom-bust cap ---------------------------------------------------------------------------------------------------------------
BOOM_REL = 0.25  # a boom year is more than this share above the series median
BOOM_MIN_YEARS = 2
BOOM_PRE_YEARS = 3  # ordinary years before the first boom year
BOOM_MIN_WINDOW = 8
BOOM_BASELINE_ABOVE = 0.15  # the latest year is back within -25% .. +15% of the pre-boom baseline
BOOM_BASELINE_BELOW = 0.25
BOOM_KEEP = 0.5  # boom years keep this share of their excess above the cap level

# --- Floor, ceiling, TTM, combination --------------------------------------------------------------------------------------------
SOFT_FLOOR = 20.0  # a profitable series' raw score 0..SOFT_FLOOR_TOP maps onto SOFT_FLOOR..SOFT_FLOOR_TOP
SOFT_FLOOR_TOP = 30.0
TTM_CAP = 5.0  # points, per series
TTM_MIN_YEARS = 5
TTM_BONUS_SPAN = 0.20  # the bonus is full at a TTM this share of the reference scale above the latest year
TTM_PENALTY_SPAN = 0.25  # the penalty is full at a shortfall of this share of the reference scale
TTM_SKIP_ABS = 8.0  # a TTM further than max(8 points, 50% of the latest year) from the latest year is skipped
TTM_SKIP_REL = 0.5
GROSS_WEIGHT = 0.5  # Margins = GROSS_WEIGHT x Gross + (1 - GROSS_WEIGHT) x max(Net, Operating)
CARVEOUT_FLOOR = 60  # Utility: a declining series is never scored below this (applied per series, before the blend)

MARGIN_KEYS = ("gross", "operating", "net")


@dataclass(frozen=True)
class MarginAssessment:
    pattern: str
    score: int  # rounded display score
    score_f: float  # the unrounded score the blend uses
    charge: str | None = None  # which of the four recent-fall measures was charged (None = no recent charge)
    charge_points: float = 0.0
    clamped_years: tuple[int, ...] = ()  # indices (oldest first) pulled into their neighbours' range
    boom_bust: bool = False
    fade_capped: bool = False
    ceiling: float | None = None  # the positivity ceiling, when the latest value is at or below zero
    ttm_adjustment: float = 0.0
    wf: dict = field(default_factory=dict)  # points lost per rule, for tests and diagnostics


_INSUFFICIENT = MarginAssessment(INSUFFICIENT, 0, 0.0)


def _trend_score(g: float) -> float:
    if g >= TREND_FULL:
        return 100.0
    if g >= 0:
        return TREND_FLAT_SCORE + (100.0 - TREND_FLAT_SCORE) * g / TREND_FULL
    if g <= TREND_FLOOR:
        return TREND_FLOOR_SCORE
    return TREND_FLAT_SCORE - (TREND_FLAT_SCORE - TREND_FLOOR_SCORE) * g / TREND_FLOOR


def _discount(burden: float) -> float:
    return DISCOUNT_MAX * (1.0 - math.exp(-((burden / DISCOUNT_SCALE) ** DISCOUNT_POWER)))


def clamp_one_off_years(x: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Rule: the one-off-year clamp. Pulls an isolated outlier year (never the first or the latest) into the range of its neighbours
    (up to CLAMP_NEIGHBOURS each side) when it lies outside that range by at least CLAMP_MIN_REL of the series level AND at least
    CLAMP_MIN_SPREAD times the neighbours' own spread. Largest outlier first, at most CLAMP_MAX_YEARS per series."""
    x = np.asarray(x, dtype=float).copy()
    n = len(x)
    if n < CLAMP_MIN_YEARS:
        return x, []
    level = max(float(np.median(np.abs(x))), LEVEL_FLOOR)
    clamped: list[int] = []
    for _ in range(CLAMP_MAX_YEARS):
        best = None
        for i in range(1, n - 1):
            if i in clamped:
                continue
            near = np.concatenate((x[max(0, i - CLAMP_NEIGHBOURS) : i], x[i + 1 : i + 1 + CLAMP_NEIGHBOURS]))
            lo, hi = float(near.min()), float(near.max())
            outside = max(lo - x[i], x[i] - hi, 0.0)
            if outside / level >= CLAMP_MIN_REL and outside >= CLAMP_MIN_SPREAD * (hi - lo) and (best is None or outside > best[0]):
                best = (outside, i, lo, hi)
        if best is None:
            break
        _, i, lo, hi = best
        x[i] = min(max(x[i], lo), hi)
        clamped.append(i)
    return x, sorted(clamped)


def cap_boom_bust(x: np.ndarray) -> tuple[np.ndarray, bool]:
    """Rule: the boom-bust cap. M is the series median; boom years are those more than BOOM_REL above M. It applies when there are
    at least BOOM_MIN_YEARS of them, at least BOOM_PRE_YEARS ordinary years before the first, and the latest year is back at the
    pre-boom baseline B (the median of the years before the first boom year) within -BOOM_BASELINE_BELOW .. +BOOM_BASELINE_ABOVE.
    From the first boom year on, every year above C = the larger of the ordinary-year median and the latest year keeps only
    BOOM_KEEP of its excess above C."""
    x = np.asarray(x, dtype=float).copy()
    n = len(x)
    if n < BOOM_MIN_WINDOW:
        return x, False
    median = float(np.median(x))
    if median <= 0:
        return x, False
    boom = x > median * (1 + BOOM_REL)
    if boom.sum() < BOOM_MIN_YEARS:
        return x, False
    first = int(np.argmax(boom))
    if first < BOOM_PRE_YEARS:
        return x, False
    baseline = float(np.median(x[:first]))
    if baseline <= 0 or not (baseline * (1 - BOOM_BASELINE_BELOW) <= x[-1] <= baseline * (1 + BOOM_BASELINE_ABOVE)):
        return x, False
    cap = max(float(np.median(x[~boom])), float(x[-1]))
    x[first:] = np.where(x[first:] > cap, cap + BOOM_KEEP * (x[first:] - cap), x[first:])
    return x, True


def _ttm_nudge(
    ttm: float, latest: float, average: float, level: float, shortfall: float, burden: float, band: float
) -> float:
    """Rule: the TTM nudge, +-TTM_CAP points. Bonus: the series is below its average or had a dip, TTM is back within the band
    and above the latest year. Penalty: TTM is below both the latest year and (average - band)."""
    scale = max(abs(average), level * 0.5)
    had_dip = shortfall > 0 or burden >= 1.0
    if had_dip and ttm >= average - band and ttm > latest:
        return TTM_CAP * min(max(((ttm - latest) / scale) / TTM_BONUS_SPAN, 0.0), 1.0)
    if ttm < latest and ttm < average - band:
        return -TTM_CAP * min(max(((average - band - ttm) / scale) / TTM_PENALTY_SPAN, 0.0), 1.0)
    return 0.0


def ttm_allowed(values: list[float], ttm: float | None, outlier_flagged: bool) -> bool:
    """Rule: the TTM skip rules. No TTM when the outlier check flagged the ticker, when TTM is missing, or when it sits further from
    the latest completed year than max(TTM_SKIP_ABS points, TTM_SKIP_REL of the latest year's value)."""
    if outlier_flagged or ttm is None or not values:
        return False
    return abs(ttm - values[-1]) <= max(TTM_SKIP_ABS, TTM_SKIP_REL * abs(values[-1]))


def assess_margin_series(values: list[float], ttm: float | None = None, ttm_ok: bool = True) -> MarginAssessment:
    """One margin series (percent, oldest first, completed fiscal years, no missing values) -> score 0-100. `ttm` is the trailing-
    twelve-month margin and `ttm_ok` whether the caller's skip rules allow it (see `ttm_allowed`); the nudge also needs 5+ years and
    a positive latest year. Fewer than 2 points is `insufficient_data`."""
    raw_values = np.asarray(values, dtype=float)
    n = len(raw_values)
    if n < 2:
        return _INSUFFICIENT

    x, clamped = clamp_one_off_years(raw_values)
    x, boom_bust = cap_boom_bust(x)
    level = max(float(np.median(np.abs(x))), LEVEL_FLOOR)
    y = x / level

    # Trend, and the recent-slope blend (only ever pulls down; a slope inside the deadband is ignored)
    g_long = _trend(y)
    recent = None
    if n >= RECENT_MIN_POINTS:
        shifted = min(0.0, _theil_sen_slope(y[-RECENT_WINDOW:]) + RECENT_DEADBAND)
        if shifted < 0 and shifted < g_long:
            recent = shifted
    g_blend = (1 - RECENT_BLEND) * g_long + RECENT_BLEND * recent if recent is not None else g_long
    t_long, t_blend = _trend_score(g_long), _trend_score(g_blend)

    # Dips beyond the trend; older dips decay, recent ones are charged inside the single recent-fall charge
    excess = np.maximum(0.0, -np.diff(y) - max(0.0, -g_long))
    weight = np.clip((excess - DIP_LO) / (DIP_HI - DIP_LO), 0.0, DIP_WEIGHT_CAP)
    age = np.arange(n - 2, -1, -1)
    is_recent = age <= RECENT_DIP_AGE
    decay = 0.5 ** ((age - 2) / DIP_HALF_LIFE_YEARS)
    k_old = float(np.sum(weight * np.where(is_recent, 0.0, decay)))
    k_recent = float(np.sum(weight * np.where(is_recent, RECENT_DIP_MULT, 0.0)))
    burden = k_old + k_recent
    base = max(0.0, t_long - _discount(k_old))

    # The four recent-fall measures, in points lost from `base`
    average = float(np.mean(x[-AVG_YEARS:]))
    band = max(AVG_BAND_REL * abs(average), AVG_BAND_MIN)
    shortfall = (average - x[-1] - band) / max(abs(average), level * 0.5) if n >= AVG_YEARS else 0.0
    measures = {
        "slope": base - max(0.0, t_blend - _discount(k_old)),
        "dip": base - max(0.0, t_long - _discount(k_old + k_recent)),
        "avg": min(AVG_MAX_CUT * min(max(shortfall / AVG_SPAN, 0.0), 1.0), base),
        "last": base * LAST_CUT * min(max((float(excess[-1]) - LAST_LO) / (LAST_HI - LAST_LO), 0.0), 1.0),
    }
    charge = max(measures, key=measures.get)
    charge_points = measures[charge]
    fade_capped = False
    median = float(np.median(x))
    if n >= FADE_MIN_YEARS and median > 0 and x[-1] >= FADE_FLOOR * median and charge_points > FADE_CAP:
        charge_points, fade_capped = FADE_CAP, True
    raw = max(0.0, base - charge_points)

    latest = float(raw_values[-1])
    ttm_adjustment = 0.0
    if ttm is not None and ttm_ok and n >= TTM_MIN_YEARS and latest > 0:
        ttm_adjustment = _ttm_nudge(float(ttm), float(x[-1]), average, level, shortfall, burden, band)
    after_ttm = min(max(raw + ttm_adjustment, 0.0), 100.0)

    after_floor = after_ttm
    if latest > 0 and after_ttm < SOFT_FLOOR_TOP:
        after_floor = SOFT_FLOOR + after_ttm * (SOFT_FLOOR_TOP - SOFT_FLOOR) / SOFT_FLOOR_TOP
    final = after_floor
    ceiling = None
    if latest <= 0:
        ceiling = CEILING_AT_ZERO * max(0.0, 1.0 + latest / CEILING_ZERO_LOSS)
        final = min(final, ceiling)

    shape = UPTREND if g_long >= LABEL_TREND else DECLINE if g_long <= -LABEL_TREND else FLAT
    pattern = shape + (DIPS_SUFFIX if burden >= DIPS_LABEL_MIN_K else "")
    return MarginAssessment(
        pattern=pattern,
        score=int(round(final)),
        score_f=final,
        charge=charge if charge_points > 0 else None,
        charge_points=charge_points,
        clamped_years=tuple(clamped),
        boom_bust=boom_bust,
        fade_capped=fade_capped,
        ceiling=ceiling,
        ttm_adjustment=ttm_adjustment,
        wf={
            "trend": 100.0 - t_long,
            "older_dips": t_long - base,
            "recent_charge": base - raw,
            "ttm": raw - after_ttm,
            "soft_floor": after_ttm - after_floor,
            "ceiling": after_floor - final,
            "measures": measures,
        },
    )


def _margin_input(
    values: list[float], carveout: bool, ttm: float | None, ttm_ok: bool
) -> tuple[MarginAssessment, float] | None:
    """One margin series through the engine, then the Utility carve-out. None = missing (fewer than 2 years): the input drops out.
    Returns the assessment (display score) and the unrounded score the blend uses."""
    result = assess_margin_series(values, ttm, ttm_ok)
    if result.pattern == INSUFFICIENT:
        return None
    score_f = result.score_f
    if carveout and result.pattern.startswith(DECLINE):
        score_f = max(score_f, float(CARVEOUT_FLOOR))
    return result, score_f


def classify_margins(
    gross_margin: list[float],
    operating_margin: list[float],
    net_margin: list[float],
    carveout: bool = False,
    ttm_margins: dict[str, float | None] | None = None,
    ttm_outlier_flagged: bool = False,
) -> tuple[TrendResult, dict]:
    """Margins = 0.5 x Gross + 0.5 x max(Net, Operating) of the three per-series scores, rounded once. A missing input drops out: no
    gross margin gives max(N, O) alone; one of N / O missing gives the other as the profit leg; N and O both missing makes Margins
    `insufficient_data` whatever G is. When neither the latest net nor the latest operating margin is positive, Margins is capped at
    the positivity-ceiling curve of the better of the two.

    `ttm_margins` ({"gross"|"operating"|"net": trailing-twelve-month margin or None}) feeds each series' capped TTM nudge;
    `ttm_outlier_flagged` skips it for every series (the outlier check flagged a statement line). Returns the result (the pattern is
    the weaker leg's) and the display detail: each present input's score and pattern under `inputs` (plus the TTM nudge when it
    moved the score and the rule that drove it), `profit_leg` (net or operating, whichever scored higher), `legs` (the unrounded gross
    and profit-leg scores), `binding` (the weaker leg: "gross" or the profit leg's key, kept for display compatibility) and
    `ceiling` when the loss-making cap bound."""
    ttm_margins = ttm_margins or {}
    series = {"gross": gross_margin, "operating": operating_margin, "net": net_margin}
    inputs = {
        key: _margin_input(
            values, carveout, ttm_margins.get(key), ttm_allowed(values, ttm_margins.get(key), ttm_outlier_flagged)
        )
        for key, values in series.items()
    }
    detail: dict = {"inputs": {}}
    for key, item in inputs.items():
        if item is None:
            continue
        assessment = item[0]
        entry: dict = {"score": assessment.score, "pattern": assessment.pattern}
        if assessment.ttm_adjustment:
            entry["ttm_adjustment"] = round(assessment.ttm_adjustment, 1)
        if assessment.charge:
            entry["charge"] = assessment.charge
        detail["inputs"][key] = entry

    gross, operating, net = inputs["gross"], inputs["operating"], inputs["net"]
    if operating is None and net is None:
        return TrendResult(INSUFFICIENT, 0), detail

    present = {key: item for key, item in (("net", net), ("operating", operating)) if item is not None}
    profit_key = max(present, key=lambda key: present[key][1])  # a tie between N and O goes to net margin (listed first)
    profit_assessment, profit_score = present[profit_key]
    detail["profit_leg"] = profit_key

    if gross is None:
        blended, weaker_key, pattern = profit_score, profit_key, profit_assessment.pattern
        detail["legs"] = {"profit": round(profit_score, 1)}
    else:
        gross_assessment, gross_score = gross
        blended = GROSS_WEIGHT * gross_score + (1 - GROSS_WEIGHT) * profit_score
        gross_is_weaker = gross_score <= profit_score
        weaker_key = "gross" if gross_is_weaker else profit_key
        pattern = gross_assessment.pattern if gross_is_weaker else profit_assessment.pattern
        detail["legs"] = {"gross": round(gross_score, 1), "profit": round(profit_score, 1)}

    latest = [values[-1] for values in (operating_margin, net_margin) if values]
    if latest and max(latest) <= 0:
        ceiling = CEILING_AT_ZERO * max(0.0, 1.0 + max(latest) / CEILING_ZERO_LOSS)
        if blended > ceiling:
            blended = ceiling
            detail["ceiling"] = round(ceiling, 1)
    detail["binding"] = weaker_key
    return TrendResult(pattern, int(round(blended))), detail
