from typing import NamedTuple

import numpy as np

from scoring.series_trend import analyze_series_direction, robust_late_direction
from scoring.trend import RECOVERY_PATTERNS, TrendResult, classify_trend

# --- ROE / ROIC tiers (percent) ---------------------------------------------
ROE_EXCELLENT_AVG = 15.0
ROE_GOOD_AVG = 12.0
ROE_MARGINAL_AVG = 8.0
ROE_MIN_YEAR_CONSISTENCY = 8.0
# ROE/ROIC's avg+min-year tiering had no trend awareness at all -- the only
# "consistently X%" check in the app that worked this way (everything else
# is now direction-aware after this session's Margins/CCC fixes). Two
# distinct failure modes, confirmed via live data, need two distinct
# mechanisms (mirrors Margins needing both Rule 1's durable-reversal gate
# AND a separate late-window spike guard -- not one trick fixing both):
#
# 1. A single anomalous high year inflates the plain average enough to
#    reach a higher tier (MPWR: a one-time tax benefit took ROE's average
#    from 17.5% to 21.1%). ROE_SPIKE_RATIO_THRESHOLD gates this -- only the
#    series MAXIMUM is ever a candidate for exclusion (never the minimum:
#    ROE_MIN_YEAR_CONSISTENCY already exists specifically to catch a single
#    bad year, and excluding a low outlier here would silently undo that),
#    and only when it's genuinely extreme relative to the rest, not just
#    "whichever point happens to be most extreme" -- confirmed necessary
#    via live data: without the ratio gate, MPWR's own ROIC (a real 24.5%
#    cyclical peak, not an anomaly) was wrongly excluded too.
# 2. A severe, still-not-durably-recovered decline (INTU: ROE 84%->12.6%
#    trough, only partial recovery to 23.3% TTM) still scores "excellent"
#    since both average and single-worst-year clear their bars regardless
#    of trajectory. ROE_TREND_WINDOW/ROE_SUSTAINED_DECLINE_STEPS/POINTS
#    reuse analyze_series_direction's exact windowed-direction +
#    sustained-decline logic already used for Margins/CCC, tuned for
#    ROE/ROIC's own scale (much larger swings than margins). If a sustained
#    decline hasn't been reclaimed by TTM, the tier is capped one notch
#    down (excellent->good, good->marginal) -- but never demoted past
#    "marginal" into a manufactured hard-fail; "fail" only ever comes from
#    the doc's own absolute floor, never invented by a trend correction.
ROE_SPIKE_RATIO_THRESHOLD = 2.0
ROE_TREND_WINDOW = 3
ROE_DIP_POINTS = 5.0
ROE_SUSTAINED_DECLINE_STEPS = 2
ROE_SUSTAINED_DECLINE_POINTS = 15.0
# An old, since-recovered bad year (single low ROE/ROIC year, or a
# negative-equity-substitute loss year) shouldn't permanently disqualify --
# same recency-gate + classify_trend fallback Step 1/Step 3 use. Matches
# the app-wide "3" recency convention (AR_RED_FLAG_RECENCY_WINDOW below,
# Step 1's FCF_CASH_BURN_RECENCY_YEARS, Step 3's NEGATIVE_VALUE_RECENCY_YEARS).
DIP_RECOVERY_RECENCY_YEARS = 3

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
# strong_red_flag (revenue declining while AR grows in the same year) had no
# recency awareness -- a single real-but-old occurrence (e.g. NVDA's FY2020
# crypto/gaming glut, 8 of 10 transitions old) permanently forced a hard 0
# regardless of everything since. Reuses the same 3-FY "recent" window
# CCC_TREND_WINDOW/MARGIN_TREND_WINDOW already use elsewhere in the app,
# rather than inventing a new convention.
AR_RED_FLAG_RECENCY_WINDOW = 3

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
# --- CCC sign-awareness (2026-08-01) ------------------------------------------
# A negative CCC isn't a milder version of positive CCC -- it's the opposite
# signal: the company collects from customers before paying its own
# suppliers, so suppliers are effectively funding the business. The trend-only
# classification above has no awareness of this and scores a company whose
# CCC is deeply negative and drifting toward zero (AAPL: -84 to -54 days,
# still elite) identically to one whose CCC is genuinely positive and rising
# -- confirmed AAPL's Step 4 score was dragged to 50 (0/100 ROE, 0/100 ROIC,
# but CCC read "sustained_upward", 0) purely from this blind spot. All three
# constants below were derived from a real, cache-only sweep of all 318
# CCC-scorable tickers in the universe, not guessed -- see CLAUDE.md's Step 4
# deviations for the full threshold-selection writeup.
CCC_SIGN_EPS_DAYS = 1.0  # tolerance for "effectively zero" (case 1/2 purity + settling materiality)
CCC_NEAR_ZERO_AMPLITUDE_DAYS = 10.0  # near-zero-oscillation band (COST/TGT-shape)
CCC_SPIKE_ISOLATION_RATIO = 3.0  # single-outlier-vs-typical-magnitude ratio to rescue back to case 1/2

