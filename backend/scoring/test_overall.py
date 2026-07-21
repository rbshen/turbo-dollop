import pytest

from scoring.overall import StepSnapshot, compute_overall_assessment


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
