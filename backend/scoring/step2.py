from typing import NamedTuple

# Magnitude thresholds: average projected growth rate, in percent.
MAGNITUDE_HIGH = 15.0
MAGNITUDE_SOLID = 10.0
MAGNITUDE_MODEST = 5.0
MAGNITUDE_BORDERLINE = 0.0
# --- Negative-magnitude graduated scale (2026-08-13) -------------------------
# The negative branch used to be a flat 0 regardless of magnitude -- a
# ticker projected at -0.03% growth (DVN, statistically indistinguishable
# from flat/breakeven) scored identically to one at -60.0% (SNDK, a genuine
# projected collapse). Confirmed via a full-universe scan: of 27 tickers
# hitting this branch, 13/27 were "mildly negative" (-5% to 0%) and only
# 1/27 was severely negative (<-50%) -- the flat floor was hiding real
# distinction in the majority of cases it applied to.
#
# MAGNITUDE_SEVERE_NEGATIVE (-10.0) mirrors MAGNITUDE_SOLID's own magnitude
# on the negative side -- a first-pass, round-number judgment call (no
# doc-given guidance exists for the negative side at all), chosen because it
# already captures the bulk of the real distribution as "mild" (20/27
# tickers, everything from ALL's -9.0% up through DVN's -0.0%) while leaving
# the genuinely severe tail (SNDK -60.0%, VLO -25.9%, CF -18.9%, INSW
# -14.5%, DOW -11.5%, LYB -11.0%, APA -10.8%) at a flat 0, unchanged.
#
# NEGATIVE_MAGNITUDE_FLOOR/CEILING graduate linearly between
# MAGNITUDE_SEVERE_NEGATIVE (10 points) and 0% (35 points) -- CEILING is
# deliberately kept below the "weak" tier's 40, so a mildly-negative-growth
# ticker can never score as well as a genuinely-positive-but-weak one.
#
# Verdict is NOT gated on magnitude_score's own value here -- see
# _verdict_for and PASS_SCORE_FLOOR's guard below, both keyed on
# `growth_rate_pct < MAGNITUDE_BORDERLINE` directly instead. This is
# load-bearing, not a style choice: `magnitude_score` becoming nonzero for a
# mild negative would otherwise (a) auto-promote the verdict to "Pass" via
# the old `magnitude_score == 0` Fail gate, and (b) trip PASS_SCORE_FLOOR,
# pushing the score to >=70 -- silently reintroducing a false Pass for a
# company with genuinely negative projected growth. Decoupling the gates
# from magnitude_score preserves the doc's own explicit design intent ("Fail
# is gated on the magnitude tier alone" -- any negative growth still fails,
# unconditionally, exactly as before) while letting the graduated *score*
# be an honest, non-zero number instead of a flat 0 -- mirrors how Step 5's
# Debt/EBITDA Severe-zone fix graduates the displayed number while keeping
# hard_fail unconditionally true.
MAGNITUDE_SEVERE_NEGATIVE = -10.0
NEGATIVE_MAGNITUDE_FLOOR = 10
NEGATIVE_MAGNITUDE_CEILING = 35

# Agreement thresholds: high/low spread as a % of the average estimate.
AGREEMENT_TIGHT = 10.0
AGREEMENT_MODERATE = 20.0

MAGNITUDE_WEIGHT = 0.70
AGREEMENT_WEIGHT = 0.30

# Score threshold for "Strong Pass" among Pass verdicts (see _verdict_for).
STRONG_PASS_SCORE = 90

# The blended score's floor whenever growth is non-negative (see
# score_step2's own comment) -- matches the 70 "Pass" floor every other
# step's shared color bands use, so a Pass verdict can no longer display a
# Fail-range number.
PASS_SCORE_FLOOR = 70


class ScoreResult(NamedTuple):
    magnitude_score: int
    magnitude_tier: str
    agreement_score: int
    agreement_tier: str
    score: int
    verdict: str


