from scoring.step5 import (
    BreachContextSignal,
    _evaluate_breach_context,
    classify_company_type,
    classify_interest_coverage,
    evaluate_current_ratio_breach_context,
    evaluate_debt_to_ebitda_breach_context,
    score_cet1,
    score_current_ratio,
    score_debt_servicing,
    score_debt_to_ebitda,
    score_gearing,
    score_npl,
    score_step5_bank,
    score_step5_reit,
    score_step5_standard,
)


def test_classify_bank():
    assert classify_company_type("Financial Services", "Banks - Diversified") == "Bank"


def test_classify_reit_by_sector():
    assert classify_company_type("Real Estate", "REIT - Retail") == "REIT/Property Developer"


def test_classify_reit_by_industry_text_outside_real_estate_sector():
    # Industry text containing "REIT" should classify even if sector isn't
    # exactly "Real Estate" -- matches the spec's "OR" condition.
    assert classify_company_type("Diversified", "Mortgage REIT") == "REIT/Property Developer"


def test_classify_standard():
    assert classify_company_type("Technology", "Consumer Electronics") == "Standard"


# --- Current Ratio: Comfortable-zone sub-tiers (unchanged from before the
# severity-band redesign whenever raw is already >= 1.0). score_current_ratio
# itself is UNCHANGED by the breach-context framework -- that's applied one
# level up, by score_step5_standard, only when this function's own result is
# still "borderline_fail" (see the score_step5_standard tests further down).
# RatioResult grew a 5th field (breach_context, defaults to ()) -- every
# expected tuple below has that appended. ---


def test_current_ratio_excellent_above_2():
    result = score_current_ratio(raw_ratio=2.5, adjusted_ratio=2.5)
    assert result == ("excellent", 100, False, False, ())


def test_current_ratio_good_boundary_at_2_is_good_not_excellent():
    result = score_current_ratio(raw_ratio=2.0, adjusted_ratio=2.0)
    assert result == ("good", 85, False, False, ())


def test_current_ratio_good_boundary_at_1_5_is_good_not_acceptable():
    result = score_current_ratio(raw_ratio=1.5, adjusted_ratio=1.5)
    assert result == ("good", 85, False, False, ())


def test_current_ratio_boundary_at_1_is_acceptable_not_borderline():
    result = score_current_ratio(raw_ratio=1.0, adjusted_ratio=1.0)
    assert result == ("acceptable", 70, False, False, ())


# --- Current Ratio: Borderline and Severe zones ---


def test_current_ratio_borderline_fails_with_no_deferred_revenue():
    # 0.9 is Borderline (0.7-1.0) -- no deferred revenue to rescue it here.
    # score_current_ratio itself still reports this as an unrescued Fail;
    # score_step5_standard's breach-context framework gets a separate,
    # later chance at it (see further down).
    result = score_current_ratio(raw_ratio=0.9, adjusted_ratio=0.9)
    assert result == ("borderline_fail", 0, True, False, ())


def test_current_ratio_boundary_at_0_7_is_borderline_not_severe():
    result = score_current_ratio(raw_ratio=0.7, adjusted_ratio=0.7)
    assert result == ("borderline_fail", 0, True, False, ())


def test_current_ratio_below_0_7_is_severe():
    result = score_current_ratio(raw_ratio=0.5, adjusted_ratio=0.5)
    assert result == ("severe", 0, True, False, ())


def test_current_ratio_severe_raw_but_deferred_revenue_only_lifts_it_to_borderline():
    # Mirrors CCL's real shape: deferred revenue lifts the adjusted ratio
    # from Severe (0.33) to Borderline (0.90), but not all the way to
    # Comfortable (>=1.0) -- a partial rescue isn't a full rescue, so this
    # still stands as a Fail (not saved_by_tiebreaker) at this function's
    # level -- the breach-context framework never reconsiders a Severe
    # breach (confirmed scope decision), and this ticker's RAW ratio was
    # Severe, so it's excluded from breach-context entirely regardless of
    # the adjusted value landing in Borderline.
    result = score_current_ratio(raw_ratio=0.33, adjusted_ratio=0.90)
    assert result == ("borderline_fail", 0, True, False, ())


# --- Current Ratio: deferred-revenue rescue (Comfortable via adjusted ratio) ---


def test_current_ratio_rescued_by_deferred_revenue_to_comfortable():
    # Mirrors ADBE's real shape: raw 0.75 (Borderline), deferred revenue
    # lifts the adjusted ratio to 1.84 (Comfortable) -- reads as a genuine
    # Pass-tier result, flagged as saved_by_tiebreaker.
    result = score_current_ratio(raw_ratio=0.75, adjusted_ratio=1.84)
    assert result == ("good", 85, False, True, ())


def test_current_ratio_rescue_boundary_at_exactly_1_0_counts_as_rescued():
    result = score_current_ratio(raw_ratio=0.9, adjusted_ratio=1.0)
    assert result == ("acceptable", 70, False, True, ())


def test_current_ratio_deferred_revenue_present_but_raw_already_comfortable_is_unaffected():
    # A company with SOME deferred revenue but a raw ratio already >= 1.0
    # must score off the RAW ratio, byte-identical to before this redesign
    # -- there's nothing to rescue, so the sub-tier must not shift just
    # because deferred revenue exists (this was a bug caught during design
    # verification: MTD/MCO/PTC-style tickers silently gained points before
    # this guard was added).
    result = score_current_ratio(raw_ratio=1.3, adjusted_ratio=1.6)
    assert result == ("acceptable", 70, False, False, ())


