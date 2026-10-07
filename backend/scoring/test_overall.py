import pytest

from scoring.overall import (
    DEFAULT_NARROW_MOAT_MULTIPLIER,
    MOAT_NOT_RATED_NOTE,
    NARROW_MOAT_MULTIPLIER_OPTIONS,
    NO_MOAT_MULTIPLIER,
    SCORE_FORMULA_VERSION,
    STEP_WEIGHTS,
    WIDE_MOAT_MULTIPLIER,
    StepSnapshot,
    compute_overall_assessment,
    moat_multiplier,
)


def snapshot(key: str, label: str, score: int | None, verdict: str, has_error: bool = False) -> StepSnapshot:
    return StepSnapshot(key=key, label=label, has_error=has_error, score=score, verdict=verdict)


BASE = [
    snapshot("step1", "Step 1", 100, "Strong Pass"),
    snapshot("step2", "Step 2", 100, "Strong Pass"),
    snapshot("step4", "Step 4", 100, "Strong Pass"),
    snapshot("step5", "Step 5", 100, "Strong Pass"),
]


def test_computes_a_standard_weighted_average_when_every_step_has_a_real_score():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 80, "Pass"),
        snapshot("step4", "Step 4", 70, "Pass"),
        snapshot("step5", "Step 5", 60, "Pass"),
    ]
    # Default weights 30/20/20/30: 90*0.30 + 80*0.20 + 70*0.20 + 60*0.30 = 75.0 (the Steps score, unrounded).
    wide = compute_overall_assessment(steps, moat="wide_moat")
    assert wide.status == "complete"
    assert wide.steps_score == pytest.approx(75.0)
    assert (wide.score, wide.verdict) == (75, "Pass")
    # The same steps with Narrow 0.85: 75.0 x 0.85 = 63.75 -> 64, below the line.
    narrow = compute_overall_assessment(steps, moat="narrow_moat")
    assert (narrow.score, narrow.verdict) == (64, "Fail")


def test_all_steps_at_100_scores_exactly_100_strong_pass_for_a_wide_moat():
    result = compute_overall_assessment(BASE, moat="wide_moat")
    assert result.score == 100
    assert result.verdict == "Strong Pass"


def test_renormalizes_weights_when_a_step_is_structurally_exempt():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", None, "not_supported"),
    ]
    # Step 5 excluded; remaining weights (step1+step2+step4) renormalize to
    # sum to 1 -- since all 3 remaining scores are equal (90), the
    # renormalized weighted average is still exactly 90 regardless of the
    # individual renormalized weights.
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.status == "complete"
    assert result.score == 90
    step5_entry = next(b for b in result.breakdown if b.key == "step5")
    assert step5_entry.status == "exempt"
    assert step5_entry.effective_weight is None
    step1_entry = next(b for b in result.breakdown if b.key == "step1")
    remaining = STEP_WEIGHTS["step1"] + STEP_WEIGHTS["step2"] + STEP_WEIGHTS["step4"]
    assert step1_entry.effective_weight == pytest.approx(STEP_WEIGHTS["step1"] / remaining, abs=1e-5)


def test_renormalization_actually_shifts_the_score_when_remaining_scores_differ():
    steps = [
        snapshot("step1", "Step 1", 100, "Strong Pass"),
        snapshot("step2", "Step 2", 0, "Fail"),
        snapshot("step4", "Step 4", 100, "Strong Pass"),
        snapshot("step5", "Step 5", None, "not_supported"),
    ]
    # Without step5: (100*30 + 0*20 + 100*20) / (30+20+20) = 5000/70 = 71.43 -> 71 (Wide, multiplier 1.0)
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.score == 71


def test_shows_incomplete_instead_of_a_partial_score_when_a_step_errors():
    steps = [*BASE[:3], snapshot("step5", "Step 5", None, "n/a", has_error=True)]
    result = compute_overall_assessment(steps)
    assert result.status == "incomplete"
    assert result.score is None
    assert result.incomplete_steps == ["Step 5"]


def test_shows_incomplete_when_a_step_has_insufficient_data_missing_not_exempt():
    steps = [*BASE[:3], snapshot("step5", "Step 5", None, "insufficient_data")]
    result = compute_overall_assessment(steps)
    assert result.status == "incomplete"
    assert result.score is None
    assert result.incomplete_steps == ["Step 5"]


