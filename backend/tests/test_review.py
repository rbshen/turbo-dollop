"""scoring/review.py: the demote-only Review status (pure; no DB, no FMP)."""

from types import SimpleNamespace as NS

import pytest

from scoring import review
from scoring.review import REVIEW_GATE_SCORE, compute_review, conviction_for, current_ratio_covered, debt_ebitda_covered


def ratio(value, label):
    return NS(value=value, label=label)


def step(score, verdict, **extra):
    return NS(score=score, verdict=verdict, **extra)


def step1(score=40, verdict="Fail", **kwargs):
    base = dict(
        components={
            "revenue": {"score": 80, "pattern": "steady_growth"},
            "net_income": {"score": 30, "pattern": "declining"},
            "cfo": {"score": 60, "pattern": "growing"},
            "margins": {"score": 20, "pattern": "compressing"},
            "fcf": None,
        },
        revenue=[100, 100, 100, 100, 100],
        net_income=[10, -5, -5, 3, 1],
        operating_income=[10, 8, -2, 6, 4],
    )
    base.update(kwargs)
    return step(score, verdict, **base)


# A failing Debt/EBITDA that is chronic and stable, ICR 6, DSR 12.
STABLE_DE = [3.4, 3.5, 3.6, 3.5, 3.4, 3.5]


def step5(score=30, verdict="Fail", ratios=None, series=None, fallback=None):
    default = {
        "current_ratio": ratio(1.5, "acceptable"),
        "debt_to_ebitda": ratio(3.5, "borderline_fail"),
        "debt_servicing_ratio": ratio(12.0, "good"),
        "interest_coverage_ratio": ratio(6.0, "safe"),
    }
    default.update(ratios or {})
    return step(score, verdict, ratios=default, debt_to_ebitda_series=series if series is not None else STABLE_DE, balance_sheet_fallback=fallback)


def bs(*ratios):
    """Balance-sheet rows newest first with the given current ratios (assets / 100 liabilities)."""
    return [{"date": f"20{25 - i // 4}-{12 - 3 * (i % 4):02d}-28", "totalCurrentAssets": r * 100, "totalCurrentLiabilities": 100} for i, r in enumerate(ratios)]


def flag(rule, period="quarterly", statement="cash_flow", period_end="2026-06-30", **detail):
    return NS(rule=rule, period=period, statement=statement, period_end=period_end, detail=detail)


PASS_STEP = step(80, "Pass")
HEALTHY = dict(step2=PASS_STEP, step4=PASS_STEP)


def run(s1=None, s5=None, overall="Pass", annual=(), quarterly=(), flags=(), s2=PASS_STEP, s4=PASS_STEP, **kw):
    return compute_review(overall, s1, s2, s4, s5, list(annual), list(quarterly), list(flags), **kw)


def only(result, key):
    return next(r for r in result.reasons if r["step"] == key)


# ---- gate ----------------------------------------------------------------------------------------------


def test_the_gate_constant_is_fifty():
    assert REVIEW_GATE_SCORE == 50


@pytest.mark.parametrize("score, gated", [(49, True), (50, False), (0, True), (69, False)])
def test_gate_boundary_on_score(score, gated):
    result = run(s1=step1(score=score))
    assert (result.status is not None) is gated


def test_gate_needs_a_fail_verdict_not_just_a_low_score():
    assert run(s1=step1(score=40, verdict="Pass with caution")).status is None
    assert run(s1=step1(score=40, verdict="Pass")).status is None


def test_step5_gate_reads_the_stored_fail_key_and_score_with_no_hard_fail_involved():
    # 2026-10-07: Step 5 has no hard fail and the Debt card DISPLAYS "Fail" as "May not pass", but the stored verdict key is still
    # "Fail": a blend under the Review line (50) still gates, a blend of 50-69 never did, and a caution Pass (an unrescued breach
    # carried to 70+) is a Pass-family verdict and is not gated.
    assert run(s5=step5(score=49, verdict="Fail")).status is not None
    assert run(s5=step5(score=50, verdict="Fail")).status is None
    assert run(s5=step5(score=69, verdict="Fail")).status is None
    assert run(s5=step5(score=74, verdict="Pass with caution")).status is None


def test_gate_can_be_overridden_for_the_information_run_only():
    assert run(s1=step1(score=60)).status is None
    assert run(s1=step1(score=60), gate=70).status == "review_unclear"


@pytest.mark.parametrize("overall", ["Fail", None, "moat_not_rated"])
def test_demote_only_a_fail_incomplete_or_moat_not_rated_row_never_gets_a_status(overall):
    result = run(s1=step1(score=10), s5=step5(score=10, ratios={"debt_servicing_ratio": ratio(80, "severe")}), overall=overall)
    assert result.status is None and result.reasons == [] and result.conviction is None


