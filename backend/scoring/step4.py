from typing import NamedTuple

import numpy as np

from scoring.series_trend import analyze_series_direction
from scoring.trend import TrendResult

# --- ROE / ROIC tiers (percent) ---------------------------------------------
ROE_EXCELLENT_AVG = 15.0
ROE_GOOD_AVG = 12.0
ROE_MARGINAL_AVG = 8.0
ROE_MIN_YEAR_CONSISTENCY = 8.0

# --- Revenue vs Accounts Receivable ------------------------------------------
# A YoY gap (AR growth % minus revenue growth %) smaller than this is noise,
# not real AR outpacing -- same noise-floor convention as the margin
# classifier's percentage-point threshold.
AR_GAP_NOISE_FLOOR = 2.0
AR_GAP_SMALL_MAX = 15.0
AR_GAP_MEDIUM_MAX = 50.0
# "Concerning" was originally a fixed "3 of 5" transitions (the doc's own
# 5yr window) -- expressed as a ratio so it rescales correctly now that the
# window is 10yr+TTM (10 transitions). At n=5 this still rounds to 3
# (backward compatible); at n=10 it's 6, restoring the same ~60% severity
# the original "3+" tier represented before the window extension (see
# CLAUDE.md's Step 4 deviations).
AR_CONCERNING_TRANSITION_RATIO = 0.6

# --- Cash Conversion Cycle ----------------------------------------------------
# No doc-given numeric thresholds exist for CCC (unlike margins, which were
# tuned after live testing) -- these are first-pass judgment calls, flagged
# for review against real tickers before relying on them broadly.
CCC_TREND_WINDOW = 3
CCC_REAL_MOVE_DAYS = 3.0
CCC_SUSTAINED_STEPS = 2
CCC_SUSTAINED_DAYS = 5.0
CCC_FLAT_DIRECTION_DAYS = 2.0
CCC_STABLE_TOLERANCE_DAYS = -1.0

STRONG_PASS_SCORE = 90


class RatioResult(NamedTuple):
    label: str
    points: int
    hard_fail: bool


def _score_avg_min_tier(avg: float, min_year: float) -> tuple[str, int, bool]:
    if avg > ROE_EXCELLENT_AVG and min_year >= ROE_MIN_YEAR_CONSISTENCY:
        return "excellent", 100, False
    if avg >= ROE_GOOD_AVG and min_year >= ROE_MIN_YEAR_CONSISTENCY:
        return "good", 85, False
    if avg >= ROE_MARGINAL_AVG:
        return "marginal", 60, False
    return "fail", 0, True


def _net_income_consistent_and_positive(net_income: list[float]) -> bool:
    """Substitute signal for ROE when equity is negative anywhere in the
    window: positive throughout, and net growth over the window (last >=
    first) -- deliberately the same simple "last >= first" bar Step 1 uses
    for revenue_growing, not a full trend classifier, since the doc's own
    language ("consistently maintained/growing") is qualitative."""
    if not net_income or any(v <= 0 for v in net_income):
        return False
    return net_income[-1] >= net_income[0]


def score_roe(roe: list[float], equity: list[float | None], net_income: list[float]) -> RatioResult:
    """ROE tiering with the negative-equity exception: if shareholders'
    equity is <=0 in any period, raw ROE is unreliable/sign-flipped for the
    whole metric -- substitute a positive-and-growing-net-income check
    instead of the normal avg/min-year tiering (see step4 assessment doc)."""
    if any(e is not None and e <= 0 for e in equity):
        if _net_income_consistent_and_positive(net_income):
            return RatioResult("positive_despite_negative_equity", 100, False)
        return RatioResult("negative_equity_inconsistent_income", 60, False)

    valid = [v for v in roe if v is not None]
    if not valid:
        return RatioResult("insufficient_data", 0, False)
    avg = sum(valid) / len(valid)
    min_year = min(valid)
    label, points, hard_fail = _score_avg_min_tier(avg, min_year)
    return RatioResult(label, points, hard_fail)


def score_roic(roic: list[float]) -> RatioResult:
    valid = [v for v in roic if v is not None]
    if not valid:
        return RatioResult("insufficient_data", 0, False)
    avg = sum(valid) / len(valid)
    min_year = min(valid)
    label, points, hard_fail = _score_avg_min_tier(avg, min_year)
    return RatioResult(label, points, hard_fail)


def _ar_gap_magnitude(gap: float) -> str:
    if gap <= AR_GAP_SMALL_MAX:
        return "small"
    if gap <= AR_GAP_MEDIUM_MAX:
        return "medium"
    return "large"


