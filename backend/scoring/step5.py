from typing import NamedTuple

from scoring.classification import classify_company_type

# Score threshold for "Strong Pass" -- same convention as Step 1/Step 2's
# shared badge tiers (>90 Strong Pass, else Pass when not a hard fail).
STRONG_PASS_SCORE = 90

# --- Severity bands ----------------------------------------------------------
# Current Ratio, Debt/EBITDA, and Debt Servicing Ratio each used a single
# hard-fail threshold with no gradation beyond it. Replaced with a 3-zone
# read: Comfortable (unchanged sub-tiering below), Borderline (a real
# breach, but one a tiebreaker -- deferred revenue for Current Ratio,
# Interest Coverage for the other two -- can still save), and Severe (a
# breach far enough beyond the old threshold that no tiebreaker applies;
# always a hard Fail). The old single hard-fail boundary becomes each
# ratio's new *Comfortable* boundary -- nothing below it changes.
CURRENT_RATIO_COMFORTABLE = 1.0
CURRENT_RATIO_SEVERE = 0.7
DEBT_EBITDA_COMFORTABLE = 3.0
DEBT_EBITDA_SEVERE = 4.0
DSR_COMFORTABLE = 30.0
DSR_SEVERE = 40.0
# A borderline breach saved by its tiebreaker still isn't a clean pass --
# scored the same as the old "approaching_limit"/DSR mid-tier, distinct
# from every genuine Comfortable-zone sub-tier (70/85/100).
BORDERLINE_SAVED_SCORE = 60

# --- Interest Coverage Ratio (EBIT / Interest Expense, TTM) -------------------
# New tiebreaker for Debt/EBITDA and Debt Servicing Ratio's borderline zone
# only -- never applies to Current Ratio (whose tiebreaker is deferred
# revenue) and never overrides a Severe breach on either ratio. No doc-given
# numeric thresholds exist for ICR itself; >3x/1-3x/<1x are first-pass
# judgment calls, same status as Step 4's CCC thresholds.
ICR_SAFE = 3.0
ICR_DANGEROUS = 1.0

__all__ = [
    "classify_company_type",
    "RatioResult",
    "classify_interest_coverage",
    "score_current_ratio",
    "score_debt_to_ebitda",
    "score_debt_servicing",
    "score_gearing",
    "score_npl",
    "score_step5_standard",
    "score_step5_reit",
]


class RatioResult(NamedTuple):
    label: str
    points: int
    hard_fail: bool
    # True when a Borderline breach was excused by its tiebreaker (deferred
    # revenue for Current Ratio, Interest Coverage for the other two) --
    # drives the "Pass with caution" verdict, distinct from a clean Pass.
    saved_by_tiebreaker: bool = False


def classify_interest_coverage(icr: float | None) -> str:
    if icr is None:
        return "not_applicable"
    if icr > ICR_SAFE:
        return "safe"
    if icr >= ICR_DANGEROUS:
        return "tight"
    return "dangerous"


def _comfortable_current_ratio_tier(value: float) -> tuple[str, int]:
    if value < 1.5:
        return "acceptable", 70
    if value <= 2.0:
        return "good", 85
    return "excellent", 100


def score_current_ratio(raw_ratio: float, adjusted_ratio: float) -> RatioResult:
    """`adjusted_ratio` = current assets / (current liabilities - deferred
    revenue) -- computed by the caller (step5_data.py has the raw balance
    sheet figures; this stays a pure ratio-in, ratio-out function like
    every other scorer here). Equals raw_ratio when there's no deferred
    revenue, so behavior is unchanged for anyone without it."""
    if raw_ratio >= CURRENT_RATIO_COMFORTABLE:
        # Already comfortable on the RAW ratio -- score off raw, byte-
        # identical to before this redesign. Deferred revenue has nothing
        # to rescue here, so it must not perturb an already-fine score.
        label, points = _comfortable_current_ratio_tier(raw_ratio)
        return RatioResult(label, points, False)
    if adjusted_ratio >= CURRENT_RATIO_COMFORTABLE:
        # Raw was NOT comfortable, but deferred revenue rescues it -- score
        # off the adjusted ratio, since that's the basis for the rescue.
        label, points = _comfortable_current_ratio_tier(adjusted_ratio)
        return RatioResult(label, points, False, saved_by_tiebreaker=True)
    if adjusted_ratio >= CURRENT_RATIO_SEVERE:
        return RatioResult("borderline_fail", 0, True)
    return RatioResult("severe", 0, True)


def score_debt_to_ebitda(value: float, icr_is_safe: bool) -> RatioResult:
    if value <= DEBT_EBITDA_COMFORTABLE:
        if value > 2.0:
            return RatioResult("acceptable", 70, False)
        if value > 1.0:
            return RatioResult("good", 85, False)
        return RatioResult("excellent", 100, False)
    if value <= DEBT_EBITDA_SEVERE:
        if icr_is_safe:
            return RatioResult("borderline_saved_by_icr", BORDERLINE_SAVED_SCORE, False, saved_by_tiebreaker=True)
        return RatioResult("borderline_fail", 0, True)
    return RatioResult("severe", 0, True)