@pytest.mark.parametrize("overall", ["Pass", "Pass with caution", "Strong Pass"])
def test_every_pass_family_verdict_can_be_demoted(overall):
    assert run(s1=step1(), overall=overall).status == "review_unclear"


@pytest.mark.parametrize("verdict", ["not_supported", "insufficient_data", "exempt", None])
def test_not_supported_exempt_insufficient_and_errored_steps_never_gate(verdict):
    assert run(s1=step1(score=None, verdict=verdict), s5=step5(score=None, verdict=verdict)).status is None
    assert run(s1=None, s5=None).status is None


def test_steps_two_and_four_never_gate():
    result = run(s2=step(5, "Fail"), s4=step(5, "Fail"))
    assert result.status is None
    assert result.conviction == "low"


# ---- Step 1 --------------------------------------------------------------------------------------------


def test_a_gated_step1_reads_unclear_with_an_evidence_string_and_no_hint_label():
    result = run(s1=step1())
    assert result.status == "review_unclear"
    reason = only(result, "step1")
    assert (reason["hint"], reason["raw_hint"], reason["rule"], reason["guarded"]) == ("unclear", "unclear", "step1_gated", False)
    assert (reason["score"], reason["verdict"]) == (40, "Fail")
    evidence = reason["evidence"]
    assert "net_income declining 30" in evidence and "margins compressing 20" in evidence
    assert "revenue" not in evidence.split(";")[0]  # 80 is not weak
    assert "latest fiscal year operating margin 4.0%" in evidence
    assert "operating-health gate fails" in evidence  # 4% < 5% margin floor
    assert "loss years: net income 2/5, operating income 1/5" in evidence


def test_the_operating_health_gate_can_pass():
    healthy_oi = step1(operating_income=[10, 12, 14, 16, 20], revenue=[100, 100, 100, 100, 100])
    assert "operating-health gate passes" in only(run(s1=healthy_oi), "step1")["evidence"]


# ---- Step 5: structural / by design / unclear ----------------------------------------------------------


def test_dsr_at_sixty_is_structural_and_wins():
    ratios = {"debt_servicing_ratio": ratio(60.0, "severe")}
    assert only(run(s5=step5(ratios=ratios)), "step5")["rule"] == "dsr_ge_60"
    assert run(s5=step5(ratios=ratios)).status == "review_structural"
    assert run(s5=step5(ratios={"debt_servicing_ratio": ratio(59.9, "severe")})).status == "review_unclear"


def test_a_failing_dsr_is_never_covered():
    result = run(s5=step5(ratios={"debt_servicing_ratio": ratio(45.0, "severe")}))
    assert result.status == "review_unclear"
    assert "never covered" in only(result, "step5")["evidence"]


def test_a_blend_only_failure_has_no_failing_ratio_to_cover_and_reads_unclear():
    result = run(s5=step5(ratios={"debt_to_ebitda": ratio(2.5, "acceptable")}))
    assert result.status == "review_unclear"
    assert only(result, "step5")["rule"] == "not_covered"


def test_reit_gearing_is_never_covered():
    reit = step(30, "Fail", ratios={"gearing_ratio": ratio(55.0, "fail")}, debt_to_ebitda_series=[], balance_sheet_fallback=None)
    assert run(s5=reit).status == "review_unclear"


def test_a_stable_debt_ebitda_with_strong_coverage_is_by_design():
    result = run(s5=step5())
    assert result.status == "review_by_design"
    reason = only(result, "step5")
    assert (reason["hint"], reason["rule"]) == ("by_design", "debt_ebitda_stable")
    assert "3.40x to 3.60x" in reason["evidence"]


def test_a_failing_ratio_outside_its_coverage_test_is_unclear():
    unstable = [2.0, 3.5, 3.6, 3.5, 3.4, 3.5]
    assert run(s5=step5(series=unstable)).status == "review_unclear"


@pytest.mark.parametrize(
    "series, covered",
    [
        ([3.0, 3.6, 4.2, 3.6, 3.0, 3.6], True),  # median 3.6: 3.0 and 4.2 are about -16.7% / +16.7%
        ([2.88, 3.6, 3.6, 3.6, 3.6, 4.32], True),  # exactly -20% and +20%: inclusive
        ([2.87, 3.6, 3.6, 3.6, 3.6, 3.6], False),  # just below -20%
        ([3.6, 3.6, 3.6, 3.6, 3.6, 4.33], False),  # just above +20%
        ([None, 3.6, 3.6, 3.6, 3.6, 3.6], False),  # incomplete history fails closed
        ([3.6, 3.6, 3.6, 3.6, 3.6], False),  # fewer than 6 points
    ],
)
def test_debt_ebitda_median_band(series, covered):
    assert debt_ebitda_covered(series, 6.0, 12.0)[0] is covered


