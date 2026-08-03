import numpy as np

from scoring.series_trend import analyze_series_direction, robust_late_direction
from scoring.trend import RECOVERY_PATTERNS, TrendResult, classify_trend, most_recent_real_dip_age

# Revenue > CFO > Net Income priority hierarchy per a refined reading of
# the methodology doc: Revenue is the foundation ("if revenue isn't
# growing, the business is shrinking"); CFO is weighted above Net Income
# since it's "the actual cash the business generates," while Net Income is
# explicitly "most susceptible to distortion" (one-off gains/losses, tax
# anomalies, non-operating items) -- see the Operating-Income backup
# mechanism below, which already exists for exactly this reason. Margins
# stay a lower-weight supporting indicator (unchanged); FCF drops to the
# smallest weight, matching its own simpler role (a positive/negative
# check, not a growth trend -- see _classify_fcf). Was
# {0.25, 0.25, 0.25, 0.10, 0.15}. Verified via a full 427-ticker simulation
# before adopting: real trade-offs exist (10 tickers flip Pass->Fail,
# e.g. AMGN: Net Income 75 via Operating-Income backup vs CFO 40
# unresolved -- shifting weight toward the harder-to-distort CFO figure is
# the hierarchy working as intended there, not collateral damage).
WEIGHTS_STANDARD = {"revenue": 0.35, "net_income": 0.20, "cfo": 0.30, "margins": 0.10, "fcf": 0.05}
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
# FCF is "consistently positive," not a growth trend -- what matters per the
# doc's own rationale is whether a cash-burn stretch is sustained (2+
# CONSECUTIVE negative years = bankruptcy risk), not merely whether a
# negative year exists somewhere in the history. A qualifying run still
# fails outright if it's recent; an older one is excused only if
# classify_trend confirms the series has since durably recovered -- same
# recency-gate + classify_trend fallback Step 3's method-selection tree
# uses for CFO/Net Income/FCF (see scoring/step3.py).
FCF_EXCELLENT_SCORE = 100
FCF_GOOD_SCORE = 85
FCF_MARGINAL_SCORE = 60
FCF_FAIL_SCORE = 0
# A qualifying 2+-consecutive-negative-year run still fails outright if it
# ended within this many periods of TTM (too fresh to trust as resolved) --
# matches the "3" recency convention already used throughout this app
# (Step 3's NEGATIVE_VALUE_RECENCY_YEARS, Step 4's AR_RED_FLAG_RECENCY_WINDOW).
FCF_CASH_BURN_RECENCY_YEARS = 3
# Early-recovery baseline window for _fcf_durably_recovered, matching
# MARGIN_TREND_WINDOW's sizing convention (see _series_recovered).
FCF_RECOVERY_WINDOW = 3

NET_INCOME_BACKUP_THRESHOLD = 40
NET_INCOME_BACKUP_CAP = 80
# "1 or 2 years in the past" -- deliberately includes age 0 (the dip
# landing in the TTM transition itself). Excluding age 0 would mean the
# single most common one-off shape -- a charge that just hit the LATEST
# reported period -- could never qualify for the Operating Income
# fallback, which reads as an unintended gap rather than an intended
# exclusion.
NET_INCOME_BACKUP_RECENCY_YEARS = 2

# classify_trend is purely relative/directional -- it only asks whether a
# series has grown/recovered relative to its OWN prior points, never
# whether the values themselves are positive. A company whose Net Income
# has never once been profitable but is trending toward breakeven (e.g.
# SYM: -104.4M(FY19) -> ... -> -4.97M TTM, each "dip" a relative
# worsening that later reverses) reads as multiple_dips_resolved/75 --
# indistinguishable from a company that actually turned the corner into
# real profitability. Revenue, Net Income, and CFO must be positive AND
# increasing: a historical dip is still tolerated (even one that went
# negative mid-dip) as long as the series has since recovered per
# classify_trend's OWN unchanged dip-tolerance tiers AND the current/TTM
# value clears zero. This is a hard gate layered on top of classify_trend,
# not a replacement for its tiers.
NOT_YET_POSITIVE_SCORE = 0  # mirrors `declining`'s existing hard-fail-style 0


def _classify_positive_trend(values: list[float]) -> TrendResult:
    trend = classify_trend(values)
    if trend.pattern == "insufficient_data":
        return trend
    if values[-1] <= 0:
        return TrendResult("not_yet_positive", NOT_YET_POSITIVE_SCORE)
    return trend

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


