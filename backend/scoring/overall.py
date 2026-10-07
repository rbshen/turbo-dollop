from typing import NamedTuple

from scoring.weights import DEFAULT_WEIGHTS, OverallWeights, overall_fractions

# Overall Assessment = Steps score x Moat multiplier (2026-10-07; docs/decisions.md). The Steps score is the weighted blend of the
# four automated steps (Financials, Growth Rate, Profitability, Debt), computed UNROUNDED; Economic Moat is not a blend component
# any more, it scales that score, and Overall is rounded once, after the multiplication (Python `round`, half to even, the app's
# convention). Mirrored by frontend/lib/overallScore.ts, which must produce the same result for the same ticker -- both read the
# shared fixture backend/tests/fixtures/overall_verdict_cases.json. No allocation for Step 3 (Valuation is not part of Overall).
#
# The default step weights live in scoring/weights.py::DEFAULT_WEIGHTS (30/20/20/30, adding up to 100); a saved weight set is passed
# to compute_overall_assessment as a parameter.
STEP_WEIGHTS = overall_fractions(DEFAULT_WEIGHTS.overall)

IMPLEMENTED_STEPS = len(STEP_WEIGHTS)
TOTAL_METHODOLOGY_STEPS = 5

STRONG_PASS_THRESHOLD = 90
PASS_THRESHOLD = 70

# The version of the Overall FORMULA (not of the weights). TickerScore.formula_version records it; a stored row whose version is
# not this one was scored by a different formula and is stale (weights_version cannot see a formula change). Bump it whenever
# compute_overall_assessment's arithmetic changes. 1 = the old 69/31 Moat blend (rows have no version), 2 = Steps x Moat multiplier,
# 3 = the same Overall arithmetic over the neutral Step 1 engine (2026-10-07: Step 1 now scores completed fiscal years with scoring/
# step1_engine.py, so every row stored under 2 carries the old Financials score and is stale). 4 = the same engine with age-decayed dip
# costs (2026-10-07), which moves Step 1 scores again. 5 = Step 5 without its hard fail and with the 25/45/30 default weights
# (2026-10-07): a Debt blend is now a pure read of its three ratios, so every Standard/Utility Debt score and verdict can move.
# 6 = the Step 1 Commodity exemption by industry allowlist (2026-10-07): 23 Basic Materials/Energy tickers moved from the CFO/FCF-exempt
# table to the Standard one, so their stored Step 1 and Overall are stale.
SCORE_FORMULA_VERSION = 6

# Moat multipliers. Wide and No moat are fixed; Narrow is the one Settings > Economic Moat setting, one of the allowed values.
# A ticker with Moat unset is scored as No moat (there is no separate "not rated" verdict any more).
WIDE_MOAT_MULTIPLIER = 1.0
NO_MOAT_MULTIPLIER = 0.7
NARROW_MOAT_MULTIPLIER_OPTIONS = (0.80, 0.82, 0.85, 0.87, 0.90)
DEFAULT_NARROW_MOAT_MULTIPLIER = 0.85

MOAT_LABELS = {"no_moat": "No Moat", "narrow_moat": "Narrow Moat", "wide_moat": "Wide Moat"}

# Shown beside the verdict (Analysis card, header chip tooltip) when Moat is unset. Mirrors frontend/lib/overallScore.ts.
MOAT_NOT_RATED_NOTE = "Moat not rated, scored as No moat"


def moat_multiplier(moat: str | None, narrow_multiplier: float = DEFAULT_NARROW_MOAT_MULTIPLIER) -> float:
    """The multiplier for a Moat state (None = unset = No moat). `narrow_multiplier` is the saved Narrow setting."""
    if moat == "wide_moat":
        return WIDE_MOAT_MULTIPLIER
    if moat == "narrow_moat":
        return narrow_multiplier
    return NO_MOAT_MULTIPLIER


class StepSnapshot(NamedTuple):
    key: str
    label: str
    has_error: bool
    # None means no data was available for this step at all.
    score: int | None
    verdict: str | None


class StepBreakdownEntry(NamedTuple):
    key: str
    label: str
    base_weight: float
    # The weight actually used, renormalized across applicable steps (the entries add up to 1) -- None when the step was
    # excluded (exempt) or unavailable (incomplete).
    effective_weight: float | None
    score: float | None
    verdict: str | None
    status: str