# --- Debt/EBITDA: Comfortable-zone sub-tiers (unchanged) ---
# score_debt_to_ebitda is now a PURE tier classifier -- no icr_is_safe
# param. Borderline's rescue logic (formerly a narrow icr_is_safe-only
# check right here) moved to score_step5_standard, which now calls the
# richer evaluate_debt_to_ebitda_breach_context whenever this function
# returns "borderline_fail" -- see the dedicated breach-context test
# sections further down for that logic's own tests.


def test_debt_to_ebitda_excellent_at_or_below_1():
    assert score_debt_to_ebitda(1.0) == ("excellent", 100, False, False, ())


def test_debt_to_ebitda_good():
    assert score_debt_to_ebitda(1.5) == ("good", 85, False, False, ())


def test_debt_to_ebitda_acceptable_boundary_at_2():
    assert score_debt_to_ebitda(2.0) == ("good", 85, False, False, ())
    assert score_debt_to_ebitda(2.5) == ("acceptable", 70, False, False, ())


def test_debt_to_ebitda_boundary_at_3_is_acceptable_not_borderline():
    result = score_debt_to_ebitda(3.0)
    assert result == ("acceptable", 70, False, False, ())


# --- Debt/EBITDA: Borderline and Severe zones (pure tier only here -- the
# breach-context rescue attempt happens one level up) ---


def test_debt_to_ebitda_borderline_unrescued_at_this_level():
    # 3.42 is Borderline (3.0-4.0) -- score_debt_to_ebitda alone always
    # reports this as unrescued now; whether it gets excused is entirely
    # score_step5_standard's / evaluate_debt_to_ebitda_breach_context's
    # decision (see the ABT-shaped end-to-end test further down for the
    # actual rescue scenario this replaces).
    result = score_debt_to_ebitda(3.42)
    assert result == ("borderline_fail", 0, True, False, ())


def test_debt_to_ebitda_boundary_at_4_is_borderline_not_severe():
    result = score_debt_to_ebitda(4.0)
    assert result == ("borderline_fail", 0, True, False, ())


def test_debt_to_ebitda_severe_above_4():
    # Mirrors ABBV's real shape: 4.31 is Severe (>4.0). Severe never
    # reaches the breach-context framework at all (confirmed scope
    # decision) -- always an unconditional Fail, no exceptions.
    result = score_debt_to_ebitda(4.31)
    assert result == ("severe", 0, True, False, ())


# --- Debt Servicing Ratio: Comfortable-zone sub-tiers (unchanged --
# score_debt_servicing keeps its own existing icr_is_safe rescue mechanism
# untouched; DSR is never itself a breach-context subject, only a primary-
# gate INPUT to the other two frameworks) ---


def test_debt_servicing_excellent_below_10():
    assert score_debt_servicing(5.0, icr_is_safe=False) == ("excellent", 100, False, False, ())


def test_debt_servicing_good():
    assert score_debt_servicing(15.0, icr_is_safe=False) == ("good", 85, False, False, ())


def test_debt_servicing_approaching_limit():
    assert score_debt_servicing(25.0, icr_is_safe=False) == ("approaching_limit", 60, False, False, ())


def test_debt_servicing_boundary_at_30_is_borderline_not_comfortable():
    result = score_debt_servicing(30.0, icr_is_safe=False)
    assert result == ("borderline_fail", 0, True, False, ())


# --- Debt Servicing Ratio: Borderline zone + Interest Coverage tiebreaker ---


def test_debt_servicing_borderline_saved_by_safe_icr():
    result = score_debt_servicing(35.0, icr_is_safe=True)
    assert result == ("borderline_saved_by_icr", 60, False, True, ())


def test_debt_servicing_borderline_not_saved_by_unsafe_icr():
    result = score_debt_servicing(35.0, icr_is_safe=False)
    assert result == ("borderline_fail", 0, True, False, ())


def test_debt_servicing_boundary_at_40_is_severe_not_borderline():
    result = score_debt_servicing(40.0, icr_is_safe=True)
    assert result == ("severe", 0, True, False, ())


def test_debt_servicing_severe_above_40_never_saved_even_with_safe_icr():
    result = score_debt_servicing(45.0, icr_is_safe=True)
    assert result == ("severe", 0, True, False, ())


# --- Interest Coverage Ratio classification ---


def test_icr_safe_above_3():
    assert classify_interest_coverage(3.5) == "safe"


def test_icr_boundary_at_3_is_tight_not_safe():
    assert classify_interest_coverage(3.0) == "tight"


def test_icr_tight_between_1_and_3():
    assert classify_interest_coverage(1.5) == "tight"


def test_icr_boundary_at_1_is_tight_not_dangerous():
    assert classify_interest_coverage(1.0) == "tight"


def test_icr_dangerous_below_1():
    assert classify_interest_coverage(0.5) == "dangerous"


def test_icr_not_applicable_when_none():
    assert classify_interest_coverage(None) == "not_applicable"


# --- NPL Ratio tiers (Bank, partial signal only) -- unchanged ---


def test_npl_excellent_below_1():
    assert score_npl(0.5) == ("excellent", 100, False, False, ())


def test_npl_good():
    assert score_npl(2.0) == ("good", 85, False, False, ())


