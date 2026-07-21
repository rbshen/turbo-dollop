from typing import NamedTuple

# Mirrors frontend/lib/overallScore.ts::STEP_WEIGHTS exactly -- these two
# implementations must never drift, since the live ticker page (frontend,
# computed client-side) and the Screener's pre-computed TickerScore row
# (backend, this module) both need to produce the same Overall Assessment
# for the same ticker. Sum to 100%, no allocation for Step 3 (not yet
# implemented) -- revisit both together once Step 3 ships.
STEP_WEIGHTS = {"step1": 0.35, "step2": 0.22, "step4": 0.28, "step5": 0.15}

IMPLEMENTED_STEPS = len(STEP_WEIGHTS)
TOTAL_METHODOLOGY_STEPS = 5

STRONG_PASS_THRESHOLD = 90


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
    # The weight actually used, renormalized across applicable steps --
    # None when the step was excluded (exempt) or unavailable (incomplete).
    effective_weight: float | None
    score: int | None
    verdict: str | None
    status: str


class OverallAssessment(NamedTuple):
    status: str  # "complete" | "incomplete"
    score: int | None
    verdict: str | None  # "Strong Pass" | "Pass" | None
    breakdown: list[StepBreakdownEntry]
    incomplete_steps: list[str]
    failing_steps: list[str]
    assessed_count: int
    total_methodology_steps: int


def _status_for(snapshot: StepSnapshot) -> str:
    if snapshot.has_error:
        return "error"
    if snapshot.score is None:
        # "not_supported" (currently only Step 5, for Banks -- CET1 data
        # isn't available from FMP) is a legitimate structural exemption.
        # Any other null-score verdict (e.g. "insufficient_data") means the
        # figures this ticker needed just weren't available -- missing
        # data, not "doesn't apply", so it's treated the same as an error.
        return "exempt" if snapshot.verdict == "not_supported" else "incomplete"
    return "ok"


def compute_overall_assessment(steps: list[StepSnapshot]) -> OverallAssessment:
    """Pure port of frontend/lib/overallScore.ts::computeOverallAssessment,
    minus the "loading" status -- there's no async/loading concept here,
    since the backend calls each step's data function synchronously and
    already has (or doesn't have) a result by the time this runs. Every
    other rule (renormalization across non-exempt steps, no hard-fail
    override, `score > 90` -> Strong Pass) is identical."""
    with_status = [(s, _status_for(s)) for s in steps]

    incomplete = [(s, st) for s, st in with_status if st in ("error", "incomplete")]
    ok = [(s, st) for s, st in with_status if st == "ok"]
    total_weight = sum(STEP_WEIGHTS[s.key] for s, _ in ok)

    # A confident score requires every non-exempt step to have real data --
    # a weighted average built on missing data would be misleading, so this
    # short-circuits to an explicit incomplete state instead.
    can_compute = len(incomplete) == 0 and total_weight > 0
    score = round(sum(STEP_WEIGHTS[s.key] * s.score for s, _ in ok) / total_weight) if can_compute else None

    failing_steps = [s.label for s, _ in ok if s.verdict == "Fail"]

    breakdown = [
        StepBreakdownEntry(
            key=s.key,
            label=s.label,
            base_weight=STEP_WEIGHTS[s.key],
            effective_weight=(STEP_WEIGHTS[s.key] / total_weight) if can_compute and st == "ok" else None,
            score=s.score,
            verdict=s.verdict,
            status=st,
        )
        for s, st in with_status
    ]

    return OverallAssessment(
        status="complete" if can_compute else "incomplete",
        score=score,
        # No hard-fail override -- deliberately a pure weighted average
        # (unlike every individual step). The failing_steps list is the
        # separate, non-blocking "worth reviewing directly" signal.
        verdict=(("Strong Pass" if score > STRONG_PASS_THRESHOLD else "Pass") if score is not None else None),
        breakdown=breakdown,
        incomplete_steps=[] if can_compute else [s.label for s, _ in incomplete],
        failing_steps=failing_steps,
        assessed_count=IMPLEMENTED_STEPS,
        total_methodology_steps=TOTAL_METHODOLOGY_STEPS,
    )