STRONG_PASS_SCORE = 90


class RatioResult(NamedTuple):
    label: str
    points: int
    hard_fail: bool


def _min_year_consistency_satisfied(valid: list[float], min_year: float) -> bool:
    """min_year clearing ROE_MIN_YEAR_CONSISTENCY is the literal bar; but a
    single old, since-recovered bad year (e.g. MPWR-style) shouldn't
    permanently disqualify an otherwise-strong average -- same recency-gate
    + classify_trend fallback Step 3 uses for CFO/Net Income/FCF. A RECENT
    low year still disqualifies outright; an older one is excused only if
    classify_trend confirms a durable recovery since. Uses the LAST index
    where the series hits min_year (not the first), so a value that recurs
    both early and late in the window is correctly read as recent."""
    if min_year >= ROE_MIN_YEAR_CONSISTENCY:
        return True
    min_indices = [i for i, v in enumerate(valid) if v == min_year]
    years_since_min = (len(valid) - 1) - max(min_indices)
    if years_since_min <= DIP_RECOVERY_RECENCY_YEARS:
        return False
    trend = classify_trend(valid)
    return trend.pattern in RECOVERY_PATTERNS


def _score_avg_min_tier(valid: list[float], avg: float, min_year: float) -> tuple[str, int, bool]:
    consistent = _min_year_consistency_satisfied(valid, min_year)
    if avg > ROE_EXCELLENT_AVG and consistent:
        return "excellent", 100, False
    if avg >= ROE_GOOD_AVG and consistent:
        return "good", 85, False
    if avg >= ROE_MARGINAL_AVG:
        return "marginal", 60, False
    return "fail", 0, True


def _spike_robust_avg(values: list[float]) -> float:
    """The plain average, but with the series MAXIMUM excluded when it's
    >=2x the median of the rest -- an anomalous high year (e.g. a one-time
    tax benefit) can't inflate the average into a higher tier on its own.
    Never excludes the minimum -- see this module's ROE/ROIC comment block
    for why that would undo the min-year consistency floor."""
    arr = np.asarray(values, dtype=float)
    if len(arr) < 3:
        return float(arr.mean())
    idx = int(np.argmax(arr))
    others = np.delete(arr, idx)
    others_median = float(np.median(others))
    if others_median > 0 and arr[idx] / others_median >= ROE_SPIKE_RATIO_THRESHOLD:
        return float(others.mean())
    return float(arr.mean())


_TIER_DEMOTION = {"excellent": ("good", 85), "good": ("marginal", 60)}


def _demote_for_unrecovered_decline(values: list[float], label: str, points: int) -> tuple[str, int]:
    """Caps a tier one notch down (excellent->good, good->marginal -- never
    past marginal) when a sustained decline hasn't been reclaimed by TTM.
    Reuses analyze_series_direction's exact sustained-decline detection
    (as Margins/CCC do), tuned for ROE/ROIC's own scale."""
    if label not in _TIER_DEMOTION:
        return label, points
    arr = np.asarray(values, dtype=float)
    analysis = analyze_series_direction(
        arr, ROE_TREND_WINDOW, ROE_DIP_POINTS, ROE_SUSTAINED_DECLINE_STEPS, ROE_SUSTAINED_DECLINE_POINTS
    )
    w = min(ROE_TREND_WINDOW, len(arr))
    early_avg = float(arr[:w].mean())
    if analysis.sustained_decline and arr[-1] < early_avg:
        return _TIER_DEMOTION[label]
    return label, points