def test_lists_every_incomplete_step_by_name_when_more_than_one_fails():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", None, "n/a", has_error=True),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", None, "n/a", has_error=True),
    ]
    result = compute_overall_assessment(steps)
    assert result.incomplete_steps == ["Step 2", "Step 5"]


def test_flags_a_fail_warning_when_any_implemented_steps_verdict_is_fail():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", 0, "Fail"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat")
    # No hard-fail override -- the score is still a plain weighted average.
    assert result.score == round(90 * STEP_WEIGHTS["step1"] + 90 * STEP_WEIGHTS["step2"] + 90 * STEP_WEIGHTS["step4"] + 0 * STEP_WEIGHTS["step5"])
    assert result.score == 63
    assert result.failing_steps == ["Step 5"]


def test_stays_silent_no_failing_steps_when_nothing_failed():
    result = compute_overall_assessment(BASE, moat="wide_moat")
    assert result.failing_steps == []


def test_score_under_70_shows_fail_not_pass():
    # Mirrors CCL's real shape: a low blended score (well under 70) must
    # read as "Fail", matching the shared 0-69/70-90/91-100 bands used
    # everywhere else in the app -- previously this always read "Pass"
    # regardless of how low the score was.
    steps = [
        snapshot("step1", "Step 1", 57, "Fail"),
        snapshot("step2", "Step 2", 58, "Pass"),
        snapshot("step4", "Step 4", 20, "Fail"),
        snapshot("step5", "Step 5", 28, "Fail"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.score < 70
    assert result.verdict == "Fail"


def test_score_of_exactly_70_is_pass_not_fail():
    steps = [
        snapshot("step1", "Step 1", 70, "Pass"),
        snapshot("step2", "Step 2", 70, "Pass"),
        snapshot("step4", "Step 4", 70, "Pass"),
        snapshot("step5", "Step 5", 70, "Pass"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.score == 70
    assert result.verdict == "Pass"


def test_score_of_69_is_fail():
    steps = [
        snapshot("step1", "Step 1", 69, "Pass"),
        snapshot("step2", "Step 2", 69, "Pass"),
        snapshot("step4", "Step 4", 69, "Pass"),
        snapshot("step5", "Step 5", 69, "Pass"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.score == 69
    assert result.verdict == "Fail"


def test_caution_step_forces_caution_verdict_even_when_blend_is_strong_pass():
    # A step-level "Pass with caution" (e.g. Step 5's tiebreaker-saved
    # breach) must override the blended score's own band -- previously the
    # verdict was purely score-banded, so this real breach was invisible
    # unless the user separately read the warning-text banner.
    # step1/2/4 at 100 (not 95) -- Debt's higher post-rebalance weight
    # (15%, was 10%) pulls the blend down further than before, so 95s no
    # longer clear the Strong Pass threshold on their own; 100s do.
    steps = [
        snapshot("step1", "Step 1", 100, "Strong Pass"),
        snapshot("step2", "Step 2", 100, "Strong Pass"),
        snapshot("step4", "Step 4", 100, "Strong Pass"),
        snapshot("step5", "Step 5", 74, "Pass with caution"),
    ]
    # 100*0.70 + 74*0.30 = 92.2 -> 92 (Wide)
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.score == 92  # the underlying blend is untouched
    assert result.verdict == "Pass with caution"
    # Unrated is scored as No moat: 92.2 x 0.7 = 64.5 -> 64, a Fail (the caution never softens it).
    assert compute_overall_assessment(steps, moat=None).verdict == "Fail"


def test_caution_propagation_does_not_override_a_fail_blend():
    # Fail must remain the strongest signal in the system -- a caution flag
    # never softens an already-failing blend into "Pass with caution".
    steps = [
        snapshot("step1", "Step 1", 30, "Fail"),
        snapshot("step2", "Step 2", 30, "Fail"),
        snapshot("step4", "Step 4", 30, "Fail"),
        snapshot("step5", "Step 5", 74, "Pass with caution"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.score < 70
    assert result.verdict == "Fail"


def test_lists_every_failing_step_by_name_when_more_than_one_fails():
    steps = [
        snapshot("step1", "Step 1", 0, "Fail"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", 0, "Fail"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.failing_steps == ["Step 1", "Step 5"]


# --- Economic Moat: Overall = Steps score x Moat multiplier (worked examples, a ticker whose four steps all score 90) ---

STEPS_BLENDING_TO_90 = [
    snapshot("step1", "Step 1", 90, "Pass"),
    snapshot("step2", "Step 2", 90, "Pass"),
    snapshot("step4", "Step 4", 90, "Pass"),
    snapshot("step5", "Step 5", 90, "Pass"),
]


def test_multiplier_constants():
    assert (WIDE_MOAT_MULTIPLIER, NO_MOAT_MULTIPLIER) == (1.0, 0.70)
    assert NARROW_MOAT_MULTIPLIER_OPTIONS == (0.80, 0.82, 0.85, 0.87, 0.90)
    assert DEFAULT_NARROW_MOAT_MULTIPLIER == 0.85 and DEFAULT_NARROW_MOAT_MULTIPLIER in NARROW_MOAT_MULTIPLIER_OPTIONS
    assert SCORE_FORMULA_VERSION == 5


def test_moat_multiplier_resolution():
    assert moat_multiplier("wide_moat") == 1.0
    assert moat_multiplier("narrow_moat") == 0.85
    assert moat_multiplier("narrow_moat", 0.9) == 0.9
    assert moat_multiplier("no_moat") == 0.70
    assert moat_multiplier(None) == 0.70  # unset is scored as No moat
    assert moat_multiplier(None, 0.9) == 0.70  # and never reads the Narrow setting


def test_wide_moat_worked_example():
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat="wide_moat")
    assert (result.score, result.verdict, result.moat_multiplier) == (90, "Pass", 1.0)
    assert result.steps_score == pytest.approx(90.0)


def test_narrow_moat_worked_example():
    # 90 x 0.85 = 76.5 -> 76 (half to even)
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat="narrow_moat")
    assert (result.score, result.verdict, result.moat_multiplier) == (76, "Pass", 0.85)


def test_the_analysis_card_example_steps_83_8_times_narrow_0_85_is_71():
    steps = [
        snapshot("step1", "Step 1", 84, "Pass"),
        snapshot("step2", "Step 2", 84, "Pass"),
        snapshot("step4", "Step 4", 83, "Pass"),
        snapshot("step5", "Step 5", 84, "Pass"),
    ]
    result = compute_overall_assessment(steps, moat="narrow_moat")
    assert round(result.steps_score, 1) == 83.8
    assert result.score == 71  # 83.8 x 0.85 = 71.23


def test_the_steps_score_is_kept_unrounded_and_rounded_once_after_the_multiplier():
    # Steps 81.6 x 0.85 = 69.36 -> 69, while rounding the Steps score first (82 x 0.85 = 69.7) would give 70, a Pass.
    steps = [
        snapshot("step1", "Step 1", 81, "Pass"),
        snapshot("step2", "Step 2", 83, "Pass"),
        snapshot("step4", "Step 4", 82, "Pass"),
        snapshot("step5", "Step 5", 81, "Pass"),
    ]
    result = compute_overall_assessment(steps, moat="narrow_moat")
    assert result.steps_score == pytest.approx(81.6)
    assert result.score == 69  # not 70: the Steps score was not rounded before the multiplier
    assert result.verdict == "Fail"


def test_no_moat_worked_example():
    # 90 x 0.70 = 63
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat="no_moat")
    assert (result.score, result.verdict, result.moat_multiplier) == (63, "Fail", 0.70)
    assert result.moat_note is None  # rated No moat: no "not rated" note


def test_a_perfect_steps_score_with_no_moat_reaches_exactly_70():
    # The one way a No moat / unrated ticker can read 70: all four steps at 100 (unreachable in practice, see the simulation).
    result = compute_overall_assessment(BASE, moat="no_moat")
    assert (result.score, result.verdict) == (70, "Pass")


def test_unrated_is_scored_exactly_as_no_moat_with_the_note():
    unrated = compute_overall_assessment(STEPS_BLENDING_TO_90, moat=None)
    rated = compute_overall_assessment(STEPS_BLENDING_TO_90, moat="no_moat")
    assert (unrated.score, unrated.verdict, unrated.moat_multiplier, unrated.steps_score) == (
        rated.score,
        rated.verdict,
        rated.moat_multiplier,
        rated.steps_score,
    )
    assert unrated.moat_note == MOAT_NOT_RATED_NOTE == "Moat not rated, scored as No moat"


def test_the_not_rated_verdict_state_is_retired():
    # A Pass-range steps score no longer reads "moat_not_rated": an unrated ticker's verdict comes from its (x0.7) score.
    assert compute_overall_assessment(_steps(95, "Strong Pass"), moat=None).verdict == "Fail"  # 95 x 0.7 = 66.5 -> 66
    assert compute_overall_assessment(_steps(95, "Strong Pass"), moat="wide_moat").verdict == "Strong Pass"


@pytest.mark.parametrize("narrow", NARROW_MOAT_MULTIPLIER_OPTIONS)
def test_every_allowed_narrow_multiplier_is_applied(narrow):
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat="narrow_moat", narrow_multiplier=narrow)
    assert result.moat_multiplier == narrow
    assert result.score == round(90 * narrow)


def test_moat_does_not_rescue_an_incomplete_steps_blend():
    steps = [*BASE[:3], snapshot("step5", "Step 5", None, "n/a", has_error=True)]
    result = compute_overall_assessment(steps, moat="wide_moat")
    assert result.status == "incomplete"
    assert (result.score, result.steps_score, result.moat_multiplier) == (None, None, None)
    # An incomplete unrated row has no score, hence no "scored as No moat" note either.
    assert compute_overall_assessment(steps, moat=None).moat_note is None


def test_the_multiplier_applies_on_top_of_a_renormalized_steps_blend_with_an_exempt_step():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", None, "not_supported"),
    ]
    # The Steps score renormalizes to 90 (all remaining scores are equal); Narrow then gives 90 x 0.85 = 76.5 -> 76, the same as
    # the all-four-present case.
    result = compute_overall_assessment(steps, moat="narrow_moat")
    assert (result.status, result.score) == ("complete", 76)


def test_the_breakdown_lists_only_the_steps_and_their_effective_weights_add_up_to_one():
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat="wide_moat")
    assert [b.key for b in result.breakdown] == ["step1", "step2", "step4", "step5"]  # Moat is no longer a row
    assert sum(b.effective_weight for b in result.breakdown) == pytest.approx(1.0)
    assert [b.effective_weight for b in result.breakdown] == pytest.approx([0.30, 0.20, 0.20, 0.30])


def _steps(score: int, verdict: str, step5_verdict: str | None = None) -> list[StepSnapshot]:
    return [
        snapshot("step1", "Step 1", score, verdict),
        snapshot("step2", "Step 2", score, verdict),
        snapshot("step4", "Step 4", score, verdict),
        snapshot("step5", "Step 5", score, step5_verdict or verdict),
    ]


def test_unrated_pass_with_caution_carries_up_only_when_the_score_passes():
    # Wide: 80 x 1.0 passes, so the caution step still shows; unrated: 80 x 0.7 = 56 is a Fail, which stays Fail.
    steps = _steps(80, "Pass", step5_verdict="Pass with caution")
    assert compute_overall_assessment(steps, moat="wide_moat").verdict == "Pass with caution"
    assert compute_overall_assessment(steps, moat=None).verdict == "Fail"


def test_unrated_incomplete_stays_incomplete():
    steps = [*_steps(90, "Pass")[:3], snapshot("step5", "Step 5", None, "insufficient_data")]
    result = compute_overall_assessment(steps, moat=None)
    assert (result.status, result.score, result.verdict, result.moat_note) == ("incomplete", None, None, None)


def test_unrated_with_an_exempt_step_is_scored_as_no_moat():
    steps = [*_steps(90, "Pass")[:3], snapshot("step5", "Step 5", None, "not_supported")]
    result = compute_overall_assessment(steps, moat=None)
    assert (result.status, result.score, result.verdict) == ("complete", 63, "Fail")


def test_a_non_default_weight_set_changes_the_steps_score_not_the_multiplier():
    from scoring.weights import OverallWeights

    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 80, "Pass"),
        snapshot("step4", "Step 4", 70, "Pass"),
        snapshot("step5", "Step 5", 60, "Pass"),
    ]
    result = compute_overall_assessment(steps, moat="wide_moat", weights=OverallWeights(10, 5, 5, 80))
    assert result.steps_score == pytest.approx(0.10 * 90 + 0.05 * 80 + 0.05 * 70 + 0.80 * 60)
    assert result.moat_multiplier == 1.0