def test_npl_boundary_at_1_is_good_not_excellent():
    assert score_npl(1.0) == ("good", 85, False, False, ())


def test_npl_acceptable():
    assert score_npl(4.0) == ("acceptable", 70, False, False, ())


def test_npl_boundary_at_3_is_acceptable_not_good():
    assert score_npl(3.0) == ("acceptable", 70, False, False, ())


def test_npl_fail_at_or_above_5():
    assert score_npl(5.0) == ("fail", 0, True, False, ())
    assert score_npl(7.5) == ("fail", 0, True, False, ())


# --- CET1 Ratio tiers (Bank, manual entry only) ---
# 2026-08-05 bands: <10 fail / 10-12 acceptable / 12-14 good / >=14
# excellent -- a fresh decision replacing both the original source doc's
# 10/11/13 bands and an earlier code-only 8/10/12 version.


def test_cet1_fail_below_10():
    assert score_cet1(9.9) == ("fail", 0, True, False, ())
    assert score_cet1(4.0) == ("fail", 0, True, False, ())


def test_cet1_boundary_at_10_is_acceptable():
    assert score_cet1(10.0) == ("acceptable", 70, False, False, ())


def test_cet1_acceptable_at_11():
    assert score_cet1(11.0) == ("acceptable", 70, False, False, ())


def test_cet1_boundary_at_12_is_good():
    assert score_cet1(12.0) == ("good", 85, False, False, ())


def test_cet1_good_at_13():
    assert score_cet1(13.0) == ("good", 85, False, False, ())


def test_cet1_boundary_at_14_is_excellent():
    assert score_cet1(14.0) == ("excellent", 100, False, False, ())


def test_cet1_excellent_above_14():
    assert score_cet1(15.0) == ("excellent", 100, False, False, ())


# --- Bank path (CET1 + NPL, 50/50 blend) ---


def test_bank_both_excellent_is_strong_pass():
    result = score_step5_bank(cet1_pct=15.0, npl_pct=0.5)
    assert result["score"] == 100
    assert result["hard_fail"] is False
    assert result["verdict"] == "Strong Pass"
    assert result["weights"] == {"cet1_ratio": 0.5, "npl_ratio": 0.5}
    assert result["ratios"]["cet1_ratio"]["label"] == "excellent"
    assert result["ratios"]["npl_ratio"]["label"] == "excellent"


def test_bank_blend_math_mixed_tiers():
    # CET1 "good" (85) + NPL "acceptable" (70) -> (85*0.5 + 70*0.5) = 77.5 -> 78
    result = score_step5_bank(cet1_pct=13.0, npl_pct=4.0)
    assert result["score"] == 78
    assert result["hard_fail"] is False
    assert result["verdict"] == "Pass"


def test_bank_cet1_hard_fail_overrides_even_with_excellent_npl():
    result = score_step5_bank(cet1_pct=6.0, npl_pct=0.5)
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_bank_npl_hard_fail_overrides_even_with_excellent_cet1():
    result = score_step5_bank(cet1_pct=15.0, npl_pct=6.0)
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


# --- Gearing Ratio tiers (REIT) -- unchanged ---


def test_gearing_excellent_below_30():
    assert score_gearing(25.0) == ("excellent", 100, False, False, ())


def test_gearing_good_boundary_at_30_is_good_not_excellent():
    result = score_gearing(30.0)
    assert result == ("good", 85, False, False, ())


def test_gearing_good():
    assert score_gearing(35.0) == ("good", 85, False, False, ())


def test_gearing_approaching_limit():
    assert score_gearing(42.0) == ("approaching_limit", 60, False, False, ())


def test_gearing_fail_above_45():
    result = score_gearing(50.0)
    assert result == ("fail", 0, True, False, ())


def test_gearing_boundary_at_45_is_approaching_limit_not_fail():
    result = score_gearing(45.0)
    assert result == ("approaching_limit", 60, False, False, ())


# --- score_step5_standard: end-to-end, real-ticker-shaped cases ---


def test_comfortable_company_completely_unaffected():
    # Mirrors AAPL's real shape: every ratio Comfortable, no deferred
    # revenue or ICR involvement at all.
    result = score_step5_standard(
        current_ratio=1.07, adjusted_current_ratio=1.15, debt_to_ebitda=0.53, debt_servicing_pct=0.0,
        interest_coverage_ratio=None,
    )
    assert result["hard_fail"] is False
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Pass"


def test_severe_breach_fails_regardless_of_strong_icr():
    # Mirrors ABBV's real shape: Debt/EBITDA is Severe (4.31) despite a
    # strong ICR (5.96x) -- Severe can never be saved.
    result = score_step5_standard(
        current_ratio=0.80, adjusted_current_ratio=0.80, debt_to_ebitda=4.31, debt_servicing_pct=12.5,
        interest_coverage_ratio=5.96,
    )
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_borderline_debt_to_ebitda_with_strong_icr_becomes_pass_with_caution():
    # Mirrors ABT's real shape.
    result = score_step5_standard(
        current_ratio=1.39, adjusted_current_ratio=1.39, debt_to_ebitda=3.42, debt_servicing_pct=4.0,
        interest_coverage_ratio=12.45,
    )
    assert result["hard_fail"] is False
    assert result["pass_with_caution"] is True
    assert result["verdict"] == "Pass with caution"