def score_debt_servicing(value_pct: float, icr_is_safe: bool) -> RatioResult:
    if value_pct < DSR_COMFORTABLE:
        if value_pct >= 20.0:
            return RatioResult("approaching_limit", 60, False)
        if value_pct >= 10.0:
            return RatioResult("good", 85, False)
        return RatioResult("excellent", 100, False)
    if value_pct < DSR_SEVERE:
        if icr_is_safe:
            return RatioResult("borderline_saved_by_icr", BORDERLINE_SAVED_SCORE, False, saved_by_tiebreaker=True)
        return RatioResult("borderline_fail", 0, True)
    return RatioResult("severe", 0, True)


def score_gearing(value_pct: float) -> RatioResult:
    if value_pct < 30.0:
        return RatioResult("excellent", 100, False)
    if value_pct <= 40.0:
        return RatioResult("good", 85, False)
    if value_pct <= 45.0:
        return RatioResult("approaching_limit", 60, False)
    return RatioResult("fail", 0, True)


def score_npl(value_pct: float) -> RatioResult:
    """NPL ratio tiers, mirroring Debt/EBITDA's excellent/good/acceptable/
    fail structure (both are higher-is-worse ratios). The source doc's own
    threshold is <5% = pass, so >=5% is the hard-fail boundary; the
    sub-tiers above that are first-pass judgment calls, same status as
    Step 4's CCC thresholds (no doc-given numeric gradation exists).
    This is a partial signal only -- CET1 is still unavailable for Banks,
    so this ratio alone never produces a Bank verdict (see step5_data.py)."""
    if value_pct >= 5.0:
        return RatioResult("fail", 0, True)
    if value_pct >= 3.0:
        return RatioResult("acceptable", 70, False)
    if value_pct >= 1.0:
        return RatioResult("good", 85, False)
    return RatioResult("excellent", 100, False)


def _verdict_for(score: int, hard_fail: bool, saved_by_tiebreaker: bool) -> str:
    # Hard-fail overrides the blended score entirely -- mirrors the Step 2
    # fix (CLAUDE.md's "Scoring rubric deviations"): a breached hard limit
    # must never be diluted by averaging with healthy ratios. A Borderline
    # breach excused by its tiebreaker is a distinct third state -- not a
    # clean Pass (a real breach did occur), not a Fail (a tiebreaker
    # resolved it) -- checked before the Strong Pass threshold since a
    # saved breach should never read as a Strong Pass regardless of score.
    if hard_fail:
        return "Fail"
    if saved_by_tiebreaker:
        return "Pass with caution"
    if score > STRONG_PASS_SCORE:
        return "Strong Pass"
    return "Pass"


def score_step5_standard(
    current_ratio: float,
    adjusted_current_ratio: float,
    debt_to_ebitda: float,
    debt_servicing_pct: float,
    interest_coverage_ratio: float | None,
) -> dict:
    """Pure scoring function for Step 5's Standard-company path. No I/O, no
    FMP/DB dependency -- mirrors score_step1/score_step2's shape.
    `adjusted_current_ratio` and `interest_coverage_ratio` are precomputed
    by the caller (step5_data.py has the raw balance sheet/income figures)."""
    icr_is_safe = interest_coverage_ratio is not None and interest_coverage_ratio > ICR_SAFE
    cr = score_current_ratio(current_ratio, adjusted_current_ratio)
    de = score_debt_to_ebitda(debt_to_ebitda, icr_is_safe)
    ds = score_debt_servicing(debt_servicing_pct, icr_is_safe)
    hard_fail = cr.hard_fail or de.hard_fail or ds.hard_fail
    # Both ratios share the SAME icr_is_safe signal (one shared confidence
    # check, not two independent ones) -- if both are borderline, ICR must
    # clear the bar to save both at once, never just one.
    saved_by_tiebreaker = cr.saved_by_tiebreaker or de.saved_by_tiebreaker or ds.saved_by_tiebreaker
    score = round((cr.points + de.points + ds.points) / 3)
    return {
        "score": score,
        "verdict": _verdict_for(score, hard_fail, saved_by_tiebreaker),
        "hard_fail": hard_fail,
        "pass_with_caution": not hard_fail and saved_by_tiebreaker,
        "ratios": {
            "current_ratio": {
                "value": current_ratio,
                "adjusted_value": adjusted_current_ratio,
                "label": cr.label,
                "points": cr.points,
                "saved_by_tiebreaker": cr.saved_by_tiebreaker,
            },
            "debt_to_ebitda": {
                "value": debt_to_ebitda,
                "label": de.label,
                "points": de.points,
                "saved_by_tiebreaker": de.saved_by_tiebreaker,
            },
            "debt_servicing_ratio": {
                "value": debt_servicing_pct,
                "label": ds.label,
                "points": ds.points,
                "saved_by_tiebreaker": ds.saved_by_tiebreaker,
            },
            "interest_coverage_ratio": {
                "value": interest_coverage_ratio,
                "label": classify_interest_coverage(interest_coverage_ratio),
            },
        },
    }


def score_step5_reit(gearing_pct: float) -> dict:
    """Pure scoring function for Step 5's REIT/Property Developer path."""
    g = score_gearing(gearing_pct)
    return {
        "score": g.points,
        "verdict": _verdict_for(g.points, g.hard_fail, False),
        "hard_fail": g.hard_fail,
        "ratios": {
            "gearing_ratio": {"value": gearing_pct, "label": g.label, "points": g.points},
        },
    }
