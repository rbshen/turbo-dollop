import numpy as np

from scoring.series_trend import analyze_series_direction, robust_late_direction
from scoring.trend import TrendResult, classify_trend

WEIGHTS_STANDARD = {"revenue": 0.25, "net_income": 0.25, "cfo": 0.25, "margins": 0.10, "fcf": 0.15}
# FCF is derived from CFO, so wherever CFO is exempt (Bank / Property
# Developer / Commodity Company), FCF is exempt for the same underlying
# reason -- their combined 25%+15% redistributes evenly across the 3
# remaining applicable metrics (Revenue, Net Income, Margins), same
# equal-redistribution convention used everywhere else in this app.
_CFO_FCF_EXEMPT_WEIGHT = WEIGHTS_STANDARD["cfo"] + WEIGHTS_STANDARD["fcf"]
_REDISTRIBUTE_TARGETS = ("revenue", "net_income", "margins")
_PER_TARGET_BONUS = _CFO_FCF_EXEMPT_WEIGHT / len(_REDISTRIBUTE_TARGETS)
WEIGHTS_CFO_EXEMPT = {
    "revenue": WEIGHTS_STANDARD["revenue"] + _PER_TARGET_BONUS,
    "net_income": WEIGHTS_STANDARD["net_income"] + _PER_TARGET_BONUS,
    "cfo": 0.0,
    "margins": WEIGHTS_STANDARD["margins"] + _PER_TARGET_BONUS,
    "fcf": 0.0,
}

# --- Free Cash Flow tiers -----------------------------------------------
# FCF is "consistently positive," not a growth trend -- deliberately does
# NOT reuse classify_trend's 6-tier pattern. What matters per the doc's own
# rationale is whether a cash-burn stretch is sustained (2+ CONSECUTIVE
# negative years = bankruptcy risk), not merely whether a negative year
# exists somewhere in the history.
FCF_EXCELLENT_SCORE = 100
FCF_GOOD_SCORE = 85
FCF_MARGINAL_SCORE = 60
FCF_FAIL_SCORE = 0

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
    (91, 100, "Strong Pass"),
    (70, 90, "Pass"),
    (0, 69, "Fail"),
]


def _analyze_margin_series(values: np.ndarray):
    return analyze_series_direction(
        values,
        MARGIN_TREND_WINDOW,
        MARGIN_DIP_POINTS,
        MARGIN_SUSTAINED_DECLINE_STEPS,
        MARGIN_SUSTAINED_DECLINE_POINTS,
    )


def _series_recovered(values: np.ndarray, analysis) -> bool:
    """True if this series has no sustained decline, or -- if it does --
    the decline has been durably reversed: direction is non-negative AND
    the current (TTM) value has climbed back to at least the same
    early-window baseline `direction` itself is measured against. Confirmed
    via live data (see CLAUDE.md's Step 1 deviations) that a 10yr+TTM
    window makes an old, small, fully-reversed decline (frequently the
    COVID-2020 FY) permanently cap otherwise-excellent margins at
    "gradually_compressing" -- the same class of bug fixed in Step 4's CCC
    classifier. Uses the early-window AVERAGE rather than the single value
    right before the decline began, since that value is often itself an
    anomalous spike (e.g. a one-off gain) -- requiring a full re-exceedance
    of a spike would leave genuine recoveries capped forever."""
    if not analysis.sustained_decline:
        return True
    if analysis.direction < MARGIN_STABLE_TOLERANCE:
        return False
    w = min(MARGIN_TREND_WINDOW, len(values))
    return bool(values[-1] >= values[:w].mean())


def _stable_and_spike_robust(gross_arr: np.ndarray, gross, net_arr: np.ndarray, net) -> bool:
    """True if both series read as non-negative direction AND that reading
    isn't solely propped up by a single anomalous point in the late window
    (e.g. LYV: a decade flat at 23-30% gross margin, then one TTM spike to
    44.7% flips direction positive on its own). Mirrors sustained_decline's
    dip-side gate, but for the opposite failure mode -- see CLAUDE.md's
    Step 1 deviations."""
    if not (gross.direction >= MARGIN_STABLE_TOLERANCE and net.direction >= MARGIN_STABLE_TOLERANCE):
        return False
    return (
        robust_late_direction(gross_arr, MARGIN_TREND_WINDOW) >= MARGIN_STABLE_TOLERANCE
        and robust_late_direction(net_arr, MARGIN_TREND_WINDOW) >= MARGIN_STABLE_TOLERANCE
    )