def test_borderline_debt_to_ebitda_with_weak_icr_still_fails():
    # Mirrors SYF's real shape.
    result = score_step5_standard(
        current_ratio=1.33, adjusted_current_ratio=1.33, debt_to_ebitda=3.23, debt_servicing_pct=0.0,
        interest_coverage_ratio=1.13,
    )
    assert result["hard_fail"] is True
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Fail"


def test_current_ratio_saved_by_deferred_revenue_becomes_pass_with_caution():
    # Mirrors ADBE's real shape.
    result = score_step5_standard(
        current_ratio=0.75, adjusted_current_ratio=1.84, debt_to_ebitda=0.67, debt_servicing_pct=1.2,
        interest_coverage_ratio=67.3,
    )
    assert result["hard_fail"] is False
    assert result["pass_with_caution"] is True
    assert result["verdict"] == "Pass with caution"
    # Unblended average would be (85+100+100)/3 = 95 -- Current Ratio's
    # deferred-revenue rescue lands "good" (85), not BORDERLINE_SAVED_SCORE,
    # since it re-scores off the adjusted ratio's own Comfortable-zone tier.
    # PASS_WITH_CAUTION_SCORE_CAP must bring this down to 74, or the number
    # (95) contradicts the amber "caution" color a real breach earns.
    assert result["score"] == 74


def test_pass_with_caution_score_is_capped_even_when_natural_blend_is_100():
    # Mirrors AMP's real shape: Current Ratio rescued all the way to
    # "excellent" (100) while Debt/EBITDA and DSR are also excellent -- the
    # unblended average would be a perfect 100, yet a real breach occurred.
    result = score_step5_standard(
        current_ratio=0.80, adjusted_current_ratio=2.5, debt_to_ebitda=0.5, debt_servicing_pct=2.0,
        interest_coverage_ratio=20.0,
    )
    assert result["pass_with_caution"] is True
    assert result["score"] == 74


def test_pass_with_caution_cap_does_not_raise_an_already_low_score():
    # If the natural blend is already below the cap (e.g. one ratio only
    # just clears the deferred-revenue rescue at "acceptable"), the cap
    # must not artificially inflate it back up to 74.
    result = score_step5_standard(
        current_ratio=0.9, adjusted_current_ratio=1.0, debt_to_ebitda=2.9, debt_servicing_pct=25.0,
        interest_coverage_ratio=None,
    )
    # (70 acceptable + 70 acceptable + 60 approaching_limit) / 3 = 66.67 -> 67
    assert result["score"] == 67
    # 67 < 70 -- the rescue is redundant here (see
    # test_tiebreaker_saved_breach_with_sub_70_blend_stays_fail below):
    # this ticker genuinely fails regardless of Current Ratio's tiebreaker.
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Fail"


def test_tiebreaker_saved_breach_with_sub_70_blend_stays_fail():
    # Confirmed real bug (2026-07-31 investigation): a rescued breach is a
    # Pass VARIANT -- it must never promote an otherwise-failing blend into
    # a passing verdict. Debt/EBITDA's breach is saved by ICR (60 pts), but
    # Debt Servicing Ratio is separately just weak -- not breaching, only
    # "approaching_limit" (60 pts, non-breach) -- so no ratio here is
    # hard_fail, yet the blend (70+60+60)/3 = 63.3 -> 63 is well under the
    # 70 Pass floor. Previously this read "Pass with caution" at score 63.
    result = score_step5_standard(
        current_ratio=1.0, adjusted_current_ratio=1.0, debt_to_ebitda=3.5, debt_servicing_pct=25.0,
        interest_coverage_ratio=5.0,
    )
    assert result["ratios"]["debt_to_ebitda"]["saved_by_tiebreaker"] is True
    assert result["hard_fail"] is False
    assert result["score"] == 63
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Fail"


def test_current_ratio_borderline_without_deferred_revenue_still_fails():
    # Mirrors AZO's real shape: Borderline (0.89), no deferred revenue.
    result = score_step5_standard(
        current_ratio=0.89, adjusted_current_ratio=0.89, debt_to_ebitda=2.11, debt_servicing_pct=15.4,
        interest_coverage_ratio=7.63,
    )
    assert result["hard_fail"] is True
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Fail"


def test_debt_to_ebitda_breach_context_gate_uses_raw_dsr_not_dsrs_own_rescue():
    # DSR itself is Borderline (35%) but rescued by ICR via ITS OWN,
    # unchanged icr_is_safe mechanism -- saved_by_tiebreaker=True on its
    # own ratio, exactly as before this redesign (this is what the old
    # test name "...share one ICR signal" described). But Debt/EBITDA's
    # breach-context PRIMARY GATE checks DSR's raw value (< 30%, literal
    # threshold per spec), not DSR's own possibly-rescued classification --
    # a DSR that itself needed rescuing isn't "clean" for the purposes of
    # vouching for a DIFFERENT ratio's breach. So Debt/EBITDA's own
    # Borderline breach does NOT qualify here even though the same ICR
    # that rescued DSR would read "favorable" as one of Debt/EBITDA's own
    # secondary signals too -- the primary gate never lets it reach that
    # secondary-signal evaluation at all. This is a deliberate behavior
    # change from the old narrow icr_is_safe-only mechanism (which rescued
    # both ratios off the exact same boolean, independently).
    result = score_step5_standard(
        current_ratio=2.5, adjusted_current_ratio=2.5, debt_to_ebitda=3.5, debt_servicing_pct=35.0,
        interest_coverage_ratio=5.0,
    )
    assert result["ratios"]["debt_servicing_ratio"]["saved_by_tiebreaker"] is True
    assert result["ratios"]["debt_to_ebitda"]["saved_by_tiebreaker"] is False
    assert result["ratios"]["debt_to_ebitda"]["label"] == "borderline_fail"
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_hard_fail_overrides_score_even_with_two_excellent_ratios():
    # Debt Servicing Ratio is Severe -- verdict must be Fail even though the
    # blended score alone would land well into Pass territory.
    result = score_step5_standard(
        current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=0.5, debt_servicing_pct=45.0,
        interest_coverage_ratio=None,
    )
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_no_hard_fail_one_approaching_limit_still_passes():
    result = score_step5_standard(
        current_ratio=2.5, adjusted_current_ratio=2.5, debt_to_ebitda=0.8, debt_servicing_pct=25.0,
        interest_coverage_ratio=None,
    )
    assert result["hard_fail"] is False
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Pass"


