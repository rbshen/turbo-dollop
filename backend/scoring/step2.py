from typing import NamedTuple

# Magnitude thresholds: average projected growth rate, in percent.
MAGNITUDE_HIGH = 15.0
MAGNITUDE_SOLID = 10.0
MAGNITUDE_MODEST = 5.0
MAGNITUDE_BORDERLINE = 0.0

# Agreement thresholds: high/low spread as a % of the average estimate.
AGREEMENT_TIGHT = 10.0
AGREEMENT_MODERATE = 20.0

MAGNITUDE_WEIGHT = 0.70
AGREEMENT_WEIGHT = 0.30

VERDICT_BANDS = [
    (91, 100, "Strong Pass"),
    (70, 90, "Pass"),
    (0, 69, "Fail"),
]


class ScoreResult(NamedTuple):
    magnitude_score: int
    agreement_score: int
    score: int
    verdict: str


def _score_magnitude(growth_rate_pct: float) -> int:
    # Bucket boundaries are half-open ([low, high)) so e.g. exactly 15%
    # falls in the 10-15 bucket (85), not the >15 bucket (100).
    if growth_rate_pct > MAGNITUDE_HIGH:
        return 100
    if growth_rate_pct >= MAGNITUDE_SOLID:
        return 85
    if growth_rate_pct >= MAGNITUDE_MODEST:
        return 65
    if growth_rate_pct >= MAGNITUDE_BORDERLINE:
        return 40
    return 0


def _score_agreement(spread_pct: float) -> int:
    if spread_pct < AGREEMENT_TIGHT:
        return 100
    if spread_pct <= AGREEMENT_MODERATE:
        return 60
    return 20


def _verdict_for(score: int) -> str:
    for low, high, label in VERDICT_BANDS:
        if low <= score <= high:
            return label
    return "Fail"


def score_step2(growth_rate_pct: float, spread_pct: float) -> ScoreResult:
    """Pure scoring function for Step 2 (Positive Growth Rate). Takes the
    already-computed projected growth rate and estimate-range spread (both
    percentages) and returns the weighted score. No I/O, no FMP/DB
    dependency -- mirrors score_step1's shape."""
    magnitude_score = _score_magnitude(growth_rate_pct)
    agreement_score = _score_agreement(spread_pct)
    weighted_sum = magnitude_score * MAGNITUDE_WEIGHT + agreement_score * AGREEMENT_WEIGHT
    score = max(0, min(100, round(weighted_sum)))
    return ScoreResult(
        magnitude_score=magnitude_score,
        agreement_score=agreement_score,
        score=score,
        verdict=_verdict_for(score),
    )