def _classify_margins(gross_margin: list[float], net_margin: list[float], revenue_growing: bool) -> TrendResult:
    if len(gross_margin) < 2 or len(net_margin) < 2:
        return TrendResult("insufficient_data", 0)

    gross_arr = np.asarray(gross_margin, dtype=float)
    net_arr = np.asarray(net_margin, dtype=float)
    gross = _analyze_margin_series(gross_arr)
    net = _analyze_margin_series(net_arr)

    # Rule 1: a sustained multi-year decline anywhere must not be masked by
    # a later rebound -- UNLESS the decline has been durably reversed (see
    # _series_recovered). The sharp-decline check always runs first,
    # regardless of reversal status: a currently sharply-negative net
    # margin must never be excused by an unrelated gross-side recovery.
    if gross.sustained_decline or net.sustained_decline:
        if net.direction < MARGIN_SHARP_DECLINE and revenue_growing:
            return TrendResult("sharply_declining", 20)
        if not (_series_recovered(gross_arr, gross) and _series_recovered(net_arr, net)):
            return TrendResult("gradually_compressing", 60)
        # Exempted: durably reversed. Read straight off the stable/expanding
        # check below -- deliberately does NOT fall through to Rule 2,
        # whose per-series dip count has its own separately-known issues
        # (see CLAUDE.md) and would otherwise turn a confirmed recovery
        # into the WORST tier for a near-flat-but-positive ticker.
        if _stable_and_spike_robust(gross_arr, gross, net_arr, net):
            return TrendResult("stable_or_expanding", 100)
        return TrendResult("gradually_compressing", 60)

    # Rule 2: 2+ real dips in a series that still nets out flat overall is
    # genuine directionless chaos -- reserved for the bottom tier. Requires
    # BOTH series to show the pattern, not either alone -- an OR here let one
    # choppy series veto an unambiguously improving other series (e.g. GOOGL:
    # net margin nearly doubled, scored 0 anyway because gross was choppy).
    # Confirmed via live data that no ticker in the dataset currently
    # satisfies both conditions at once -- this tier is reserved for genuine
    # simultaneous dual-metric chaos, not one noisy series alone.
    if (gross.num_real_dips >= 2 and abs(gross.direction) < MARGIN_FLAT_DIRECTION) and (
        net.num_real_dips >= 2 and abs(net.direction) < MARGIN_FLAT_DIRECTION
    ):
        return TrendResult("wildly_inconsistent", 0)

    if _stable_and_spike_robust(gross_arr, gross, net_arr, net):
        return TrendResult("stable_or_expanding", 100)

    if net.direction < MARGIN_SHARP_DECLINE and revenue_growing:
        return TrendResult("sharply_declining", 20)

    return TrendResult("gradually_compressing", 60)


def _classify_fcf(fcf: list[float]) -> TrendResult:
    """FCF tiering: all-positive -> Excellent; a single isolated negative
    year -> Good (a one-off blip, not a pattern); any run of 2+ consecutive
    negative years anywhere in the window -> Fail; negative years present
    but never 2 in a row (e.g. two scattered, non-adjacent negative years)
    -> Marginal. Checking max-consecutive-run first means "exactly 1
    negative year" and "2+ scattered negative years" fall out directly from
    the count, since a lone negative year can never itself form a run >= 2."""
    if len(fcf) < 2:
        return TrendResult("insufficient_data", 0)

    negative_years = sum(1 for v in fcf if v < 0)
    if negative_years == 0:
        return TrendResult("consistently_positive", FCF_EXCELLENT_SCORE)

    max_consecutive = 0
    current_run = 0
    for v in fcf:
        if v < 0:
            current_run += 1
            max_consecutive = max(max_consecutive, current_run)
        else:
            current_run = 0

    if max_consecutive >= 2:
        return TrendResult("sustained_cash_burn", FCF_FAIL_SCORE)

    if negative_years == 1:
        return TrendResult("isolated_dip", FCF_GOOD_SCORE)

    return TrendResult("scattered_negative_years", FCF_MARGINAL_SCORE)


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
    fcf: list[float] | None = None,
    margin_context_revenue: list[float] | None = None,
) -> dict:
    """Pure scoring function per CLAUDE.md's Step 1 spec: takes parsed metric
    series (chronological, oldest fiscal year -> TTM) and returns
    {score, verdict, components}. No I/O, no FMP/DB dependency.

    `margin_context_revenue` lets the caller feed a different series purely
    for the margin classifier's revenue_growing check than the one being
    trend-classified as "Revenue" -- used for Bank tickers, where `revenue`
    is actually Net Interest Income (see step1_data.py), but margins should
    still read against real revenue growth. Defaults to `revenue` itself,
    unchanged behavior for every other company type."""
    revenue_result = classify_trend(revenue)
    net_income_result = classify_trend(net_income)

    net_income_backup_used = False
    if net_income_result.score <= NET_INCOME_BACKUP_THRESHOLD:
        oi_result = classify_trend(operating_income)
        backup_score = min(NET_INCOME_BACKUP_CAP, max(net_income_result.score, oi_result.score))
        net_income_backup_used = backup_score != net_income_result.score
        net_income_result = TrendResult(net_income_result.pattern, backup_score)

    growth_reference = margin_context_revenue if margin_context_revenue is not None else revenue
    revenue_growing = growth_reference[-1] > growth_reference[0] if len(growth_reference) >= 2 else False
    margin_result = _classify_margins(gross_margin, net_margin, revenue_growing)

    if cfo_exempt or cfo is None:
        cfo_result = None
        fcf_result = None
        weights = WEIGHTS_CFO_EXEMPT
    else:
        cfo_result = classify_trend(cfo)
        fcf_result = _classify_fcf(fcf) if fcf is not None else None
        weights = WEIGHTS_STANDARD

    weighted_sum = (
        revenue_result.score * weights["revenue"]
        + net_income_result.score * weights["net_income"]
        + (cfo_result.score if cfo_result else 0) * weights["cfo"]
        + margin_result.score * weights["margins"]
        + (fcf_result.score if fcf_result else 0) * weights["fcf"]
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
            "fcf": {"score": fcf_result.score, "pattern": fcf_result.pattern} if fcf_result else None,
        },
        "weights": weights,
    }