def _net_income_consistent_and_positive(net_income: list[float]) -> bool:
    """Substitute signal for ROE when equity is negative anywhere in the
    window: positive throughout (or an old, since-recovered loss year --
    same recency-gate + classify_trend fallback used elsewhere in this
    app), and net growth over the window when no loss occurred at all
    (last >= first, deliberately the same simple bar Step 1 uses for
    revenue_growing, not a full trend classifier, since the doc's own
    language ("consistently maintained/growing") is qualitative)."""
    if not net_income:
        return False
    negative_indices = [i for i, v in enumerate(net_income) if v <= 0]
    if not negative_indices:
        return net_income[-1] >= net_income[0]
    years_since_negative = (len(net_income) - 1) - max(negative_indices)
    if years_since_negative <= DIP_RECOVERY_RECENCY_YEARS:
        return False
    trend = classify_trend(net_income)
    return trend.pattern in RECOVERY_PATTERNS


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
    avg = _spike_robust_avg(valid)
    min_year = min(valid)
    label, points, hard_fail = _score_avg_min_tier(valid, avg, min_year)
    label, points = _demote_for_unrecovered_decline(valid, label, points)
    return RatioResult(label, points, hard_fail)


def score_roic(roic: list[float]) -> RatioResult:
    valid = [v for v in roic if v is not None]
    if not valid:
        return RatioResult("insufficient_data", 0, False)
    avg = _spike_robust_avg(valid)
    min_year = min(valid)
    label, points, hard_fail = _score_avg_min_tier(valid, avg, min_year)
    label, points = _demote_for_unrecovered_decline(valid, label, points)
    return RatioResult(label, points, hard_fail)