def test_all_excellent_is_strong_pass():
    result = score_step5_standard(
        current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=0.5, debt_servicing_pct=5.0,
        interest_coverage_ratio=None,
    )
    assert result["score"] == 100
    assert result["hard_fail"] is False
    assert result["verdict"] == "Strong Pass"


# --- REIT path -- unchanged ---


def test_reit_hard_fail_overrides():
    result = score_step5_reit(gearing_pct=50.0)
    assert result["score"] == 0
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_reit_healthy_passes():
    result = score_step5_reit(gearing_pct=25.0)
    assert result["score"] == 100
    assert result["hard_fail"] is False
    assert result["verdict"] == "Strong Pass"


def test_reit_approaching_limit_now_reads_fail_not_pass():
    # Residual gap found during the 2026-07-31 investigation, fixed by the
    # SAME hoisted _verdict_for floor as the Standard-path fallback (not a
    # second, separate fix): gearing 42% is "approaching_limit" (60pts,
    # hard_fail=False, no tiebreaker involved at all -- REIT gearing has no
    # rescue mechanism). Previously this read "Pass" at score 60 (AVB, EQR,
    # HST, KIM, O, REG's real shape) despite being well under the shared 70
    # Pass floor.
    result = score_step5_reit(gearing_pct=42.0)
    assert result["score"] == 60
    assert result["hard_fail"] is False
    assert result["verdict"] == "Fail"


# --- Breach-context framework: shared gate math (_evaluate_breach_context) ---


def test_evaluate_breach_context_primary_gate_fail_blocks_regardless_of_signals():
    signals = [BreachContextSignal("a", "favorable"), BreachContextSignal("b", "favorable")]
    assert _evaluate_breach_context(False, signals) == (False, 0)


def test_evaluate_breach_context_no_computable_signals_does_not_qualify():
    signals = [BreachContextSignal("a", "not_computable"), BreachContextSignal("b", "not_computable")]
    assert _evaluate_breach_context(True, signals) == (False, 0)


def test_evaluate_breach_context_exact_half_favorable_is_not_a_strict_majority():
    signals = [BreachContextSignal("a", "favorable"), BreachContextSignal("b", "unfavorable")]
    assert _evaluate_breach_context(True, signals) == (False, 0)


def test_evaluate_breach_context_strict_majority_qualifies_with_graded_score():
    signals = [
        BreachContextSignal("a", "favorable"),
        BreachContextSignal("b", "favorable"),
        BreachContextSignal("c", "unfavorable"),
    ]
    qualifies, score = _evaluate_breach_context(True, signals)
    assert qualifies is True
    # 2/3 favorable -> 40 + (60-40)*(2/3) = 53.3 -> 53
    assert score == 53


def test_evaluate_breach_context_all_favorable_lands_at_borderline_saved_score():
    signals = [BreachContextSignal("a", "favorable"), BreachContextSignal("b", "favorable")]
    qualifies, score = _evaluate_breach_context(True, signals)
    assert qualifies is True
    assert score == 60  # BORDERLINE_SAVED_SCORE -- same ceiling the old narrow ICR-only rescue used


def test_evaluate_breach_context_single_computable_favorable_lands_at_ceiling():
    # A single computable signal that's favorable is, by definition, 100%
    # favorable -- lands at the ceiling (BORDERLINE_SAVED_SCORE), not the
    # floor. (MARGINAL_SCORE_FLOOR is only approached in the limit as the
    # favorable fraction nears 50% from above across MANY signals -- with
    # this app's realistic 3-4 signal frameworks, the tightest achievable
    # qualifying fraction is 2-of-3, see the strict-majority test above.)
    signals = [BreachContextSignal("a", "favorable")]
    qualifies, score = _evaluate_breach_context(True, signals)
    assert qualifies is True
    assert score == 60


def test_evaluate_breach_context_non_gating_signals_excluded_from_vote():
    # 2 of 3 GATING signals favorable (matches
    # test_evaluate_breach_context_strict_majority_qualifies_with_graded_score,
    # score 53) -- adding non-gating signals of EITHER status must not
    # shift the outcome at all. If "d" below were wrongly counted,
    # computable would be 4 and favorable 2 -- 2*2=4 is NOT > 4, which
    # would flip this to NOT qualifying at all, a clearly divergent result
    # this test would catch.
    signals = [
        BreachContextSignal("a", "favorable"),
        BreachContextSignal("b", "favorable"),
        BreachContextSignal("c", "unfavorable"),
        BreachContextSignal("d", "unfavorable", counts_toward_gate=False),
        BreachContextSignal("e", "not_computable", counts_toward_gate=False),
    ]
    qualifies, score = _evaluate_breach_context(True, signals)
    assert qualifies is True
    assert score == 53