def _fcf_durably_recovered(fcf: list[float], run_end: int) -> bool:
    """Recovery check for a cash-burn run that classify_trend's full-series
    read rejects SOLELY because of its own blunt "any TTM decline is
    disqualifying" rule -- which doesn't distinguish an old, resolved burn
    stretch followed by years of robust positive FCF from a genuinely fresh
    decline (e.g. TSLA: an 8-year-old burn, 6 straight recovered years,
    capped by a mere -7.4% TTM dip vs. last FY; GE: a -50% TTM pullback that
    still lands well above its own early-recovery baseline). Three
    conditions, all required:

    1. Every year since the run ended -- including TTM -- must itself be
       non-negative. This is what actually distinguishes "durable recovery,
       one wobble year" from a company that's still periodically lurching
       negative (e.g. PEG: a capex-heavy utility whose "post-burn" years
       include a further -$1.25B year and a negative TTM -- superficially
       past FCF_CASH_BURN_RECENCY_YEARS since its last 2+-consecutive run,
       but nowhere near "solidly positive since"). Without this gate, a
       negative value hiding in the post-burn window can also drag the
       baseline in condition 3 negative, making an also-negative TTM look
       like it clears the baseline.
    2. Dropping the TTM period, does the series independently read as a
       recovered classify_trend pattern? This confirms the run was already
       durably resolved BEFORE this year's wobble, rather than merely
       looking recovered because TTM's decline hasn't yet compounded into a
       second bad year. A genuinely still-declining series (DE, AIG) fails
       here too -- their unresolved dips sit in the recovery years
       themselves (an interim peak TTM hasn't reclaimed), not just the
       final wobble year, so dropping TTM alone doesn't fix their read.
    3. Has TTM fallen back below the early post-burn recovery baseline?
       Mirrors _series_recovered's early-window-baseline pattern (same
       window size) -- a wobble that's merely off last year's number is
       tolerable, but craters back toward the original burn level are not,
       regardless of how the pre-TTM series reads on its own.
    """
    post_burn = fcf[run_end + 1 :]
    if any(v < 0 for v in post_burn):
        return False
    pre_ttm_trend = classify_trend(fcf[:-1])
    if pre_ttm_trend.pattern not in RECOVERY_PATTERNS:
        return False
    w = min(FCF_RECOVERY_WINDOW, len(post_burn))
    baseline = float(np.mean(post_burn[:w]))
    return fcf[-1] >= baseline