@pytest.mark.parametrize("icr, covered", [(5.0, True), (4.96, False), (None, False)])
def test_debt_ebitda_coverage_needs_icr_at_least_five(icr, covered):
    assert debt_ebitda_covered(STABLE_DE, icr, 12.0)[0] is covered


@pytest.mark.parametrize("dsr, covered", [(29.9, True), (30.0, False), (None, False)])
def test_debt_ebitda_coverage_needs_dsr_below_thirty(dsr, covered):
    assert debt_ebitda_covered(STABLE_DE, 6.0, dsr)[0] is covered


CR_FAIL = {"current_ratio": ratio(0.6, "severe"), "debt_to_ebitda": ratio(1.0, "good")}


@pytest.mark.parametrize("below, covered", [(4, True), (3, False)])
def test_current_ratio_annual_boundary_four_of_five_years(below, covered):
    annual = bs(*([0.8] * below + [1.2] * (5 - below)))
    assert current_ratio_covered(annual, [])[0] is covered
    assert (run(s5=step5(ratios=CR_FAIL), annual=annual).status == "review_by_design") is covered


@pytest.mark.parametrize("below, covered", [(6, True), (5, False)])
def test_current_ratio_quarterly_boundary_six_of_eight_quarters(below, covered):
    quarterly = bs(*([0.8] * below + [1.2] * (8 - below)))
    result = current_ratio_covered([], quarterly)
    assert result[0] is covered
    assert (result[1] == "cr_chronic_quarterly") is covered
    assert (run(s5=step5(ratios=CR_FAIL), quarterly=quarterly).status == "review_by_design") is covered


def test_a_ratio_of_exactly_one_is_not_below_and_an_unusable_row_never_counts():
    rows = bs(1.0, 1.0, 1.0, 1.0, 1.0)
    assert current_ratio_covered(rows, [])[0] is False
    broken = [{"date": "2025-12-28", "totalCurrentAssets": None, "totalCurrentLiabilities": 100}] * 5
    assert current_ratio_covered(broken, broken)[0] is False


def test_only_eight_quarters_and_five_years_are_looked_at():
    # Newer rows fine, older ones below 1.0: 4 low years sit outside the 5-year window.
    assert current_ratio_covered(bs(1.2, 1.2, 1.2, 1.2, 1.2, 0.5, 0.5, 0.5, 0.5), [])[0] is False


def test_the_quarter_window_starts_at_the_balance_sheet_in_use():
    rows = bs(5.0, 0.8, 0.8, 0.8, 0.8, 0.8, 1.2, 1.2, 0.8)  # newest is a partial row with a good-looking ratio
    used = rows[1]["date"]
    assert current_ratio_covered([], review.quarters_from(rows, used))[0] is True  # 6 of the 8 from the used row
    assert current_ratio_covered([], rows)[0] is False  # the partial row would push the oldest low quarter out of the window


def test_both_failing_ratios_must_be_covered():
    ratios = {"current_ratio": ratio(0.6, "severe"), "debt_to_ebitda": ratio(3.5, "borderline_fail")}
    annual = bs(*([0.8] * 5))
    assert run(s5=step5(ratios=ratios), annual=annual).status == "review_by_design"
    assert run(s5=step5(ratios=ratios, series=[2.0, 3.5, 3.6, 3.5, 3.4, 3.5]), annual=annual).status == "review_unclear"
    assert run(s5=step5(ratios=ratios), annual=bs(*([1.2] * 5))).status == "review_unclear"


# ---- data-quality guard --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rule, step1_guarded, step5_guarded",
    [
        ("placeholder_cf", True, False),
        ("scale_break", True, True),
        ("partial_balance_sheet", False, True),
        ("not_landed", True, True),
    ],
)
def test_the_guard_per_flag_per_step(rule, step1_guarded, step5_guarded):
    f = [flag(rule, in_ttm_window=True, newest_period=True)]
    assert run(s1=step1(), flags=f).status == ("data_uncertain" if step1_guarded else "review_unclear")
    assert run(s5=step5(), flags=f).status == ("data_uncertain" if step5_guarded else "review_by_design")


def test_a_quarterly_flag_outside_the_ttm_window_does_not_count():
    outside = [flag("scale_break", in_ttm_window=False, newest_period=False)]
    assert run(s1=step1(), flags=outside).status == "review_unclear"
    inside = [flag("scale_break", in_ttm_window=True, newest_period=False)]
    assert run(s1=step1(), flags=inside).status == "data_uncertain"
    newest = [flag("scale_break", in_ttm_window=False, newest_period=True)]
    assert run(s1=step1(), flags=newest).status == "data_uncertain"