# --- Debt/EBITDA breach-context: primary gates ---


def test_debt_to_ebitda_breach_context_current_ratio_gate_fails():
    qualifies, _, _ = evaluate_debt_to_ebitda_breach_context(
        current_ratio=0.95,
        debt_servicing_pct=10.0,
        debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=7.0,
        debt_to_ebitda_oldest_year="2021",
        fcf_ttm=1e9,
        total_debt=2e9,
        interest_coverage_ratio=10.0,
        net_debt=1e9,
        ebitda_ttm=1e9,
    )
    assert qualifies is False


def test_debt_to_ebitda_breach_context_dsr_gate_fails():
    qualifies, _, _ = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5,
        debt_servicing_pct=30.0,
        debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=7.0,
        debt_to_ebitda_oldest_year="2021",
        fcf_ttm=1e9,
        total_debt=2e9,
        interest_coverage_ratio=10.0,
        net_debt=1e9,
        ebitda_ttm=1e9,
    )
    assert qualifies is False


# --- Debt/EBITDA breach-context: secondary signals ---


def test_debt_to_ebitda_breach_context_trend_not_computable_when_no_history():
    qualifies, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=None, debt_to_ebitda_oldest_year=None,
        fcf_ttm=None, total_debt=None, interest_coverage_ratio=None, net_debt=None, ebitda_ttm=None,
    )
    trend = next(s for s in signals if s.key == "trend")
    assert trend.status == "not_computable"
    assert qualifies is False  # nothing computable at all


def test_debt_to_ebitda_breach_context_declining_trend_is_favorable():
    qualifies, score, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=7.0, debt_to_ebitda_oldest_year="2021",
        fcf_ttm=None, total_debt=None, interest_coverage_ratio=None, net_debt=None, ebitda_ttm=None,
    )
    trend = next(s for s in signals if s.key == "trend")
    assert trend.status == "favorable"
    assert qualifies is True  # only computable signal, favorable -> 100% -> ceiling
    assert score == 60


def test_debt_to_ebitda_breach_context_flat_trend_is_unfavorable():
    qualifies, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=3.6, debt_to_ebitda_oldest_year="2021",  # < 10% relative move
        fcf_ttm=None, total_debt=None, interest_coverage_ratio=None, net_debt=None, ebitda_ttm=None,
    )
    trend = next(s for s in signals if s.key == "trend")
    assert trend.status == "unfavorable"
    assert qualifies is False


def test_debt_to_ebitda_breach_context_strong_fcf_is_favorable():
    qualifies, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=None, debt_to_ebitda_oldest_year=None,
        fcf_ttm=300e6, total_debt=1000e6, interest_coverage_ratio=None, net_debt=None, ebitda_ttm=None,  # 30% >= 15%
    )
    fcf = next(s for s in signals if s.key == "fcf_vs_debt")
    assert fcf.status == "favorable"
    assert qualifies is True


def test_debt_to_ebitda_breach_context_weak_fcf_is_unfavorable():
    qualifies, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=None, debt_to_ebitda_oldest_year=None,
        fcf_ttm=50e6, total_debt=1000e6, interest_coverage_ratio=None, net_debt=None, ebitda_ttm=None,  # 5% < 15%
    )
    fcf = next(s for s in signals if s.key == "fcf_vs_debt")
    assert fcf.status == "unfavorable"
    assert qualifies is False


def test_debt_to_ebitda_breach_context_negative_fcf_is_unfavorable():
    qualifies, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=None, debt_to_ebitda_oldest_year=None,
        fcf_ttm=-50e6, total_debt=1000e6, interest_coverage_ratio=None, net_debt=None, ebitda_ttm=None,
    )
    fcf = next(s for s in signals if s.key == "fcf_vs_debt")
    assert fcf.status == "unfavorable"


def test_debt_to_ebitda_breach_context_cause_of_debt_always_not_computable_and_non_gating():
    _, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=7.0, debt_to_ebitda_oldest_year="2021",
        fcf_ttm=300e6, total_debt=1000e6, interest_coverage_ratio=20.0, net_debt=800e6, ebitda_ttm=500e6,
    )
    cause = next(s for s in signals if s.key == "cause_of_debt")
    assert cause.status == "not_computable"
    assert cause.counts_toward_gate is False
    assert "recent acquisition" in cause.detail


def test_debt_to_ebitda_breach_context_net_vs_gross_is_informational_only():
    _, _, signals = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.5, debt_servicing_pct=10.0, debt_to_ebitda_current=3.5,
        debt_to_ebitda_oldest=None, debt_to_ebitda_oldest_year=None,
        fcf_ttm=None, total_debt=None, interest_coverage_ratio=None, net_debt=800e6, ebitda_ttm=500e6,
    )
    net_vs_gross = next(s for s in signals if s.key == "net_vs_gross_debt")
    assert net_vs_gross.counts_toward_gate is False