def score_revenue_vs_ar(revenue: list[float], accounts_receivable: list[float]) -> RatioResult:
    """Metric 3: Revenue must grow at the same or faster rate than
    Accounts Receivable. Checked worst-first since the tiers below overlap
    (e.g. the "concerning" count and "majority" can both be true at once):

    1. Majority of transitions outpacing, OR revenue declining while AR
       grows in the same year -> 0 (auto-escalate regardless of count).
    2. `concerning_threshold`+ transitions outpacing (proportional to the
       window size -- see AR_CONCERNING_TRANSITION_RATIO), OR any single
       large-magnitude (>50pp) gap -> 40.
    3. 0 outpacing transitions, or exactly 1 isolated year with a small
       (<=15pp) gap -> 100.
    4. Otherwise (1-2 outpacing transitions, not caught above) -> 70.
    """
    n = len(revenue) - 1
    if n < 1 or len(accounts_receivable) != len(revenue):
        return RatioResult("insufficient_data", 0, False)

    outpacing_gaps: list[float] = []
    strong_red_flag = False
    for i in range(n):
        prev_rev, curr_rev = revenue[i], revenue[i + 1]
        prev_ar, curr_ar = accounts_receivable[i], accounts_receivable[i + 1]
        if not prev_rev or not prev_ar:
            continue
        revenue_yoy = (curr_rev - prev_rev) / abs(prev_rev) * 100
        ar_yoy = (curr_ar - prev_ar) / abs(prev_ar) * 100
        if revenue_yoy < 0 and ar_yoy > 0:
            strong_red_flag = True
        gap = ar_yoy - revenue_yoy
        if gap > AR_GAP_NOISE_FLOOR:
            outpacing_gaps.append(gap)

    num_outpacing = len(outpacing_gaps)
    has_large = any(_ar_gap_magnitude(g) == "large" for g in outpacing_gaps)
    majority_outpacing = num_outpacing > n / 2
    # floor of 3: below a 5-transition window, "3+" was never reachable via
    # count anyway (n=1-2 can't produce 3 outpacing transitions), so the
    # ratio must not round down below the original absolute floor.
    concerning_threshold = max(3, round(AR_CONCERNING_TRANSITION_RATIO * n))

    if majority_outpacing or strong_red_flag:
        return RatioResult("outpacing_majority_or_red_flag", 0, False)
    if num_outpacing >= concerning_threshold or has_large:
        return RatioResult("outpacing_concerning", 40, False)
    if num_outpacing == 0:
        return RatioResult("healthy", 100, False)
    if num_outpacing == 1 and _ar_gap_magnitude(outpacing_gaps[0]) == "small":
        return RatioResult("healthy", 100, False)
    return RatioResult("outpacing_isolated", 70, False)


def classify_ccc_trend(ccc: list[float]) -> TrendResult:
    """CCC classification: reuses the exact early/late-direction +
    dip-count + sustained-decline logic built for Step 1's margin
    classifier, run on the negated series -- a declining CCC (faster cash
    conversion) is the good direction here, the inverse of margins."""
    if len(ccc) < 2:
        return TrendResult("insufficient_data", 0)

    negated = -np.asarray(ccc, dtype=float)
    analysis = analyze_series_direction(
        negated, CCC_TREND_WINDOW, CCC_REAL_MOVE_DAYS, CCC_SUSTAINED_STEPS, CCC_SUSTAINED_DAYS
    )

    # Rule 1: a sustained multi-period rise in real CCC (the negated series
    # sustainedly falling) can't be masked by a later improvement -- UNLESS
    # direction (the early-vs-late-window average, computed above) shows the
    # decline has since been durably outweighed. sustained_decline is a flat
    # scan across the whole window with no recency awareness, so on a now-
    # 10yr+TTM series an old, small, fully-reversed blip (e.g. a 2016-2018
    # uptick preceding a decade of improvement) could otherwise permanently
    # cap the score at 0 even while direction is strongly positive -- this
    # gate reuses the same CCC_STABLE_TOLERANCE_DAYS boundary the "stable"
    # tier below already uses, rather than a new constant.
    if analysis.sustained_decline and analysis.direction < CCC_STABLE_TOLERANCE_DAYS:
        return TrendResult("sustained_upward", 0)

    # Rule 2: 2+ real swings netting out flat overall -- genuine volatility,
    # no clear trend (mirrors the margin classifier's chaotic gate).
    if analysis.num_real_dips >= 2 and abs(analysis.direction) < CCC_FLAT_DIRECTION_DAYS:
        return TrendResult("volatile_no_trend", 40)

    if analysis.direction >= CCC_STABLE_TOLERANCE_DAYS:
        if analysis.num_real_dips >= 1:
            return TrendResult("volatile_but_net_declining", 70)
        return TrendResult("declining_or_stable", 100)

    # Net worsening direction, not caught by the strict sustained check above
    # (e.g. a slow multi-year creep) -- still reads as an upward CCC trend.
    return TrendResult("sustained_upward", 0)


def _verdict_for(score: int, hard_fail: bool) -> str:
    if hard_fail:
        return "Fail"
    if score > STRONG_PASS_SCORE:
        return "Strong Pass"
    return "Pass"


def score_step4(
    roe: RatioResult,
    ar: RatioResult,
    roic: RatioResult | None,
    ccc: TrendResult | None,
) -> dict:
    """Pure scoring function: equal-weight redistribution among whatever
    metrics are applicable (all 4 -> 25% each; ROIC exempt -> remaining 3 at
    33.3% each; ROIC+CCC both exempt -> remaining 2 at 50% each), with a
    hard-fail override if ROE or ROIC (when applicable) lands in its Fail
    tier -- mirrors Step 2/Step 5's hard-fail override pattern."""
    applicable: list[tuple[str, int]] = [("roe", roe.points), ("ar", ar.points)]
    if roic is not None:
        applicable.append(("roic", roic.points))
    if ccc is not None:
        applicable.append(("ccc", ccc.score))

    weight = 1.0 / len(applicable)
    weighted_sum = sum(points * weight for _, points in applicable)
    score = max(0, min(100, round(weighted_sum)))

    hard_fail = roe.hard_fail or (roic.hard_fail if roic is not None else False)

    return {
        "score": score,
        "verdict": _verdict_for(score, hard_fail),
        "hard_fail": hard_fail,
        "weight_per_metric": weight,
        "components": {
            "roe": {"label": roe.label, "points": roe.points},
            "roic": {"label": roic.label, "points": roic.points} if roic is not None else None,
            "revenue_vs_ar": {"label": ar.label, "points": ar.points},
            "ccc": {"pattern": ccc.pattern, "points": ccc.score} if ccc is not None else None,
        },
    }