def test_an_annual_flag_always_counts_and_not_landed_ignores_the_window():
    assert run(s1=step1(), flags=[flag("placeholder_cf", period="annual", in_ttm_window=False)]).status == "data_uncertain"
    assert run(s1=step1(), flags=[flag("not_landed", statement="income", in_ttm_window=False, newest_period=False)]).status == "data_uncertain"


def test_a_balance_sheet_fallback_guards_step5():
    result = run(s5=step5(fallback=NS(reason="debt_remap")))
    assert result.status == "data_uncertain"
    assert "balance_sheet_fallback" in only(result, "step5")["evidence"]


def test_the_guard_records_the_raw_hint_so_a_structural_reading_is_not_hidden():
    ratios = {"debt_servicing_ratio": ratio(72.0, "severe")}
    result = run(s5=step5(ratios=ratios), flags=[flag("scale_break", in_ttm_window=True)])
    reason = only(result, "step5")
    assert result.status == "data_uncertain"
    assert (reason["hint"], reason["raw_hint"], reason["guarded"], reason["rule"]) == ("data_uncertain", "structural", True, "dsr_ge_60")


def test_a_guard_on_one_step_does_not_hide_the_other_steps_hint():
    flags = [flag("partial_balance_sheet", statement="balance_sheet", in_ttm_window=True, newest_period=True)]
    result = run(s1=step1(), s5=step5(), flags=flags)
    assert only(result, "step1")["guarded"] is False
    assert only(result, "step5")["guarded"] is True
    assert result.status == "data_uncertain"


# ---- two gated steps: precedence -----------------------------------------------------------------------

STRUCTURAL = {"debt_servicing_ratio": ratio(70.0, "severe")}
GUARD_STEP1 = [flag("placeholder_cf", in_ttm_window=True)]


def test_precedence_unguarded_structural_beats_everything():
    result = run(s1=step1(), s5=step5(ratios=STRUCTURAL), flags=[])
    assert result.status == "review_structural"
    # ... even when the other step is guarded.
    assert run(s1=step1(), s5=step5(ratios=STRUCTURAL), flags=GUARD_STEP1).status == "review_structural"


def test_precedence_a_guarded_step_beats_unclear_and_by_design():
    assert run(s1=step1(), s5=step5(), flags=GUARD_STEP1).status == "data_uncertain"
    assert run(s1=step1(), s5=step5(ratios={"debt_servicing_ratio": ratio(45, "severe")}), flags=GUARD_STEP1).status == "data_uncertain"


def test_precedence_a_guarded_structural_is_data_uncertain_not_structural():
    flags = [flag("partial_balance_sheet", statement="balance_sheet", in_ttm_window=True, newest_period=True)]
    assert run(s1=step1(), s5=step5(ratios=STRUCTURAL), flags=flags).status == "data_uncertain"


def test_precedence_any_unclear_beats_by_design_and_all_by_design_is_by_design():
    assert run(s1=step1(), s5=step5()).status == "review_unclear"
    assert run(s5=step5()).status == "review_by_design"


# ---- conviction ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "v2, v4, expected",
    [
        ("Pass", "Pass", "high"),
        ("Strong Pass", "Pass", "high"),
        ("Pass", "Fail", "medium"),
        ("Fail", "Strong Pass", "medium"),
        ("Pass with caution", "Pass", "medium"),
        ("Pass with caution", "Pass with caution", "medium"),
        ("Pass with caution", "Fail", "medium"),
        ("Fail", "Fail", "low"),
        (None, "Pass", "medium"),
        (None, None, "medium"),
    ],
)
def test_conviction_levels(v2, v4, expected):
    assert conviction_for(v2, v4) == expected


def test_conviction_is_stored_with_a_status_and_for_a_clean_pass_family_row_but_never_for_other_verdicts():
    with_status = run(s1=step1(), s2=step(90, "Pass"), s4=step(5, "Fail"))
    assert (with_status.status, with_status.conviction) == ("review_unclear", "medium")
    clean = run(s1=step(90, "Pass"), s5=step(85, "Pass"))
    assert (clean.status, clean.reasons, clean.conviction) == (None, [], "high")
    assert run(s1=step1(), overall="Fail").conviction is None


def test_a_clean_ticker_stays_null():
    clean = run(s1=step(90, "Strong Pass"), s5=step5(score=80, verdict="Pass"), flags=[flag("scale_break", in_ttm_window=True)])
    assert clean.status is None and clean.reasons == []


def test_status_labels_cover_every_status_key():
    assert set(review.STATUS_LABELS) == {"review_structural", "data_uncertain", "review_unclear", "review_by_design"}
    assert review.STATUS_LABELS["review_by_design"] == "Review (by design)"