def test_debt_to_ebitda_breach_context_majority_favorable_end_to_end():
    # Mirrors ABT's real shape (the ICR-only-rescue scenario the old
    # narrow mechanism used to handle) -- with a declining trend and
    # strong FCF also provided now, all 3 computable signals favor a
    # downgrade.
    qualifies, score, _ = evaluate_debt_to_ebitda_breach_context(
        current_ratio=1.39, debt_servicing_pct=4.0, debt_to_ebitda_current=3.42,
        debt_to_ebitda_oldest=5.0, debt_to_ebitda_oldest_year="2021",
        fcf_ttm=300e6, total_debt=1000e6, interest_coverage_ratio=12.45, net_debt=800e6, ebitda_ttm=500e6,
    )
    assert qualifies is True
    assert score == 60  # 3/3 favorable -> ceiling


# --- Current Ratio breach-context: primary gates ---


def test_current_ratio_breach_context_debt_to_ebitda_gate_fails():
    qualifies, _, _ = evaluate_current_ratio_breach_context(
        debt_to_ebitda=3.5, debt_servicing_pct=10.0, current_ratio_current=0.9,
        current_ratio_oldest=0.95, current_ratio_oldest_year="2021",
        deferred_revenue=200.0, current_liabilities=1000.0,
        cash_and_equivalents=600.0, current_assets=950.0, liquid_current_assets=900.0,
    )
    assert qualifies is False


def test_current_ratio_breach_context_dsr_gate_fails():
    qualifies, _, _ = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=30.0, current_ratio_current=0.9,
        current_ratio_oldest=0.95, current_ratio_oldest_year="2021",
        deferred_revenue=200.0, current_liabilities=1000.0,
        cash_and_equivalents=600.0, current_assets=950.0, liquid_current_assets=900.0,
    )
    assert qualifies is False


# --- Current Ratio breach-context: secondary signals ---


def test_current_ratio_breach_context_material_deferred_revenue_is_favorable():
    qualifies, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=10.0, current_ratio_current=0.9,
        current_ratio_oldest=None, current_ratio_oldest_year=None,
        deferred_revenue=200.0, current_liabilities=1000.0,  # 20% >= 15% material
        cash_and_equivalents=None, current_assets=None, liquid_current_assets=None,
    )
    dr = next(s for s in signals if s.key == "deferred_revenue")
    assert dr.status == "favorable"
    assert qualifies is True


def test_current_ratio_breach_context_zero_deferred_revenue_is_unfavorable():
    # Mirrors MA's real shape -- MA carries no deferred revenue at all.
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=0.9, debt_servicing_pct=3.5, current_ratio_current=0.98,
        current_ratio_oldest=None, current_ratio_oldest_year=None,
        deferred_revenue=0.0, current_liabilities=1000.0,
        cash_and_equivalents=None, current_assets=None, liquid_current_assets=None,
    )
    dr = next(s for s in signals if s.key == "deferred_revenue")
    assert dr.status == "unfavorable"


def test_current_ratio_breach_context_stable_trend_is_favorable():
    # Inverse framing from Debt/EBITDA's trend -- NOT declining (stable or
    # even a small move either way) is the favorable case here.
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=10.0, current_ratio_current=0.98,
        current_ratio_oldest=1.0, current_ratio_oldest_year="2021",  # well under 10% move
        deferred_revenue=None, current_liabilities=None,
        cash_and_equivalents=None, current_assets=None, liquid_current_assets=None,
    )
    trend = next(s for s in signals if s.key == "trend")
    assert trend.status == "favorable"


def test_current_ratio_breach_context_declining_trend_is_unfavorable():
    # Mirrors MA's real shape -- Current Ratio genuinely declined ~24% over
    # 5 years (1.29 -> 0.98), a real deterioration, not just noise.
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=0.9, debt_servicing_pct=3.5, current_ratio_current=0.98,
        current_ratio_oldest=1.29, current_ratio_oldest_year="2021",
        deferred_revenue=None, current_liabilities=None,
        cash_and_equivalents=None, current_assets=None, liquid_current_assets=None,
    )
    trend = next(s for s in signals if s.key == "trend")
    assert trend.status == "unfavorable"


def test_current_ratio_breach_context_strong_cash_position_is_favorable():
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=10.0, current_ratio_current=0.9,
        current_ratio_oldest=None, current_ratio_oldest_year=None,
        deferred_revenue=None, current_liabilities=1000.0,
        cash_and_equivalents=600.0, current_assets=None, liquid_current_assets=None,  # 60% >= 50%
    )
    cash = next(s for s in signals if s.key == "cash_position")
    assert cash.status == "favorable"


def test_current_ratio_breach_context_weak_cash_position_is_unfavorable():
    # Mirrors MA's real shape -- cash covers only ~34% of current liabilities.
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=10.0, current_ratio_current=0.9,
        current_ratio_oldest=None, current_ratio_oldest_year=None,
        deferred_revenue=None, current_liabilities=1000.0,
        cash_and_equivalents=340.0, current_assets=None, liquid_current_assets=None,  # 34% < 50%
    )
    cash = next(s for s in signals if s.key == "cash_position")
    assert cash.status == "unfavorable"


def test_current_ratio_breach_context_liquid_assets_favorable():
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=10.0, current_ratio_current=0.9,
        current_ratio_oldest=None, current_ratio_oldest_year=None,
        deferred_revenue=None, current_liabilities=None,
        cash_and_equivalents=None, current_assets=1000.0, liquid_current_assets=900.0,  # 90% >= 50%
    )
    quality = next(s for s in signals if s.key == "asset_quality")
    assert quality.status == "favorable"