def _score_magnitude(growth_rate_pct: float) -> tuple[int, str]:
    # Bucket boundaries are half-open ([low, high)) so e.g. exactly 15%
    # falls in the 10-15 bucket (85), not the >15 bucket (100).
    if growth_rate_pct > MAGNITUDE_HIGH:
        return 100, "strong"
    if growth_rate_pct >= MAGNITUDE_SOLID:
        return 85, "solid"
    if growth_rate_pct >= MAGNITUDE_MODEST:
        return 65, "modest"
    if growth_rate_pct >= MAGNITUDE_BORDERLINE:
        return 40, "weak"
    if growth_rate_pct >= MAGNITUDE_SEVERE_NEGATIVE:
        fraction = (growth_rate_pct - MAGNITUDE_SEVERE_NEGATIVE) / abs(MAGNITUDE_SEVERE_NEGATIVE)
        points = round(NEGATIVE_MAGNITUDE_FLOOR + (NEGATIVE_MAGNITUDE_CEILING - NEGATIVE_MAGNITUDE_FLOOR) * fraction)
        return points, "mildly_negative"
    return 0, "negative"


def _score_agreement(spread_pct: float) -> tuple[int, str]:
    if spread_pct < AGREEMENT_TIGHT:
        return 100, "tight"
    if spread_pct <= AGREEMENT_MODERATE:
        return 60, "moderate"
    return 20, "wide"


def _verdict_for(score: int, growth_rate_pct: float) -> str:
    # Deliberately refined beyond step2_positive_growth_rate_assessment_
    # prompt.md's original score-band verdict -- see CLAUDE.md's "Scoring
    # rubric deviations". The doc's own scale only fails a company for
    # negative projected growth; 0-5% is "borderline" and 5-10% is "modest
    # but acceptable", neither a fail condition. Analyst disagreement (the
    # agreement component, 30% weight) should never by itself drag a
    # genuinely positive-growth company under the Fail line, so Fail is
    # gated on the raw growth rate's sign alone, not the blended score.
    #
    # Gated on `growth_rate_pct` directly, NOT `magnitude_score == 0`
    # (changed 2026-08-13, alongside the negative-magnitude graduated
    # scale above) -- magnitude_score is no longer 0 for every negative
    # growth rate (mildly-negative cases now get a nonzero, graduated
    # score), so checking it here would silently promote a genuinely
    # negative-growth ticker to "Pass" the moment its magnitude cleared 0.
    # This keeps the verdict boundary byte-identical to before: any
    # negative growth still fails, unconditionally.
    if growth_rate_pct < MAGNITUDE_BORDERLINE:
        return "Fail"
    if score > STRONG_PASS_SCORE:
        return "Strong Pass"
    return "Pass"


def score_step2(growth_rate_pct: float, spread_pct: float) -> ScoreResult:
    """Pure scoring function for Step 2 (Positive Growth Rate). Takes the
    already-computed projected growth rate and estimate-range spread (both
    percentages) and returns the weighted score. No I/O, no FMP/DB
    dependency -- mirrors score_step1's shape."""
    magnitude_score, magnitude_tier = _score_magnitude(growth_rate_pct)
    agreement_score, agreement_tier = _score_agreement(spread_pct)
    weighted_sum = magnitude_score * MAGNITUDE_WEIGHT + agreement_score * AGREEMENT_WEIGHT
    score = max(0, min(100, round(weighted_sum)))
    # Floors the BLENDED score, not magnitude_score itself (which stays the
    # raw tier value the UI's own magnitude/agreement breakdown shows) --
    # a weak-but-positive-growth ticker's Pass verdict must never display a
    # 0-69 number, which every other step's shared color bands (and every
    # other step's own verdict logic) treat as Fail-severity. Verdict logic
    # is untouched: Fail is still gated purely on growth_rate_pct's sign
    # (see _verdict_for), and this can never cross the Strong Pass threshold
    # (raises only scores already below 70, Strong Pass requires > 90).
    #
    # Gated on `growth_rate_pct >= MAGNITUDE_BORDERLINE`, NOT
    # `magnitude_score > 0` (changed 2026-08-13) -- a mildly-negative-growth
    # ticker now has a nonzero magnitude_score too, and flooring its score
    # to 70 would silently make it indistinguishable from a genuine Pass.
    if growth_rate_pct >= MAGNITUDE_BORDERLINE and score < PASS_SCORE_FLOOR:
        score = PASS_SCORE_FLOOR
    return ScoreResult(
        magnitude_score=magnitude_score,
        magnitude_tier=magnitude_tier,
        agreement_score=agreement_score,
        agreement_tier=agreement_tier,
        score=score,
        verdict=_verdict_for(score, growth_rate_pct),
    )
