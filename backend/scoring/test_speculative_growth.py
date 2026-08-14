import pytest

from scoring.speculative_growth import (
    GROWTH_GATE_MIN_PCT,
    cash_runway_years,
    cfo_recent_direction,
    evaluate_speculative_growth,
    psg_ratio,
    trailing_revenue_growth_pct,
)


# --- evaluate_speculative_growth: gate composition ---------------------------


def test_qualifies_when_standard_moat_and_growth_all_pass():
    result = evaluate_speculative_growth("Standard", "narrow_moat", GROWTH_GATE_MIN_PCT + 1)
    assert result.qualifies is True
    assert result.not_applicable_reason is None


def test_wide_moat_also_qualifies():
    result = evaluate_speculative_growth("Standard", "wide_moat", GROWTH_GATE_MIN_PCT + 10)
    assert result.qualifies is True


def test_no_moat_excludes_even_with_strong_growth():
    result = evaluate_speculative_growth("Standard", "no_moat", GROWTH_GATE_MIN_PCT + 50)
    assert result.qualifies is False
    assert result.not_applicable_reason is None  # in-scope, just didn't clear the moat gate


def test_unset_moat_excludes():
    result = evaluate_speculative_growth("Standard", None, GROWTH_GATE_MIN_PCT + 50)
    assert result.qualifies is False
    assert result.not_applicable_reason is None


def test_growth_at_exactly_the_boundary_does_not_qualify():
    # Half-open like every other tier boundary in this codebase -- exactly
    # at MAGNITUDE_HIGH doesn't clear ">".
    result = evaluate_speculative_growth("Standard", "narrow_moat", GROWTH_GATE_MIN_PCT)
    assert result.qualifies is False


def test_growth_below_boundary_excludes():
    result = evaluate_speculative_growth("Standard", "narrow_moat", 5.0)
    assert result.qualifies is False
    assert result.not_applicable_reason is None


def test_none_growth_rate_excludes():
    result = evaluate_speculative_growth("Standard", "narrow_moat", None)
    assert result.qualifies is False


def test_non_standard_company_type_is_not_applicable_regardless_of_moat_or_growth():
    result = evaluate_speculative_growth("Bank", "wide_moat", 999.0)
    assert result.qualifies is False
    assert result.not_applicable_reason is not None
    assert "Bank" in result.not_applicable_reason


def test_reit_company_type_is_not_applicable():
    result = evaluate_speculative_growth("REIT/Property Developer", None, None)
    assert result.qualifies is False
    assert result.not_applicable_reason is not None


# --- cfo_recent_direction -----------------------------------------------------


def test_cfo_direction_latest_positive_is_turning_positive_even_if_prior_was_too():
    assert cfo_recent_direction(latest_quarter_cfo=10.0, prior_quarter_cfo=5.0) == "turning_positive"


def test_cfo_direction_latest_positive_prior_negative_is_turning_positive():
    assert cfo_recent_direction(latest_quarter_cfo=1.0, prior_quarter_cfo=-50.0) == "turning_positive"


def test_cfo_direction_both_negative_improving():
    assert cfo_recent_direction(latest_quarter_cfo=-10.0, prior_quarter_cfo=-30.0) == "improving"


def test_cfo_direction_both_negative_worsening():
    assert cfo_recent_direction(latest_quarter_cfo=-30.0, prior_quarter_cfo=-10.0) == "worsening"


def test_cfo_direction_latest_negative_prior_positive_is_mixed():
    assert cfo_recent_direction(latest_quarter_cfo=-5.0, prior_quarter_cfo=20.0) == "mixed"


def test_cfo_direction_none_when_either_quarter_missing():
    assert cfo_recent_direction(None, -10.0) is None
    assert cfo_recent_direction(-10.0, None) is None
    assert cfo_recent_direction(None, None) is None


# --- cash_runway_years ---------------------------------------------------------


def test_cash_runway_computes_when_burning():
    assert cash_runway_years(cash_and_st_investments=850.0, cfo_ttm=-85.0) == 10.0


def test_cash_runway_none_when_cfo_positive():
    assert cash_runway_years(cash_and_st_investments=850.0, cfo_ttm=50.0) is None


def test_cash_runway_none_when_cfo_exactly_zero():
    # Not burning cash -- "runway" isn't a meaningful concept.
    assert cash_runway_years(cash_and_st_investments=850.0, cfo_ttm=0.0) is None


def test_cash_runway_none_when_cash_missing():
    assert cash_runway_years(cash_and_st_investments=None, cfo_ttm=-85.0) is None


def test_cash_runway_none_when_cfo_missing():
    assert cash_runway_years(cash_and_st_investments=850.0, cfo_ttm=None) is None


# --- psg_ratio -----------------------------------------------------------------


def test_psg_ratio_basic():
    assert psg_ratio(price_to_sales_ttm=5.0, trailing_growth_pct=60.0) == pytest.approx(5.0 / 60.0)


def test_psg_ratio_none_when_price_to_sales_missing():
    assert psg_ratio(None, 60.0) is None


def test_psg_ratio_none_when_growth_missing():
    assert psg_ratio(5.0, None) is None


def test_psg_ratio_none_when_growth_zero():
    assert psg_ratio(5.0, 0.0) is None


def test_psg_ratio_none_when_growth_negative():
    assert psg_ratio(5.0, -10.0) is None


# --- trailing_revenue_growth_pct -----------------------------------------------


def test_trailing_revenue_growth_basic():
    assert trailing_revenue_growth_pct(ttm_revenue=160.0, last_fy_revenue=100.0) == pytest.approx(60.0)


def test_trailing_revenue_growth_none_when_ttm_missing():
    assert trailing_revenue_growth_pct(None, 100.0) is None


def test_trailing_revenue_growth_none_when_base_missing():
    assert trailing_revenue_growth_pct(160.0, None) is None


def test_trailing_revenue_growth_none_when_base_non_positive():
    assert trailing_revenue_growth_pct(160.0, 0.0) is None
    assert trailing_revenue_growth_pct(160.0, -50.0) is None
