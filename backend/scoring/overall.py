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
PASS_THRESHOLD = 70

# Once a ticker has an Economic Moat set (any of the 3 real states -- "not
# set" is unaffected and uses the pure Steps 1/2/4/5 blend above, untouched),
# Steps 1+2+4+5 combined occupy 69% of Overall Assessment and Moat occupies
# the other 31%. Mirrors frontend/lib/overallScore.ts::MOAT_WEIGHT exactly --
# see STEP_WEIGHTS's own comment above on why these two implementations must
# never drift.
MOAT_WEIGHT = 0.31

MOAT_LABELS = {"no_moat": "No Moat", "narrow_moat": "Narrow Moat", "wide_moat": "Wide Moat"}


class StepSnapshot(NamedTuple):
    key: str
    label: str
    has_error: bool
    # None means no data was available for this step at all.
    score: int | None
    verdict: str | None


class MoatSnapshot(NamedTuple):
    moat: str  # "no_moat" | "narrow_moat" | "wide_moat"
    # Resolved point value (0-100) from MoatScoreConfig for this moat state
    # -- callers resolve this before calling compute_overall_assessment
    # (see moat.py::resolve_moat_score), since this module has no DB access.
    score: float


class StepBreakdownEntry(NamedTuple):
    key: str
    label: str
    base_weight: float
    # The weight actually used, renormalized across applicable steps --
    # None when the step was excluded (exempt) or unavailable (incomplete).
    effective_weight: float | None
    score: float | None
    verdict: str | None
    status: str


class OverallAssessment(NamedTuple):
    status: str  # "complete" | "incomplete"
    score: int | None
    verdict: str | None  # "Strong Pass" | "Pass" | "Fail" | None
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


def _verdict_for(score: int) -> str:
    if score > STRONG_PASS_THRESHOLD:
        return "Strong Pass"
    if score >= PASS_THRESHOLD:
        return "Pass"
    return "Fail"


def compute_overall_assessment(steps: list[StepSnapshot], moat: MoatSnapshot | None = None) -> OverallAssessment:
    """Pure port of frontend/lib/overallScore.ts::computeOverallAssessment,
    minus the "loading" status -- there's no async/loading concept here,
    since the backend calls each step's data function synchronously and
    already has (or doesn't have) a result by the time this runs. Every
    other rule (renormalization across non-exempt steps, no hard-fail
    override, verdict bands) is identical.

    `moat` is None for the (default) "not set" state -- in that case the
    result is byte-identical to the pre-Moat behavior below. When set, Moat
    is applied as a SECOND stage on top of the Steps 1/2/4/5 blend
    (`0.69 * steps_score + 0.31 * moat.score`), not folded into a single
    flat weight table alongside STEP_WEIGHTS -- a flat renormalization does
    not reduce to that formula once a step is also exempt/missing (traced
    through the arithmetic; see CLAUDE.md's Economic Moat deviation note).
    A missing/incomplete steps blend is never rescued by a present moat --
    Moat is not a substitute for missing step data."""
    with_status = [(s, _status_for(s)) for s in steps]

    incomplete = [(s, st) for s, st in with_status if st in ("error", "incomplete")]
    ok = [(s, st) for s, st in with_status if st == "ok"]
    total_weight = sum(STEP_WEIGHTS[s.key] for s, _ in ok)

    # A confident score requires every non-exempt step to have real data --
    # a weighted average built on missing data would be misleading, so this
    # short-circuits to an explicit incomplete state instead.
    can_compute = len(incomplete) == 0 and total_weight > 0
    steps_score = round(sum(STEP_WEIGHTS[s.key] * s.score for s, _ in ok) / total_weight) if can_compute else None

    failing_steps = [s.label for s, _ in ok if s.verdict == "Fail"]

    if moat is None:
        score = steps_score
        display_scale = 1.0
    elif steps_score is None:
        score = None
        display_scale = 1.0 - MOAT_WEIGHT
    else:
        score = round((1.0 - MOAT_WEIGHT) * steps_score + MOAT_WEIGHT * moat.score)
        display_scale = 1.0 - MOAT_WEIGHT

    breakdown = [
        StepBreakdownEntry(
            key=s.key,
            label=s.label,
            base_weight=STEP_WEIGHTS[s.key],
            effective_weight=(STEP_WEIGHTS[s.key] / total_weight * display_scale) if can_compute and st == "ok" else None,
            score=s.score,
            verdict=s.verdict,
            status=st,
        )
        for s, st in with_status
    ]
    if moat is not None:
        breakdown.append(
            StepBreakdownEntry(
                key="moat",
                label="Economic Moat",
                base_weight=MOAT_WEIGHT,
                effective_weight=MOAT_WEIGHT if score is not None else None,
                score=moat.score,
                # Deliberately not "Pass"/"Fail" text -- keeps Moat out of
                # failing_steps below, which filters on verdict == "Fail".
                verdict=MOAT_LABELS[moat.moat],
                status="ok",
            )
        )

    return OverallAssessment(
        status="complete" if can_compute else "incomplete",
        score=score,
        # No hard-fail override among the 4 computed steps themselves --
        # deliberately a pure weighted average there. Moat is the one
        # deliberate exception (see CLAUDE.md): since it's user-asserted,
        # not computed, a No Moat score of 0 combined with the 69/31 split
        # can cap the overall score below the 70 Pass threshold regardless
        # of how the 4 steps blend -- that's intended, not a bug. The
        # verdict BAND itself must match the shared 0-69/70-90/91-100 bands
        # used everywhere else in the app (see CLAUDE.md).
        verdict=(_verdict_for(score) if score is not None else None),
        breakdown=breakdown,
        incomplete_steps=[] if can_compute else [s.label for s, _ in incomplete],
        failing_steps=failing_steps,
        assessed_count=IMPLEMENTED_STEPS,
        total_methodology_steps=TOTAL_METHODOLOGY_STEPS,
    )