def test_current_ratio_breach_context_inventory_heavy_assets_unfavorable():
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=2.0, debt_servicing_pct=10.0, current_ratio_current=0.9,
        current_ratio_oldest=None, current_ratio_oldest_year=None,
        deferred_revenue=None, current_liabilities=None,
        cash_and_equivalents=None, current_assets=1000.0, liquid_current_assets=300.0,  # 30% < 50%
    )
    quality = next(s for s in signals if s.key == "asset_quality")
    assert quality.status == "unfavorable"


def test_current_ratio_breach_context_undrawn_revolver_always_not_computable_and_non_gating():
    _, _, signals = evaluate_current_ratio_breach_context(
        debt_to_ebitda=0.9, debt_servicing_pct=3.5, current_ratio_current=0.98,
        current_ratio_oldest=1.29, current_ratio_oldest_year="2021",
        deferred_revenue=0.0, current_liabilities=1000.0,
        cash_and_equivalents=340.0, current_assets=980.0, liquid_current_assets=550.0,
    )
    revolver = next(s for s in signals if s.key == "undrawn_revolving_credit")
    assert revolver.status == "not_computable"
    assert revolver.counts_toward_gate is False


def test_current_ratio_breach_context_ma_real_shape_does_not_qualify():
    # Confirmed against MA's actual live cached data (2026-08-01): 3 of 4
    # computable signals are unfavorable (zero deferred revenue, a genuine
    # ~24% 5yr decline, cash covering only 34% of current liabilities) --
    # only asset_quality (56% liquid) is favorable. Primary gates DO pass
    # cleanly (Debt/EBITDA 0.90, DSR 3.5%), but that alone isn't enough --
    # this is the real-data case that motivated the whole framework, and
    # it correctly stays a Fail rather than being rescued regardless of
    # the surrounding evidence.
    qualifies, _, _ = evaluate_current_ratio_breach_context(
        debt_to_ebitda=0.898, debt_servicing_pct=3.54, current_ratio_current=0.981,
        current_ratio_oldest=1.29, current_ratio_oldest_year="2021",
        deferred_revenue=0.0, current_liabilities=1000.0,
        cash_and_equivalents=340.0, current_assets=980.0, liquid_current_assets=550.0,
    )
    assert qualifies is False


def test_current_ratio_breach_context_majority_favorable_qualifies():
    # A hypothetical where the majority DOES support a downgrade -- stable
    # trend, material deferred revenue, strong cash, liquid assets.
    qualifies, score, _ = evaluate_current_ratio_breach_context(
        debt_to_ebitda=0.9, debt_servicing_pct=3.5, current_ratio_current=0.98,
        current_ratio_oldest=1.0, current_ratio_oldest_year="2021",
        deferred_revenue=200.0, current_liabilities=1000.0,
        cash_and_equivalents=600.0, current_assets=980.0, liquid_current_assets=900.0,
    )
    assert qualifies is True
    assert score == 60  # all 4 computable favorable -> ceiling


# --- Full end-to-end integration via score_step5_standard ---


def test_current_ratio_breach_context_end_to_end_becomes_pass_with_caution():
    # Same majority-favorable inputs as
    # test_current_ratio_breach_context_majority_favorable_qualifies, run
    # through the full orchestrator to confirm the downgrade actually
    # reaches the blended score/verdict, capped exactly like the existing
    # deferred-revenue-rescue and ICR-rescue paths.
    result = score_step5_standard(
        current_ratio=0.98, adjusted_current_ratio=0.98, debt_to_ebitda=0.9, debt_servicing_pct=3.5,
        interest_coverage_ratio=27.8,
        current_ratio_oldest=1.0, current_ratio_oldest_year="2021",
        deferred_revenue=200.0, current_liabilities=1000.0,
        cash_and_equivalents=600.0, current_assets=980.0, liquid_current_assets=900.0,
    )
    assert result["ratios"]["current_ratio"]["label"] == "marginal_via_breach_context"
    assert result["ratios"]["current_ratio"]["saved_by_tiebreaker"] is True
    assert result["pass_with_caution"] is True
    assert result["verdict"] == "Pass with caution"
    # Natural blend (60+100+100)/3=86.7 would otherwise be well into Pass --
    # capped at 74, same as every other saved_by_tiebreaker path.
    assert result["score"] == 74


def test_ma_real_shape_end_to_end_stays_fail():
    # Full integration check against MA's actual live cached data
    # (2026-08-01) -- confirms the framework doesn't force a rescue just
    # because it exists; the real secondary signals here don't support one.
    result = score_step5_standard(
        current_ratio=0.981, adjusted_current_ratio=0.981, debt_to_ebitda=0.898, debt_servicing_pct=3.54,
        interest_coverage_ratio=27.8,
        current_ratio_oldest=1.29, current_ratio_oldest_year="2021",
        deferred_revenue=0.0, current_liabilities=1000.0,
        cash_and_equivalents=340.0, current_assets=980.0, liquid_current_assets=550.0,
    )
    assert result["ratios"]["current_ratio"]["label"] == "borderline_fail"
    assert result["ratios"]["current_ratio"]["saved_by_tiebreaker"] is False
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"
