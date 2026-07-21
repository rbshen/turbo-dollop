from scoring.step4 import (
    classify_ccc_trend,
    score_revenue_vs_ar,
    score_roe,
    score_roic,
    score_step4,
)
from scoring.trend import TrendResult

POSITIVE_EQUITY = [100.0] * 6

# --- ROE tiers ---


def test_roe_excellent_above_15_with_consistent_min_year():
    result = score_roe([20.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("excellent", 100, False)


def test_roe_good_12_to_15():
    result = score_roe([13.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("good", 85, False)


def test_roe_good_boundary_at_15_is_good_not_excellent():
    result = score_roe([15.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("good", 85, False)


def test_roe_marginal_8_to_12():
    result = score_roe([10.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("marginal", 60, False)


def test_roe_marginal_when_high_average_but_inconsistent_min_year():
    # avg well above 15%, but one very weak year (min < 8%) -- inconsistent,
    # so it doesn't get the "excellent" tier despite the high average.
    result = score_roe([30.0, 30.0, 30.0, 30.0, 30.0, 5.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("marginal", 60, False)


def test_roe_fail_below_8_is_hard_fail():
    result = score_roe([5.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("fail", 0, True)


# --- Negative equity exception ---


def test_negative_equity_with_positive_growing_income_scores_100():
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    # Raw ROE values are ignored entirely once equity goes negative anywhere.
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("positive_despite_negative_equity", 100, False)


def test_negative_equity_with_a_loss_year_scores_60_not_a_fail():
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [10.0, -5.0, 10.0, 10.0, 10.0, 10.0]
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("negative_equity_inconsistent_income", 60, False)
    assert result.hard_fail is False


def test_negative_equity_with_declining_income_scores_60():
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [20.0, 18.0, 16.0, 14.0, 12.0, 10.0]  # positive but net declining
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("negative_equity_inconsistent_income", 60, False)


# --- ROIC uses the same tiering, independently ---


def test_roic_excellent():
    assert score_roic([20.0] * 6) == ("excellent", 100, False)


def test_roic_fail_is_hard_fail():
    assert score_roic([2.0] * 6) == ("fail", 0, True)


# --- Metric 3: Revenue vs Accounts Receivable ---


def _build(revenue_yoys: list[float], ar_yoys: list[float], revenue0: float = 100.0, ar0: float = 50.0):
    revenue = [revenue0]
    ar = [ar0]
    for ry, ay in zip(revenue_yoys, ar_yoys):
        revenue.append(revenue[-1] * (1 + ry / 100))
        ar.append(ar[-1] * (1 + ay / 100))
    return revenue, ar


def test_ar_zero_outpacing_years_scores_100():
    revenue, ar = _build([10, 10], [10, 10])
    assert score_revenue_vs_ar(revenue, ar) == ("healthy", 100, False)


def test_ar_one_isolated_small_gap_scores_100():
    revenue, ar = _build([10, 10], [10, 20])  # gap = 10pp on one of two transitions
    assert score_revenue_vs_ar(revenue, ar) == ("healthy", 100, False)


def test_ar_one_isolated_medium_gap_scores_70():
    revenue, ar = _build([10, 10], [10, 40])  # gap = 30pp (medium)
    assert score_revenue_vs_ar(revenue, ar) == ("outpacing_isolated", 70, False)


def test_ar_two_outpacing_years_not_majority_scores_70():
    revenue, ar = _build([10, 10, 10, 10], [10, 10, 40, 22])  # gaps: 0, 0, 30, 12
    assert score_revenue_vs_ar(revenue, ar) == ("outpacing_isolated", 70, False)


def test_ar_three_outpacing_years_scores_40():
    revenue, ar = _build([10] * 6, [10, 10, 10, 40, 22, 30])  # gaps: 0,0,0,30,12,20 -> 3 outpacing
    assert score_revenue_vs_ar(revenue, ar) == ("outpacing_concerning", 40, False)


def test_ar_single_large_gap_scores_40_even_if_isolated():
    revenue, ar = _build([10, 10], [10, 80])  # gap = 70pp (large), only 1 outpacing year
    assert score_revenue_vs_ar(revenue, ar) == ("outpacing_concerning", 40, False)


def test_ar_majority_outpacing_scores_0_even_with_small_gaps():
    revenue, ar = _build([10, 10, 10], [20, 20, 10])  # 2 of 3 transitions outpace, gaps small
    assert score_revenue_vs_ar(revenue, ar) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_strong_red_flag_revenue_declining_ar_growing_scores_0():
    revenue = [100.0, 90.0]
    ar = [50.0, 55.0]
    assert score_revenue_vs_ar(revenue, ar) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_insufficient_data_with_fewer_than_two_periods():
    assert score_revenue_vs_ar([100.0], [50.0]) == ("insufficient_data", 0, False)


# --- Metric 4: Cash Conversion Cycle trend (inverted margin classifier) ---


def test_ccc_declining_steadily_scores_100():
    result = classify_ccc_trend([50, 48, 46, 44, 42, 40])
    assert result == TrendResult("declining_or_stable", 100)


def test_ccc_volatile_but_net_declining_scores_70():
    result = classify_ccc_trend([50, 55, 40, 35, 30, 25])
    assert result == TrendResult("volatile_but_net_declining", 70)


def test_ccc_volatile_no_clear_trend_scores_40():
    result = classify_ccc_trend([50, 60, 40, 60, 40, 50])
    assert result == TrendResult("volatile_no_trend", 40)


def test_ccc_sharp_sustained_rise_scores_0():
    result = classify_ccc_trend([30, 32, 38, 44, 50, 56])
    assert result == TrendResult("sustained_upward", 0)


def test_ccc_slow_net_worsening_still_scores_0():
    result = classify_ccc_trend([30, 30, 30, 30, 30, 40])
    assert result == TrendResult("sustained_upward", 0)


def test_ccc_insufficient_data():
    assert classify_ccc_trend([50.0]) == TrendResult("insufficient_data", 0)


def test_ccc_old_resolved_dip_does_not_override_a_strongly_positive_trend():
    # Mirrors MSFT's real shape: a small early rise (sustained_decline
    # fires on the 2016-2018 uptick), followed by a much larger decline
    # that leaves the overall direction strongly positive (improving).
    # Before the recency gate, sustained_decline alone forced 0
    # regardless of direction -- must not happen anymore.
    result = classify_ccc_trend([20, 26, 30, 15, 0, -15])
    assert result.pattern != "sustained_upward"
    assert result.score > 0
    assert result == TrendResult("volatile_but_net_declining", 70)


def test_ccc_recent_unresolved_decline_still_overrides_to_zero():
    # Regression guard: a genuinely still-worsening series (direction
    # stays clearly negative, matching ANET/FTNT's real shape) must keep
    # scoring 0 -- the recency gate must not soften real deterioration.
    result = classify_ccc_trend([30, 32, 38, 44, 50, 56])
    assert result == TrendResult("sustained_upward", 0)


def test_ccc_direction_exactly_at_the_stable_tolerance_boundary_does_not_override():
    # direction lands at (a hair above, due to float precision) exactly
    # CCC_STABLE_TOLERANCE_DAYS (-1.0) despite sustained_decline firing on
    # an early rise -- the gate uses a strict "<", so a direction that's
    # merely at the boundary (not clearly negative) does not re-trigger
    # the hard override; it falls through to the ordinary tiering instead.
    result = classify_ccc_trend([10, 16, 20, 21, 21, 7])
    assert result.pattern != "sustained_upward"


# --- score_step4: weight redistribution + hard-fail override ---


def _ratio(label, points, hard_fail=False):
    from scoring.step4 import RatioResult

    return RatioResult(label, points, hard_fail)


def test_all_four_metrics_equal_weight_25_percent_each():
    roe = _ratio("excellent", 100)
    ar = _ratio("healthy", 100)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["weight_per_metric"] == 0.25
    assert result["score"] == 100
    assert result["verdict"] == "Strong Pass"
    assert result["hard_fail"] is False


def test_roic_exempt_redistributes_to_remaining_three():
    roe = _ratio("good", 90)
    ar = _ratio("healthy", 90)
    result = score_step4(roe, ar, None, TrendResult("declining_or_stable", 90))
    assert abs(result["weight_per_metric"] - 1 / 3) < 1e-9
    assert result["score"] == 90
    assert result["verdict"] == "Pass"  # 90 is not > 90, so not Strong Pass


def test_roic_and_ccc_both_exempt_redistributes_to_remaining_two():
    roe = _ratio("good", 90)
    ar = _ratio("healthy", 90)
    result = score_step4(roe, ar, None, None)
    assert result["weight_per_metric"] == 0.5
    assert result["score"] == 90


def test_hard_fail_from_roe_overrides_verdict_despite_good_score():
    roe = _ratio("fail", 0, hard_fail=True)
    ar = _ratio("healthy", 100)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["score"] == 75  # (0 + 100 + 100 + 100) / 4
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_hard_fail_from_roic_overrides_verdict():
    roe = _ratio("excellent", 100)
    ar = _ratio("healthy", 100)
    roic = _ratio("fail", 0, hard_fail=True)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_ar_or_ccc_landing_in_their_own_zero_tier_does_not_hard_fail():
    roe = _ratio("excellent", 100)
    ar = _ratio("outpacing_majority_or_red_flag", 0)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("sustained_upward", 0)
    result = score_step4(roe, ar, roic, ccc)
    assert result["score"] == 50  # (100 + 0 + 100 + 0) / 4
    assert result["hard_fail"] is False
    assert result["verdict"] == "Pass"