class OverallAssessment(NamedTuple):
    status: str  # "complete" | "incomplete"
    score: int | None  # Overall: round(steps_score x moat_multiplier)
    # "Strong Pass" | "Pass" | "Pass with caution" | "Fail" | None
    verdict: str | None
    breakdown: list[StepBreakdownEntry]
    incomplete_steps: list[str]
    failing_steps: list[str]
    assessed_count: int
    total_methodology_steps: int
    # The weighted blend of the steps, UNROUNDED (display it to one decimal). None when incomplete.
    steps_score: float | None = None
    # The multiplier applied (1.0 / the saved Narrow value / 0.7). None when incomplete.
    moat_multiplier: float | None = None
    # MOAT_NOT_RATED_NOTE when Moat is unset (complete rows only); None otherwise.
    moat_note: str | None = None


def _status_for(snapshot: StepSnapshot) -> str:
    if snapshot.has_error:
        return "error"
    if snapshot.score is None:
        # "not_supported" (Step 5 for Banks without CET1, and Insurance) is a legitimate structural exemption.
        # Any other null-score verdict (e.g. "insufficient_data") means the
        # figures this ticker needed just weren't available -- missing
        # data, not "doesn't apply", so it's treated the same as an error.
        return "exempt" if snapshot.verdict == "not_supported" else "incomplete"
    return "ok"


def _verdict_for(score: int) -> str:
    if score > STRONG_PASS_THRESHOLD:
        return "Strong Pass"
    if score >= PASS_THRESHOLD:
        return "Pass"
    return "Fail"


def compute_overall_assessment(
    steps: list[StepSnapshot],
    moat: str | None = None,
    weights: OverallWeights = DEFAULT_WEIGHTS.overall,
    narrow_multiplier: float = DEFAULT_NARROW_MOAT_MULTIPLIER,
) -> OverallAssessment:
    """Pure port of frontend/lib/overallScore.ts::computeOverallAssessment, minus the "loading" status -- there's no
    async/loading concept here. Every rule is identical.

    Steps score = the weighted average of the steps that apply (an exempt "not_supported" step is excluded and the rest
    reweighted; any step with missing data makes the whole assessment incomplete, which no Moat rating can rescue), kept
    unrounded. Overall = round(steps_score x multiplier), rounded once. `moat` is "no_moat" | "narrow_moat" | "wide_moat" or
    None (unset, scored as No moat); `narrow_multiplier` is the saved Narrow setting. No cap, no hard-fail override: the verdict
    is read from the Overall score (bands 0-69 Fail, 70-90 Pass, 91+ Strong Pass), and a step's "Pass with caution" still
    carries up beside an otherwise-passing score."""
    step_weights = overall_fractions(weights)
    with_status = [(s, _status_for(s)) for s in steps]

    incomplete = [(s, st) for s, st in with_status if st in ("error", "incomplete")]
    ok = [(s, st) for s, st in with_status if st == "ok"]
    total_weight = sum(step_weights[s.key] for s, _ in ok)

    # A confident score requires every non-exempt step to have real data --
    # a weighted average built on missing data would be misleading, so this
    # short-circuits to an explicit incomplete state instead.
    can_compute = len(incomplete) == 0 and total_weight > 0
    steps_score = sum(step_weights[s.key] * s.score for s, _ in ok) / total_weight if can_compute else None
    multiplier = moat_multiplier(moat, narrow_multiplier) if can_compute else None
    score = round(steps_score * multiplier) if steps_score is not None else None

    failing_steps = [s.label for s, _ in ok if s.verdict == "Fail"]
    caution_steps = [s.label for s, _ in ok if s.verdict == "Pass with caution"]

    breakdown = [
        StepBreakdownEntry(
            key=s.key,
            label=s.label,
            base_weight=step_weights[s.key],
            effective_weight=(step_weights[s.key] / total_weight) if can_compute and st == "ok" else None,
            score=s.score,
            verdict=s.verdict,
            status=st,
        )
        for s, st in with_status
    ]

    score_verdict = _verdict_for(score) if score is not None else None
    # A step-level "Pass with caution" flag must win over the blended
    # score's own band -- Fail stays Fail (already the strongest signal),
    # but an otherwise-green Pass/Strong Pass displays as caution instead.
    # This changes only the DISPLAYED verdict; `score` above is untouched.
    verdict = "Pass with caution" if score_verdict not in (None, "Fail") and caution_steps else score_verdict

    return OverallAssessment(
        status="complete" if can_compute else "incomplete",
        score=score,
        verdict=verdict,
        breakdown=breakdown,
        incomplete_steps=[] if can_compute else [s.label for s, _ in incomplete],
        failing_steps=failing_steps,
        assessed_count=IMPLEMENTED_STEPS,
        total_methodology_steps=TOTAL_METHODOLOGY_STEPS,
        steps_score=steps_score,
        moat_multiplier=multiplier,
        moat_note=MOAT_NOT_RATED_NOTE if moat is None and can_compute else None,
    )
