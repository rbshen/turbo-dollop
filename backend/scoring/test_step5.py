from scoring.step5 import (
    classify_company_type,
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


# --- Current Ratio tiers ---


def test_current_ratio_excellent_above_2():
    result = score_current_ratio(2.5)
    assert result == ("excellent", 100, False)


def test_current_ratio_good_boundary_at_2_is_good_not_excellent():
    result = score_current_ratio(2.0)
    assert result == ("good", 85, False)


def test_current_ratio_good_boundary_at_1_5_is_good_not_acceptable():
    result = score_current_ratio(1.5)
    assert result == ("good", 85, False)


def test_current_ratio_fail_below_1():
    result = score_current_ratio(0.9)
    assert result == ("fail", 0, True)


def test_current_ratio_boundary_at_1_is_acceptable_not_fail():
    result = score_current_ratio(1.0)
    assert result == ("acceptable", 70, False)


# --- Debt/EBITDA tiers ---


def test_debt_to_ebitda_excellent_at_or_below_1():
    assert score_debt_to_ebitda(1.0) == ("excellent", 100, False)


def test_debt_to_ebitda_good():
    assert score_debt_to_ebitda(1.5) == ("good", 85, False)


def test_debt_to_ebitda_acceptable_boundary_at_2():
    assert score_debt_to_ebitda(2.0) == ("good", 85, False)
    assert score_debt_to_ebitda(2.5) == ("acceptable", 70, False)


def test_debt_to_ebitda_fail_above_3():
    result = score_debt_to_ebitda(3.1)
    assert result == ("fail", 0, True)


def test_debt_to_ebitda_boundary_at_3_is_acceptable_not_fail():
    result = score_debt_to_ebitda(3.0)
    assert result == ("acceptable", 70, False)


# --- Debt Servicing Ratio tiers ---


def test_debt_servicing_excellent_below_10():
    assert score_debt_servicing(5.0) == ("excellent", 100, False)


def test_debt_servicing_good():
    assert score_debt_servicing(15.0) == ("good", 85, False)


def test_debt_servicing_approaching_limit():
    assert score_debt_servicing(25.0) == ("approaching_limit", 60, False)


def test_debt_servicing_fail_at_or_above_30():
    result = score_debt_servicing(30.0)
    assert result == ("fail", 0, True)


# --- NPL Ratio tiers (Bank, partial signal only) ---


def test_npl_excellent_below_1():
    assert score_npl(0.5) == ("excellent", 100, False)


def test_npl_good():
    assert score_npl(2.0) == ("good", 85, False)


def test_npl_boundary_at_1_is_good_not_excellent():
    assert score_npl(1.0) == ("good", 85, False)


def test_npl_acceptable():
    assert score_npl(4.0) == ("acceptable", 70, False)


def test_npl_boundary_at_3_is_acceptable_not_good():
    assert score_npl(3.0) == ("acceptable", 70, False)


def test_npl_fail_at_or_above_5():
    assert score_npl(5.0) == ("fail", 0, True)
    assert score_npl(7.5) == ("fail", 0, True)


# --- Gearing Ratio tiers (REIT) ---


def test_gearing_excellent_below_30():
    assert score_gearing(25.0) == ("excellent", 100, False)


def test_gearing_good_boundary_at_30_is_good_not_excellent():
    result = score_gearing(30.0)
    assert result == ("good", 85, False)


def test_gearing_good():
    assert score_gearing(35.0) == ("good", 85, False)


def test_gearing_approaching_limit():
    assert score_gearing(42.0) == ("approaching_limit", 60, False)


def test_gearing_fail_above_45():
    result = score_gearing(50.0)
    assert result == ("fail", 0, True)


def test_gearing_boundary_at_45_is_approaching_limit_not_fail():
    result = score_gearing(45.0)
    assert result == ("approaching_limit", 60, False)


# --- Hard-fail override (the core Step 5 fix, mirroring Step 2's) ---


def test_hard_fail_overrides_score_even_with_two_excellent_ratios():
    # Current Ratio and Debt/EBITDA are excellent, but Debt Servicing Ratio
    # breaches its hard limit (>=30%) -- verdict must be Fail even though
    # the blended score alone would land well into Pass territory.
    result = score_step5_standard(current_ratio=3.0, debt_to_ebitda=0.5, debt_servicing_pct=35.0)
    # (100 + 100 + 0) / 3 = 66.67 -> 67, which is NOT a Fail-range score
    # under the shared badge tiers -- only the hard_fail flag makes it Fail.
    assert result["score"] == 67
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_no_hard_fail_one_approaching_limit_still_passes():
    # 2 excellent/good ratios + 1 "approaching limit" (not a hard breach) --
    # matches the doc's own "2 green, 1 yellow -> Pass, monitor" framework.
    result = score_step5_standard(current_ratio=2.5, debt_to_ebitda=0.8, debt_servicing_pct=25.0)
    assert result["hard_fail"] is False
    assert result["verdict"] == "Pass"


def test_all_excellent_is_strong_pass():
    result = score_step5_standard(current_ratio=3.0, debt_to_ebitda=0.5, debt_servicing_pct=5.0)
    assert result["score"] == 100
    assert result["hard_fail"] is False
    assert result["verdict"] == "Strong Pass"


# --- REIT path ---


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
