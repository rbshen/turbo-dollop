from typing import NamedTuple

# Score threshold for "Strong Pass" -- same convention as Step 1/Step 2's
# shared badge tiers (>90 Strong Pass, else Pass when not a hard fail).
STRONG_PASS_SCORE = 90


class RatioResult(NamedTuple):
    label: str
    points: int
    hard_fail: bool


def classify_company_type(sector: str | None, industry: str | None) -> str:
    """Best-effort sector/industry text match for Step 5's Step 0
    classification -- not a certified determination. A misclassified
    ticker would silently apply the wrong ratio set, so this is always
    surfaced in the UI/API, never hidden (see CLAUDE.md)."""
    sector = (sector or "").strip()
    industry_lower = (industry or "").strip().lower()
    if sector == "Financial Services" and "bank" in industry_lower:
        return "Bank"
    if sector == "Real Estate" or "reit" in industry_lower:
        return "REIT/Property Developer"
    return "Standard"


def score_current_ratio(value: float) -> RatioResult:
    if value < 1.0:
        return RatioResult("fail", 0, True)
    if value < 1.5:
        return RatioResult("acceptable", 70, False)
    if value <= 2.0:
        return RatioResult("good", 85, False)
    return RatioResult("excellent", 100, False)


def score_debt_to_ebitda(value: float) -> RatioResult:
    if value > 3.0:
        return RatioResult("fail", 0, True)
    if value > 2.0:
        return RatioResult("acceptable", 70, False)
    if value > 1.0:
        return RatioResult("good", 85, False)
    return RatioResult("excellent", 100, False)


def score_debt_servicing(value_pct: float) -> RatioResult:
    if value_pct >= 30.0:
        return RatioResult("fail", 0, True)
    if value_pct >= 20.0:
        return RatioResult("approaching_limit", 60, False)
    if value_pct >= 10.0:
        return RatioResult("good", 85, False)
    return RatioResult("excellent", 100, False)


def score_gearing(value_pct: float) -> RatioResult:
    if value_pct < 30.0:
        return RatioResult("excellent", 100, False)
    if value_pct <= 40.0:
        return RatioResult("good", 85, False)
    if value_pct <= 45.0:
        return RatioResult("approaching_limit", 60, False)
    return RatioResult("fail", 0, True)


def _verdict_for(score: int, hard_fail: bool) -> str:
    # Hard-fail overrides the blended score entirely -- mirrors the Step 2
    # fix (CLAUDE.md's "Scoring rubric deviations"): a breached hard limit
    # must never be diluted by averaging with healthy ratios.
    if hard_fail:
        return "Fail"
    if score > STRONG_PASS_SCORE:
        return "Strong Pass"
    return "Pass"


def score_step5_standard(current_ratio: float, debt_to_ebitda: float, debt_servicing_pct: float) -> dict:
    """Pure scoring function for Step 5's Standard-company path. No I/O, no
    FMP/DB dependency -- mirrors score_step1/score_step2's shape."""
    cr = score_current_ratio(current_ratio)
    de = score_debt_to_ebitda(debt_to_ebitda)
    ds = score_debt_servicing(debt_servicing_pct)
    hard_fail = cr.hard_fail or de.hard_fail or ds.hard_fail
    score = round((cr.points + de.points + ds.points) / 3)
    return {
        "score": score,
        "verdict": _verdict_for(score, hard_fail),
        "hard_fail": hard_fail,
        "ratios": {
            "current_ratio": {"value": current_ratio, "label": cr.label, "points": cr.points},
            "debt_to_ebitda": {"value": debt_to_ebitda, "label": de.label, "points": de.points},
            "debt_servicing_ratio": {"value": debt_servicing_pct, "label": ds.label, "points": ds.points},
        },
    }


def score_step5_reit(gearing_pct: float) -> dict:
    """Pure scoring function for Step 5's REIT/Property Developer path."""
    g = score_gearing(gearing_pct)
    return {
        "score": g.points,
        "verdict": _verdict_for(g.points, g.hard_fail),
        "hard_fail": g.hard_fail,
        "ratios": {
            "gearing_ratio": {"value": gearing_pct, "label": g.label, "points": g.points},
        },
    }
