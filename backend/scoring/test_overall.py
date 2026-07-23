import pytest

from scoring.overall import MoatSnapshot, StepSnapshot, compute_overall_assessment


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
    # 90*0.35 + 80*0.22 + 70*0.28 + 60*0.15 = 31.5 + 17.6 + 19.6 + 9 = 77.7 -> 78
    result = compute_overall_assessment(steps)
    assert result.status == "complete"
    assert result.score == 78
    assert result.verdict == "Pass"


def test_all_steps_at_100_scores_exactly_100_strong_pass():
    result = compute_overall_assessment(BASE)
    assert result.score == 100
    assert result.verdict == "Strong Pass"


def test_renormalizes_weights_when_a_step_is_structurally_exempt():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", None, "not_supported"),
    ]
    # Step 5 excluded; remaining weights (0.35+0.22+0.28=0.85) renormalize
    # to sum to 1 -- since all 3 remaining scores are equal (90), the
    # renormalized weighted average is still exactly 90 regardless of the
    # individual renormalized weights.
    result = compute_overall_assessment(steps)
    assert result.status == "complete"
    assert result.score == 90
    step5_entry = next(b for b in result.breakdown if b.key == "step5")
    assert step5_entry.status == "exempt"
    assert step5_entry.effective_weight is None
    step1_entry = next(b for b in result.breakdown if b.key == "step1")
    assert step1_entry.effective_weight == pytest.approx(0.35 / 0.85, abs=1e-5)


def test_renormalization_actually_shifts_the_score_when_remaining_scores_differ():
    steps = [
        snapshot("step1", "Step 1", 100, "Strong Pass"),
        snapshot("step2", "Step 2", 0, "Fail"),
        snapshot("step4", "Step 4", 100, "Strong Pass"),
        snapshot("step5", "Step 5", None, "not_supported"),
    ]
    # Without step5: (100*0.35 + 0*0.22 + 100*0.28) / (0.35+0.22+0.28)
    # = 63 / 0.85 = 74.117... -> 74
    result = compute_overall_assessment(steps)
    assert result.score == 74


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
    result = compute_overall_assessment(steps)
    # No hard-fail override -- the score is still a plain weighted average.
    assert result.score == round(90 * 0.35 + 90 * 0.22 + 90 * 0.28 + 0 * 0.15)
    assert result.failing_steps == ["Step 5"]


def test_stays_silent_no_failing_steps_when_nothing_failed():
    result = compute_overall_assessment(BASE)
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
    result = compute_overall_assessment(steps)
    assert result.score < 70
    assert result.verdict == "Fail"


def test_score_of_exactly_70_is_pass_not_fail():
    steps = [
        snapshot("step1", "Step 1", 70, "Pass"),
        snapshot("step2", "Step 2", 70, "Pass"),
        snapshot("step4", "Step 4", 70, "Pass"),
        snapshot("step5", "Step 5", 70, "Pass"),
    ]
    result = compute_overall_assessment(steps)
    assert result.score == 70
    assert result.verdict == "Pass"


def test_score_of_69_is_fail():
    steps = [
        snapshot("step1", "Step 1", 69, "Pass"),
        snapshot("step2", "Step 2", 69, "Pass"),
        snapshot("step4", "Step 4", 69, "Pass"),
        snapshot("step5", "Step 5", 69, "Pass"),
    ]
    result = compute_overall_assessment(steps)
    assert result.score == 69
    assert result.verdict == "Fail"


def test_lists_every_failing_step_by_name_when_more_than_one_fails():
    steps = [
        snapshot("step1", "Step 1", 0, "Fail"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", 0, "Fail"),
    ]
    result = compute_overall_assessment(steps)
    assert result.failing_steps == ["Step 1", "Step 5"]


# --- Economic Moat (worked examples from the plan, ticker blending to 90
# across Steps 1/2/4/5 with all four present) ---

STEPS_BLENDING_TO_90 = [
    snapshot("step1", "Step 1", 90, "Pass"),
    snapshot("step2", "Step 2", 90, "Pass"),
    snapshot("step4", "Step 4", 90, "Pass"),
    snapshot("step5", "Step 5", 90, "Pass"),
]


def test_moat_not_set_is_byte_identical_to_no_moat_behavior():
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat=None)
    assert result.score == 90
    assert result.verdict == "Pass"  # 90 is the Pass/Strong Pass boundary (>90 required for Strong Pass)
    assert all(b.key != "moat" for b in result.breakdown)


def test_wide_moat_worked_example():
    # 0.69*90 + 0.31*100 = 62.1 + 31 = 93.1 -> 93
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat=MoatSnapshot("wide_moat", 100.0))
    assert result.score == 93
    assert result.verdict == "Strong Pass"


def test_narrow_moat_worked_example():
    # 0.69*90 + 0.31*65 = 62.1 + 20.15 = 82.25 -> 82
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat=MoatSnapshot("narrow_moat", 65.0))
    assert result.score == 82
    assert result.verdict == "Pass"


def test_no_moat_worked_example_caps_below_pass_threshold():
    # 0.69*90 + 0.31*0 = 62.1 -> 62 -- a hard-fail-via-arithmetic by design,
    # confirmed and documented (see CLAUDE.md's Economic Moat deviation note).
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat=MoatSnapshot("no_moat", 0.0))
    assert result.score == 62
    assert result.verdict == "Fail"


def test_no_moat_caps_a_perfect_steps_score_at_69_fail():
    result = compute_overall_assessment(BASE, moat=MoatSnapshot("no_moat", 0.0))
    assert result.score == 69
    assert result.verdict == "Fail"


def test_moat_does_not_rescue_an_incomplete_steps_blend():
    steps = [*BASE[:3], snapshot("step5", "Step 5", None, "n/a", has_error=True)]
    result = compute_overall_assessment(steps, moat=MoatSnapshot("wide_moat", 100.0))
    assert result.status == "incomplete"
    assert result.score is None


def test_moat_applies_on_top_of_a_renormalized_steps_blend_with_an_exempt_step():
    steps = [
        snapshot("step1", "Step 1", 90, "Pass"),
        snapshot("step2", "Step 2", 90, "Pass"),
        snapshot("step4", "Step 4", 90, "Pass"),
        snapshot("step5", "Step 5", None, "not_supported"),
    ]
    # Steps-only blend renormalizes to 90 (all remaining scores equal, see
    # test_renormalizes_weights_when_a_step_is_structurally_exempt) --
    # applying moat on top must still be 0.69*90 + 0.31*100 = 93.1 -> 93,
    # the same as the all-4-present case, not a different number produced by
    # a flat single-stage renormalization across steps+moat together.
    result = compute_overall_assessment(steps, moat=MoatSnapshot("wide_moat", 100.0))
    assert result.score == 93


def test_moat_breakdown_entry_never_appears_in_failing_steps():
    result = compute_overall_assessment(STEPS_BLENDING_TO_90, moat=MoatSnapshot("no_moat", 0.0))
    assert result.failing_steps == []
    moat_entry = next(b for b in result.breakdown if b.key == "moat")
    assert moat_entry.verdict == "No Moat"
    assert moat_entry.score == 0.0
