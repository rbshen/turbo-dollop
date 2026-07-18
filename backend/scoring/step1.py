import numpy as np

from scoring.trend import TrendResult, classify_trend

WEIGHTS_STANDARD = {"revenue": 0.30, "net_income": 0.30, "cfo": 0.30, "margins": 0.10}
WEIGHTS_CFO_EXEMPT = {"revenue": 0.45, "net_income": 0.45, "cfo": 0.0, "margins": 0.10}

NET_INCOME_BACKUP_THRESHOLD = 40
NET_INCOME_BACKUP_CAP = 80

# Margin classification thresholds, in percentage points.
MARGIN_VOLATILITY_STD = 5.0
MARGIN_STABLE_TOLERANCE = -1.0
MARGIN_SHARP_DECLINE = -5.0

VERDICT_BANDS = [
    (85, 100, "Strong Pass"),
    (70, 84, "Pass with caution"),
    (50, 69, "May not pass — investigate"),
    (0, 49, "Fail"),
]


def _classify_margins(gross_margin: list[float], net_margin: list[float], revenue_growing: bool) -> TrendResult:
    if len(gross_margin) < 2 or len(net_margin) < 2:
        return TrendResult("insufficient_data", 0)

    gross = np.asarray(gross_margin, dtype=float)
    net = np.asarray(net_margin, dtype=float)

    if np.std(np.diff(gross)) > MARGIN_VOLATILITY_STD or np.std(np.diff(net)) > MARGIN_VOLATILITY_STD:
        return TrendResult("wildly_inconsistent", 0)

    gross_change = gross[-1] - gross[0]
    net_change = net[-1] - net[0]

    if gross_change >= MARGIN_STABLE_TOLERANCE and net_change >= MARGIN_STABLE_TOLERANCE:
        return TrendResult("stable_or_expanding", 100)

    if net_change < MARGIN_SHARP_DECLINE and revenue_growing:
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