def check_roe_roic_divergence(roe: RatioResult, roic: RatioResult | None) -> str | None:
    """Surfaces the doc's own ROIC rationale ("closes a blind spot... a
    company can inflate ROE by loading up on debt to fund buybacks") as an
    explicit, informational flag -- never a score/verdict change, since
    ROIC's own tier already pulls the blend down and a real penalty would
    double-count it.

    Tier-relative, not a raw pp gap or ratio: live-data investigation found
    a fixed gap threshold can't separate genuine leverage stories (SYY: ROE
    66/ROIC 12, both real) from clean compounders with a naturally large
    gap (MA: ROE 139/ROIC 41, both "excellent" -- ROIC is elite in absolute
    terms despite the huge gap to ROE). Comparing tiers instead does
    separate them cleanly. Only fires on ROIC == "marginal": a "fail" ROIC
    already trips score_step4's hard-fail override on its own (no need to
    double-flag), and ROIC == "good"/"excellent" isn't a real divergence
    even when ROE is one tier higher (too common, not clearly meaningful --
    confirmed via live data). roic=None (Bank/Insurance/Utility/REIT
    exemption) and non-tier ROE labels (the negative-equity substitute
    paths) never match this condition, so both are naturally exempt without
    special-casing.
    """
    if roic is None or roic.label != "marginal" or roe.label not in ("excellent", "good"):
        return None
    return (
        f"ROE ({roe.label}) is notably stronger than ROIC ({roic.label}) — "
        "may indicate leverage or buybacks are inflating equity returns "
        "rather than genuine capital efficiency."
    )


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
       grows in the same year within the last AR_RED_FLAG_RECENCY_WINDOW
       transitions -> 0 (auto-escalate regardless of count). An old,
       resolved occurrence outside that window no longer counts on its own.
    2. `concerning_threshold`+ transitions outpacing (proportional to the
       window size -- see AR_CONCERNING_TRANSITION_RATIO), OR any single
       large-magnitude (>50pp) gap -> 40. Same recency exemption as rule 1:
       if every qualifying transition (count- or large-gap-driving) falls
       outside the last AR_RED_FLAG_RECENCY_WINDOW transitions, this is an
       old, since-resolved pattern, not a live concern, and falls through
       to rules 3/4 using the still-intact full-window gap list. In
       practice the count-based trigger alone can never reach this rule
       without also tripping rule 1's majority check first (concerning_
       threshold sits at or above the 50% majority line at every window
       size), so this exemption is only ever reachable via has_large.
    3. 0 outpacing transitions, or exactly 1 isolated year with a small
       (<=15pp) gap -> 100.
    4. Otherwise (1-2 outpacing transitions, not caught above) -> 70.
    """
    n = len(revenue) - 1
    if n < 1 or len(accounts_receivable) != len(revenue):
        return RatioResult("insufficient_data", 0, False)

    outpacing_gaps: list[tuple[int, float]] = []
    strong_red_flag = False
    for i in range(n):
        prev_rev, curr_rev = revenue[i], revenue[i + 1]
        prev_ar, curr_ar = accounts_receivable[i], accounts_receivable[i + 1]
        if not prev_rev or not prev_ar:
            continue
        revenue_yoy = (curr_rev - prev_rev) / abs(prev_rev) * 100
        ar_yoy = (curr_ar - prev_ar) / abs(prev_ar) * 100
        if revenue_yoy < 0 and ar_yoy > 0 and i >= n - AR_RED_FLAG_RECENCY_WINDOW:
            strong_red_flag = True
        gap = ar_yoy - revenue_yoy
        if gap > AR_GAP_NOISE_FLOOR:
            outpacing_gaps.append((i, gap))

    all_gaps = [g for _, g in outpacing_gaps]
    num_outpacing = len(all_gaps)
    has_large = any(_ar_gap_magnitude(g) == "large" for g in all_gaps)
    majority_outpacing = num_outpacing > n / 2
    # floor of 3: below a 5-transition window, "3+" was never reachable via
    # count anyway (n=1-2 can't produce 3 outpacing transitions), so the
    # ratio must not round down below the original absolute floor.
    concerning_threshold = max(3, round(AR_CONCERNING_TRANSITION_RATIO * n))

    if majority_outpacing or strong_red_flag:
        return RatioResult("outpacing_majority_or_red_flag", 0, False)
    if num_outpacing >= concerning_threshold or has_large:
        recent_gaps = [g for i, g in outpacing_gaps if i >= n - AR_RED_FLAG_RECENCY_WINDOW]
        if recent_gaps:
            return RatioResult("outpacing_concerning", 40, False)
    if num_outpacing == 0:
        return RatioResult("healthy", 100, False)
    if num_outpacing == 1 and _ar_gap_magnitude(all_gaps[0]) == "small":
        return RatioResult("healthy", 100, False)
    return RatioResult("outpacing_isolated", 70, False)


def _classify_positive_ccc_trend(ccc: list[float]) -> TrendResult:
    """CCC classification for a consistently-positive series (case 2 of
    classify_ccc_trend's sign-profile split): reuses the exact early/late-
    direction + dip-count + sustained-decline logic built for Step 1's
    margin classifier, run on the negated series -- a declining CCC (faster
    cash conversion) is the good direction here, the inverse of margins.
    Unchanged from before this module's sign-awareness split -- this is the
    NVDA/IDXX path (real, genuinely positive-and-rising CCC)."""
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
        # Spike guard: the mirror-image of Rule 1's dip-side gate -- a single
        # anomalous good-side CCC point in the late window (e.g. one wildly
        # negative TTM quarter) can flip `direction` positive even when the
        # rest of the window shows a flat or genuinely worsening trend (real
        # cases: ABBV, CDNS). Deliberately restricted to tickers that never
        # triggered sustained_decline above -- applying it unconditionally
        # would also re-touch cases already resolved by Rule 1's own gate
        # (confirmed: NEM, one of the originally-fixed 17, would otherwise
        # flip back to 0), which must stay exactly as already fixed.
        if not analysis.sustained_decline and robust_late_direction(negated, CCC_TREND_WINDOW) < CCC_STABLE_TOLERANCE_DAYS:
            return TrendResult("sustained_upward", 0)
        if analysis.num_real_dips >= 1:
            return TrendResult("volatile_but_net_declining", 70)
        return TrendResult("declining_or_stable", 100)

    # Net worsening direction, not caught by the strict sustained check above
    # (e.g. a slow multi-year creep) -- still reads as an upward CCC trend.
    return TrendResult("sustained_upward", 0)


def _window_direction(arr: np.ndarray, window: int) -> float:
    """Late-window average minus early-window average on the RAW (non-
    negated) series -- mirrors analyze_series_direction's own early/late
    slice exactly, but that shared function's dip-count/sustained-decline
    params aren't meaningful for case 1's simple strengthening/weakening
    read, so a 2-line local duplicate is clearer than threading dummy
    values through it."""
    w = min(window, len(arr))
    return float(arr[-w:].mean() - arr[:w].mean())


def _consistently_negative_result(arr: np.ndarray) -> TrendResult:
    """Case 1: CCC stays at/below zero (within CCC_SIGN_EPS_DAYS) for the
    whole window -- suppliers are funding the business throughout. Both
    getting-more-negative (strengthening) and getting-less-negative-but-
    still-solidly-negative (weakening, e.g. AAPL) score top-tier -- see
    CLAUDE.md's Step 4 deviations for why a still-deeply-negative CCC is
    never treated as a red flag just because its own direction eased."""
    direction = _window_direction(arr, CCC_TREND_WINDOW)
    if direction < 0:
        return TrendResult("consistently_negative_strengthening", 100)
    return TrendResult("consistently_negative_weakening", 100)


def _isolated_spike_index(arr: np.ndarray) -> int | None:
    """Returns the index of a single point sitting alone on the minority
    side of zero, if it's disproportionate (>= CCC_SPIKE_ISOLATION_RATIO x
    the majority side's typical magnitude) -- confirmed real case: ABBV,
    10yrs of 62-102 day positive CCC then one TTM value of -496.7 (an
    evident one-time acquisition-related accounting event). Returns None
    for genuine multi-point sign shifts (e.g. CDNS's 2 consecutive negative
    years), which must fall through to the settling/amplitude checks below,
    not be silently rescued."""
    neg_idx = np.flatnonzero(arr < -CCC_SIGN_EPS_DAYS)
    pos_idx = np.flatnonzero(arr > CCC_SIGN_EPS_DAYS)
    if len(neg_idx) == 1 and len(pos_idx) >= 3:
        typical = float(np.median(np.abs(arr[pos_idx])))
        if typical > 0 and abs(arr[neg_idx[0]]) >= CCC_SPIKE_ISOLATION_RATIO * typical:
            return int(neg_idx[0])
    if len(pos_idx) == 1 and len(neg_idx) >= 3:
        typical = float(np.median(np.abs(arr[neg_idx])))
        if typical > 0 and abs(arr[pos_idx[0]]) >= CCC_SPIKE_ISOLATION_RATIO * typical:
            return int(pos_idx[0])
    return None


def classify_ccc_trend(ccc: list[float]) -> TrendResult:
    """CCC classification, sign-profile-aware: a negative CCC means
    suppliers fund the business (the company collects from customers
    before paying them) -- the opposite signal from a positive CCC, not a
    milder version of it. Dispatches on the series' sign profile before
    applying any trend logic:

    1. Consistently negative throughout (within CCC_SIGN_EPS_DAYS) -- see
       _consistently_negative_result.
    2. Consistently positive throughout -- delegates to
       _classify_positive_ccc_trend, today's entire pre-sign-awareness
       logic, unchanged (the NVDA/IDXX path).
    3. Mixed (crosses the sign boundary): a single isolated outlier point
       is rescued back into case 1/2 first (see _isolated_spike_index),
       then a genuine sign crossing is sub-classified by whether it
       durably settled on one side (gained/lost bargaining power) or, if
       not, by whether its overall amplitude is negligible (COST/TGT-
       shape) or genuinely unclear (CCL-shape).

    See CLAUDE.md's Step 4 deviations for the full threshold-derivation
    writeup (all three CCC_SIGN_EPS_DAYS/CCC_NEAR_ZERO_AMPLITUDE_DAYS/
    CCC_SPIKE_ISOLATION_RATIO constants were derived from a real,
    cache-only sweep of the universe, not guessed).
    """
    if len(ccc) < 2:
        return TrendResult("insufficient_data", 0)

    arr = np.asarray(ccc, dtype=float)
    mn, mx = float(arr.min()), float(arr.max())

    if mx <= CCC_SIGN_EPS_DAYS:
        return _consistently_negative_result(arr)
    if mn >= -CCC_SIGN_EPS_DAYS:
        return _classify_positive_ccc_trend(ccc)

    spike_idx = _isolated_spike_index(arr)
    if spike_idx is not None:
        rescued = np.delete(arr, spike_idx)
        # The rescued series (minority point excluded) is now pure-signed by
        # construction -- but the classification itself still runs on the
        # FULL original series (including the outlier), matching how
        # _classify_positive_ccc_trend's own existing spike guard already
        # handles a late-window outlier internally, rather than stripping
        # real data out of what gets scored.
        if float(rescued.max()) <= CCC_SIGN_EPS_DAYS:
            return _consistently_negative_result(arr)
        return _classify_positive_ccc_trend(ccc)

    early = float(arr[: min(CCC_TREND_WINDOW, len(arr))].mean())
    # Robust late-window average: reuses the existing robust_late_direction
    # (already excludes the single most extreme late-window point vs. its
    # own median) by adding back the early-window average it nets against --
    # avoids duplicating that exclusion logic.
    late = robust_late_direction(arr, CCC_TREND_WINDOW) + early

    if early > CCC_SIGN_EPS_DAYS and late < -CCC_SIGN_EPS_DAYS:
        return TrendResult("gained_bargaining_power", 100)
    if early < -CCC_SIGN_EPS_DAYS and late > CCC_SIGN_EPS_DAYS:
        return TrendResult("lost_bargaining_power", 0)

    amplitude = max(abs(mn), abs(mx))
    if amplitude <= CCC_NEAR_ZERO_AMPLITUDE_DAYS:
        return TrendResult("negligible_working_capital", 85)
    return TrendResult("mixed_unclear", 40)


def _verdict_for(score: int, hard_fail: bool) -> str:
    if hard_fail:
        return "Fail"
    if score > STRONG_PASS_SCORE:
        return "Strong Pass"
    return "Pass"


def score_step4(
    roe: RatioResult,
    ar: RatioResult | None,
    roic: RatioResult | None,
    ccc: TrendResult | None,
) -> dict:
    """Pure scoring function: equal-weight redistribution among whatever
    metrics are applicable (all 4 -> 25% each; ROIC exempt -> remaining 3 at
    33.3% each; ROIC+CCC both exempt -> remaining 2 at 50% each; AR also
    exempt -- REIT -> remaining 1 at 100%), with a hard-fail override if
    ROE or ROIC (when applicable) lands in its Fail tier -- mirrors
    Step 2/Step 5's hard-fail override pattern. `ar=None` mirrors the
    roic/ccc optional-exemption pattern -- Revenue-vs-Accounts-Receivable
    isn't part of the REIT framework (a rental-income business model has no
    comparable receivables-outpacing-revenue concept), so it's excluded the
    same way CCC already is for REITs."""
    applicable: list[tuple[str, int]] = [("roe", roe.points)]
    if ar is not None:
        applicable.append(("ar", ar.points))
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
        "roe_roic_divergence_note": check_roe_roic_divergence(roe, roic),
        "components": {
            "roe": {"label": roe.label, "points": roe.points},
            "roic": {"label": roic.label, "points": roic.points} if roic is not None else None,
            "revenue_vs_ar": {"label": ar.label, "points": ar.points} if ar is not None else None,
            "ccc": {"pattern": ccc.pattern, "points": ccc.score} if ccc is not None else None,
        },
    }