def _classify_fcf(fcf: list[float]) -> TrendResult:
    """FCF tiering: all-positive -> Excellent; a single isolated negative
    year -> Good (a one-off blip, not a pattern); negative years present
    but never 2 in a row (e.g. two scattered, non-adjacent negative years)
    -> Marginal; a run of 2+ consecutive negative years -> Fail, UNLESS that
    run ended more than FCF_CASH_BURN_RECENCY_YEARS ago AND either
    classify_trend confirms the full series has since durably recovered
    (e.g. AMD's FY2017/2018, since fully recovered to $8.57B TTM FCF), or
    _fcf_durably_recovered confirms it recovered before a since-tolerable
    single-year TTM wobble (e.g. TSLA, TMUS, GE -- see that function) -- an
    old, resolved cash-burn stretch shouldn't permanently read as an ongoing
    bankruptcy-risk signal just because the latest year alone dipped. A run
    too recent to trust as resolved still fails outright, same as everywhere
    else in this app."""
    if len(fcf) < 2:
        return TrendResult("insufficient_data", 0)

    negative_years = sum(1 for v in fcf if v < 0)
    if negative_years == 0:
        return TrendResult("consistently_positive", FCF_EXCELLENT_SCORE)

    # Track where each qualifying 2+-consecutive-negative run ENDS, not just
    # whether one exists -- recency is judged off the most recent such run.
    run_end_indices: list[int] = []
    run_start = None
    for i, v in enumerate(fcf):
        if v < 0:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start >= 2:
                run_end_indices.append(i - 1)
            run_start = None
    if run_start is not None and len(fcf) - run_start >= 2:
        run_end_indices.append(len(fcf) - 1)

    if run_end_indices:
        run_end = max(run_end_indices)
        years_since_run_end = (len(fcf) - 1) - run_end
        if years_since_run_end <= FCF_CASH_BURN_RECENCY_YEARS:
            return TrendResult("sustained_cash_burn", FCF_FAIL_SCORE)
        trend = classify_trend(fcf)
        if trend.pattern in RECOVERY_PATTERNS or _fcf_durably_recovered(fcf, run_end):
            return TrendResult("cash_burn_recovered", FCF_GOOD_SCORE)
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
    revenue_result = _classify_positive_trend(revenue)
    net_income_pos_result = _classify_positive_trend(net_income)

    net_income_result = net_income_pos_result
    net_income_backup_used = False
    oi_pos_result = None
    ni_is_insufficient = net_income_pos_result.pattern == "insufficient_data"
    # The OI fallback is recency-gated -- it exists for a genuine one-off
    # dip 1-2 years back, not a chronic negative/declining Net Income
    # history -- EXCEPT when NI has too few points to have any notion of
    # "recency" at all, where today's unconditional "always check OI"
    # behavior is preserved unchanged (see the insufficient_data comment
    # below).
    ni_dip_age = None if ni_is_insufficient else most_recent_real_dip_age(net_income)
    ni_recent_enough = ni_is_insufficient or (
        ni_dip_age is not None and ni_dip_age <= NET_INCOME_BACKUP_RECENCY_YEARS
    )
    if net_income_pos_result.score <= NET_INCOME_BACKUP_THRESHOLD and ni_recent_enough:
        oi_pos_result = _classify_positive_trend(operating_income)
        backup_score = min(NET_INCOME_BACKUP_CAP, max(net_income_pos_result.score, oi_pos_result.score))
        net_income_backup_used = backup_score != net_income_pos_result.score
        net_income_result = TrendResult(net_income_pos_result.pattern, backup_score)

    # Net Income only reads as a genuine data gap if BOTH it and its own
    # Operating-Income backup came up short -- if OI has real data, the
    # backup mechanism above already produced a legitimate (if low) score,
    # not a fabricated one.
    net_income_insufficient = ni_is_insufficient and (
        oi_pos_result is None or oi_pos_result.pattern == "insufficient_data"
    )

    growth_reference = margin_context_revenue if margin_context_revenue is not None else revenue
    revenue_growing = growth_reference[-1] > growth_reference[0] if len(growth_reference) >= 2 else False
    margin_result = _classify_margins(gross_margin, net_margin, revenue_growing)

    if cfo_exempt or cfo is None:
        cfo_result = None
        fcf_result = None
        weights = WEIGHTS_CFO_EXEMPT
    else:
        cfo_result = _classify_positive_trend(cfo)
        fcf_result = _classify_fcf(fcf) if fcf is not None else None
        weights = WEIGHTS_STANDARD

    # A fetch failure (cache.py::safe_fetch swallows httpx.HTTPError to {})
    # and a genuinely too-thin real response both collapse to the same
    # classify_trend/_classify_fcf "insufficient_data" pattern -- previously
    # that pattern's score of 0 was folded into the weighted sum below like
    # any other real (if bad) result, fabricating a scored Fail out of a
    # data gap (mirrors the bug already fixed in Step 2 -- see CLAUDE.md).
    # cfo/fcf are only "required" when not cfo-exempt; an exemption is not
    # a gap. fcf_result being None (not cfo-exempt, but no fcf series
    # supplied at all) is a distinct, pre-existing "FCF isn't being scored"
    # convention -- step1_data.py's real caller never actually passes
    # fcf=None unless cfo_exempt is also True, so this branch only exists
    # for direct scoring-function callers (tests) that omit the optional
    # fcf param; it isn't a reachable fetch-failure/data-gap shape and
    # shouldn't gate the whole step.
    cfo_fcf_applicable = not (cfo_exempt or cfo is None)
    cfo_insufficient = cfo_fcf_applicable and cfo_result.pattern == "insufficient_data"
    fcf_insufficient = cfo_fcf_applicable and fcf_result is not None and fcf_result.pattern == "insufficient_data"

    if (
        revenue_result.pattern == "insufficient_data"
        or net_income_insufficient
        or margin_result.pattern == "insufficient_data"
        or cfo_insufficient
        or fcf_insufficient
    ):
        return {"score": None, "verdict": "insufficient_data", "components": {}, "weights": weights}

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
