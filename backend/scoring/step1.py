from typing import NamedTuple

import numpy as np

from scoring.trend import TrendResult, classify_trend

WEIGHTS_STANDARD = {"revenue": 0.30, "net_income": 0.30, "cfo": 0.30, "margins": 0.10}
WEIGHTS_CFO_EXEMPT = {"revenue": 0.45, "net_income": 0.45, "cfo": 0.0, "margins": 0.10}

NET_INCOME_BACKUP_THRESHOLD = 40
NET_INCOME_BACKUP_CAP = 80

# Margin classification thresholds, in percentage points. Deliberately
# refined beyond step1_revenue_income_cfo_assessment_prompt.md's original
# stdev-based volatility check -- see CLAUDE.md's "Scoring rubric
# deviations" section for why. A single big dip-and-full-recovery year
# (e.g. one synchronized -8pt drop followed by a +15pt rebound) produces a
# high stdev but isn't the same risk profile as genuine directionless
# chaos, so we now classify on windowed direction + explicit dip/recovery
# accounting instead of penalizing variance itself.
MARGIN_TREND_WINDOW = 3  # early/late average window, in FYs (capped by series length)
MARGIN_DIP_POINTS = 2.0  # a year-over-year drop bigger than this counts as a "real" one-year dip
MARGIN_SUSTAINED_DECLINE_STEPS = 2  # 2+ consecutive down-years = a 3-FY declining stretch
MARGIN_SUSTAINED_DECLINE_POINTS = 5.0  # ...and it must total more than this to count as genuinely "sustained"
MARGIN_STABLE_TOLERANCE = -1.0
MARGIN_SHARP_DECLINE = -5.0
MARGIN_FLAT_DIRECTION = 1.0  # early-vs-late average move smaller than this counts as "no net direction"

VERDICT_BANDS = [
    (86, 100, "Strong Pass"),
    (70, 85, "Pass"),
    (0, 69, "Fail"),
]


class _MarginSeriesAnalysis(NamedTuple):
    direction: float  # late-window average minus early-window average
    num_real_dips: int
    sustained_decline: bool


def _analyze_margin_series(values: np.ndarray) -> _MarginSeriesAnalysis:
    window = min(MARGIN_TREND_WINDOW, len(values))
    direction = float(values[-window:].mean() - values[:window].mean())

    diffs = np.diff(values)
    num_real_dips = int(np.count_nonzero(diffs < -MARGIN_DIP_POINTS))

    sustained_decline = False
    for i in range(len(diffs) - MARGIN_SUSTAINED_DECLINE_STEPS + 1):
        run = diffs[i : i + MARGIN_SUSTAINED_DECLINE_STEPS]
        if np.all(run < 0) and run.sum() <= -MARGIN_SUSTAINED_DECLINE_POINTS:
            sustained_decline = True
            break

    return _MarginSeriesAnalysis(direction, num_real_dips, sustained_decline)


def _classify_margins(gross_margin: list[float], net_margin: list[float], revenue_growing: bool) -> TrendResult:
    if len(gross_margin) < 2 or len(net_margin) < 2:
        return TrendResult("insufficient_data", 0)

    gross = _analyze_margin_series(np.asarray(gross_margin, dtype=float))
    net = _analyze_margin_series(np.asarray(net_margin, dtype=float))

    # Rule 1: a sustained multi-year decline anywhere must not be masked by
    # a later rebound, no matter how positive the early-vs-late average
    # ends up looking -- this can never read as "stable_or_expanding".
    if gross.sustained_decline or net.sustained_decline:
        if net.direction < MARGIN_SHARP_DECLINE and revenue_growing:
            return TrendResult("sharply_declining", 20)
        return TrendResult("gradually_compressing", 60)

    # Rule 2: 2+ real dips in a series that still nets out flat overall is
    # genuine directionless chaos -- reserved for the bottom tier. A single
    # dip (or even 2+ dips that still net a rising trend) never lands here.
    if (gross.num_real_dips >= 2 and abs(gross.direction) < MARGIN_FLAT_DIRECTION) or (
        net.num_real_dips >= 2 and abs(net.direction) < MARGIN_FLAT_DIRECTION
    ):
        return TrendResult("wildly_inconsistent", 0)

    if gross.direction >= MARGIN_STABLE_TOLERANCE and net.direction >= MARGIN_STABLE_TOLERANCE:
        return TrendResult("stable_or_expanding", 100)

    if net.direction < MARGIN_SHARP_DECLINE and revenue_growing:
        return TrendResult("sharply_declining", 20)

    return TrendResult("gradually_compressing", 60)


def _verdict_for(score: int) -> str:
    for low, high, label in VERDICT_BANDS:
        if low <= score <= high:
            return label
    return "Fail"


def score_step1(
    revenue: list[float],
    net_income: list[float],
    operating_income: list[float],
    cfo: list[float] | None,
    gross_margin: list[float],
    net_margin: list[float],
    cfo_exempt: bool,
) -> dict:
    """Pure scoring function per CLAUDE.md's Step 1 spec: takes parsed metric
    series (chronological, oldest fiscal year -> TTM) and returns
    {score, verdict, components}. No I/O, no FMP/DB dependency."""
    revenue_result = classify_trend(revenue)
    net_income_result = classify_trend(net_income)

    net_income_backup_used = False
    if net_income_result.score <= NET_INCOME_BACKUP_THRESHOLD:
        oi_result = classify_trend(operating_income)
        backup_score = min(NET_INCOME_BACKUP_CAP, max(net_income_result.score, oi_result.score))
        net_income_backup_used = backup_score != net_income_result.score
        net_income_result = TrendResult(net_income_result.pattern, backup_score)

    revenue_growing = revenue[-1] > revenue[0] if len(revenue) >= 2 else False
    margin_result = _classify_margins(gross_margin, net_margin, revenue_growing)

    if cfo_exempt or cfo is None:
        cfo_result = None
        weights = WEIGHTS_CFO_EXEMPT
    else:
        cfo_result = classify_trend(cfo)
        weights = WEIGHTS_STANDARD

    weighted_sum = (
        revenue_result.score * weights["revenue"]
        + net_income_result.score * weights["net_income"]
        + (cfo_result.score if cfo_result else 0) * weights["cfo"]
        + margin_result.score * weights["margins"]
    )
    score = max(0, min(100, round(weighted_sum)))

    return {
        "score": score,
        "verdict": _verdict_for(score),
        "components": {
            "revenue": {"score": revenue_result.score, "pattern": revenue_result.pattern},
            "net_income": {
                "score": net_income_result.score,
                "pattern": net_income_result.pattern,
                "used_operating_income_backup": net_income_backup_used,
            },
            "cfo": {"score": cfo_result.score, "pattern": cfo_result.pattern} if cfo_result else None,
            "margins": {"score": margin_result.score, "pattern": margin_result.pattern},
        },
        "weights": weights,
    }
