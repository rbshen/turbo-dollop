from scoring.step5 import (
    classify_company_type,
    classify_interest_coverage,
    score_current_ratio,
    score_debt_servicing,
    score_debt_to_ebitda,
    score_gearing,
    score_npl,
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
# severity-band redesign whenever raw is already >= 1.0) ---


def test_current_ratio_excellent_above_2():
    result = score_current_ratio(raw_ratio=2.5, adjusted_ratio=2.5)
    assert result == ("excellent", 100, False, False)


def test_current_ratio_good_boundary_at_2_is_good_not_excellent():
    result = score_current_ratio(raw_ratio=2.0, adjusted_ratio=2.0)
    assert result == ("good", 85, False, False)


def test_current_ratio_good_boundary_at_1_5_is_good_not_acceptable():
    result = score_current_ratio(raw_ratio=1.5, adjusted_ratio=1.5)
    assert result == ("good", 85, False, False)


def test_current_ratio_boundary_at_1_is_acceptable_not_borderline():
    result = score_current_ratio(raw_ratio=1.0, adjusted_ratio=1.0)
    assert result == ("acceptable", 70, False, False)


# --- Current Ratio: Borderline and Severe zones ---


def test_current_ratio_borderline_fails_with_no_deferred_revenue():
    # 0.9 is Borderline (0.7-1.0) -- no deferred revenue to rescue it, so
    # it stands as a Fail (Current Ratio's only tiebreaker is deferred
    # revenue; there's no second chance the way Debt/EBITDA/DSR get ICR).
    result = score_current_ratio(raw_ratio=0.9, adjusted_ratio=0.9)
    assert result == ("borderline_fail", 0, True, False)


def test_current_ratio_boundary_at_0_7_is_borderline_not_severe():
    result = score_current_ratio(raw_ratio=0.7, adjusted_ratio=0.7)
    assert result == ("borderline_fail", 0, True, False)


def test_current_ratio_below_0_7_is_severe():
    result = score_current_ratio(raw_ratio=0.5, adjusted_ratio=0.5)
    assert result == ("severe", 0, True, False)


def test_current_ratio_severe_raw_but_deferred_revenue_only_lifts_it_to_borderline():
    # Mirrors CCL's real shape: deferred revenue lifts the adjusted ratio
    # from Severe (0.33) to Borderline (0.90), but not all the way to
    # Comfortable (>=1.0) -- a partial rescue isn't a full rescue, so this
    # still stands as a Fail (not saved_by_tiebreaker).
    result = score_current_ratio(raw_ratio=0.33, adjusted_ratio=0.90)
    assert result == ("borderline_fail", 0, True, False)


# --- Current Ratio: deferred-revenue rescue (Comfortable via adjusted ratio) ---


def test_current_ratio_rescued_by_deferred_revenue_to_comfortable():
    # Mirrors ADBE's real shape: raw 0.75 (Borderline), deferred revenue
    # lifts the adjusted ratio to 1.84 (Comfortable) -- reads as a genuine
    # Pass-tier result, flagged as saved_by_tiebreaker.
    result = score_current_ratio(raw_ratio=0.75, adjusted_ratio=1.84)
    assert result == ("good", 85, False, True)


def test_current_ratio_rescue_boundary_at_exactly_1_0_counts_as_rescued():
    result = score_current_ratio(raw_ratio=0.9, adjusted_ratio=1.0)
    assert result == ("acceptable", 70, False, True)


def test_current_ratio_deferred_revenue_present_but_raw_already_comfortable_is_unaffected():
    # A company with SOME deferred revenue but a raw ratio already >= 1.0
    # must score off the RAW ratio, byte-identical to before this redesign
    # -- there's nothing to rescue, so the sub-tier must not shift just
    # because deferred revenue exists (this was a bug caught during design
    # verification: MTD/MCO/PTC-style tickers silently gained points before
    # this guard was added).
    result = score_current_ratio(raw_ratio=1.3, adjusted_ratio=1.6)
    assert result == ("acceptable", 70, False, False)


# --- Debt/EBITDA: Comfortable-zone sub-tiers (unchanged) ---


def test_debt_to_ebitda_excellent_at_or_below_1():
    assert score_debt_to_ebitda(1.0, icr_is_safe=False) == ("excellent", 100, False, False)


def test_debt_to_ebitda_good():
    assert score_debt_to_ebitda(1.5, icr_is_safe=False) == ("good", 85, False, False)


def test_debt_to_ebitda_acceptable_boundary_at_2():
    assert score_debt_to_ebitda(2.0, icr_is_safe=False) == ("good", 85, False, False)
    assert score_debt_to_ebitda(2.5, icr_is_safe=False) == ("acceptable", 70, False, False)


def test_debt_to_ebitda_boundary_at_3_is_acceptable_not_borderline():
    result = score_debt_to_ebitda(3.0, icr_is_safe=False)
    assert result == ("acceptable", 70, False, False)


# --- Debt/EBITDA: Borderline zone + Interest Coverage tiebreaker ---


def test_debt_to_ebitda_borderline_saved_by_safe_icr():
    # Mirrors ABT's real shape: 3.42 is Borderline (3.0-4.0), ICR is safe
    # (>3x) -- excused, reads as Pass with caution at the standard-level.
    result = score_debt_to_ebitda(3.42, icr_is_safe=True)
    assert result == ("borderline_saved_by_icr", 60, False, True)


def test_debt_to_ebitda_borderline_not_saved_by_unsafe_icr():
    # Mirrors SYF's real shape: 3.23 is Borderline, ICR is tight (1.13,
    # <=3x) -- not excused, stands as a Fail.
    result = score_debt_to_ebitda(3.23, icr_is_safe=False)
    assert result == ("borderline_fail", 0, True, False)


def test_debt_to_ebitda_boundary_at_4_is_borderline_not_severe():
    result = score_debt_to_ebitda(4.0, icr_is_safe=True)
    assert result == ("borderline_saved_by_icr", 60, False, True)


def test_debt_to_ebitda_severe_above_4_never_saved_even_with_safe_icr():
    # Mirrors ABBV's real shape: 4.31 is Severe (>4.0) despite a strong ICR
    # (5.96x) -- Severe never has a tiebreaker, no exceptions.
    result = score_debt_to_ebitda(4.31, icr_is_safe=True)
    assert result == ("severe", 0, True, False)


# --- Debt Servicing Ratio: Comfortable-zone sub-tiers (unchanged) ---


def test_debt_servicing_excellent_below_10():
    assert score_debt_servicing(5.0, icr_is_safe=False) == ("excellent", 100, False, False)


def test_debt_servicing_good():
    assert score_debt_servicing(15.0, icr_is_safe=False) == ("good", 85, False, False)


def test_debt_servicing_approaching_limit():
    assert score_debt_servicing(25.0, icr_is_safe=False) == ("approaching_limit", 60, False, False)


def test_debt_servicing_boundary_at_30_is_borderline_not_comfortable():
    result = score_debt_servicing(30.0, icr_is_safe=False)
    assert result == ("borderline_fail", 0, True, False)


# --- Debt Servicing Ratio: Borderline zone + Interest Coverage tiebreaker ---


def test_debt_servicing_borderline_saved_by_safe_icr():
    result = score_debt_servicing(35.0, icr_is_safe=True)
    assert result == ("borderline_saved_by_icr", 60, False, True)


def test_debt_servicing_borderline_not_saved_by_unsafe_icr():
    result = score_debt_servicing(35.0, icr_is_safe=False)
    assert result == ("borderline_fail", 0, True, False)


def test_debt_servicing_boundary_at_40_is_severe_not_borderline():
    result = score_debt_servicing(40.0, icr_is_safe=True)
    assert result == ("severe", 0, True, False)


def test_debt_servicing_severe_above_40_never_saved_even_with_safe_icr():
    result = score_debt_servicing(45.0, icr_is_safe=True)
    assert result == ("severe", 0, True, False)


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
    assert score_npl(0.5) == ("excellent", 100, False, False)


def test_npl_good():
    assert score_npl(2.0) == ("good", 85, False, False)


def test_npl_boundary_at_1_is_good_not_excellent():
    assert score_npl(1.0) == ("good", 85, False, False)


def test_npl_acceptable():
    assert score_npl(4.0) == ("acceptable", 70, False, False)


def test_npl_boundary_at_3_is_acceptable_not_good():
    assert score_npl(3.0) == ("acceptable", 70, False, False)


def test_npl_fail_at_or_above_5():
    assert score_npl(5.0) == ("fail", 0, True, False)
    assert score_npl(7.5) == ("fail", 0, True, False)


# --- Gearing Ratio tiers (REIT) -- unchanged ---


def test_gearing_excellent_below_30():
    assert score_gearing(25.0) == ("excellent", 100, False, False)


def test_gearing_good_boundary_at_30_is_good_not_excellent():
    result = score_gearing(30.0)
    assert result == ("good", 85, False, False)


def test_gearing_good():
    assert score_gearing(35.0) == ("good", 85, False, False)


def test_gearing_approaching_limit():
    assert score_gearing(42.0) == ("approaching_limit", 60, False, False)


def test_gearing_fail_above_45():
    result = score_gearing(50.0)
    assert result == ("fail", 0, True, False)


def test_gearing_boundary_at_45_is_approaching_limit_not_fail():
    result = score_gearing(45.0)
    assert result == ("approaching_limit", 60, False, False)


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


def test_current_ratio_borderline_without_deferred_revenue_still_fails():
    # Mirrors AZO's real shape: Borderline (0.89), no deferred revenue.
    result = score_step5_standard(
        current_ratio=0.89, adjusted_current_ratio=0.89, debt_to_ebitda=2.11, debt_servicing_pct=15.4,
        interest_coverage_ratio=7.63,
    )
    assert result["hard_fail"] is True
    assert result["pass_with_caution"] is False
    assert result["verdict"] == "Fail"


def test_both_debt_to_ebitda_and_dsr_borderline_share_one_icr_signal():
    # If both are Borderline at once, ICR is one shared confidence check --
    # a safe ICR saves both simultaneously, not independently.
    result = score_step5_standard(
        current_ratio=1.2, adjusted_current_ratio=1.2, debt_to_ebitda=3.5, debt_servicing_pct=35.0,
        interest_coverage_ratio=5.0,
    )
    assert result["ratios"]["debt_to_ebitda"]["saved_by_tiebreaker"] is True
    assert result["ratios"]["debt_servicing_ratio"]["saved_by_tiebreaker"] is True
    assert result["hard_fail"] is False
    assert result["verdict"] == "Pass with caution"


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
