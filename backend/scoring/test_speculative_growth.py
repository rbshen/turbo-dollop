import pytest

from scoring.speculative_growth import (
    GROWTH_GATE_MIN_PCT,
    cash_runway_years,
    cfo_recent_direction,
    evaluate_speculative_growth,
    is_not_durably_profitable,
    is_potential_fake_growth,
    psg_ratio,
    trailing_revenue_growth_pct,
)

# Majority-negative (6/11) -- clears is_not_durably_profitable, used by the
# gate-composition tests below to isolate the moat/growth conditions from
# the profitability gate.
UNPROFITABLE_NI_SERIES = [-1.0, -2.0, -3.0, 4.0, 5.0, -6.0]
# Majority-positive (10/11, mirrors TRMB) -- fails is_not_durably_profitable.
DURABLY_PROFITABLE_NI_SERIES = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, -1.0]


# --- evaluate_speculative_growth: gate composition ---------------------------


def test_qualifies_when_standard_moat_growth_and_profitability_all_pass():
    result = evaluate_speculative_growth("Standard", "narrow_moat", GROWTH_GATE_MIN_PCT + 1, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is True
    assert result.not_applicable_reason is None


def test_wide_moat_also_qualifies():
    result = evaluate_speculative_growth("Standard", "wide_moat", GROWTH_GATE_MIN_PCT + 10, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is True


def test_confirmed_no_moat_qualifies_with_strong_growth():
    # Added 2026-09-08, following the no_moat-gate investigation: a
    # *confirmed* no_moat rating (a real TickerMoat row) now passes the
    # moat gate, distinct from an unset rating (see test_unset_moat_excludes
    # below, unchanged). See scoring/speculative_growth.py::_MOAT_QUALIFYING.
    result = evaluate_speculative_growth("Standard", "no_moat", GROWTH_GATE_MIN_PCT + 50, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is True
    assert result.not_applicable_reason is None


def test_unset_moat_excludes():
    result = evaluate_speculative_growth("Standard", None, GROWTH_GATE_MIN_PCT + 50, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is False
    assert result.not_applicable_reason is None


def test_growth_at_exactly_the_boundary_does_not_qualify():
    # Half-open like every other tier boundary in this codebase -- exactly
    # at MAGNITUDE_HIGH doesn't clear ">".
    result = evaluate_speculative_growth("Standard", "narrow_moat", GROWTH_GATE_MIN_PCT, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is False


def test_growth_below_boundary_excludes():
    result = evaluate_speculative_growth("Standard", "narrow_moat", 5.0, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is False
    assert result.not_applicable_reason is None


def test_none_growth_rate_excludes():
    result = evaluate_speculative_growth("Standard", "narrow_moat", None, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is False


def test_durably_profitable_ni_excludes_even_with_moat_and_growth_passing():
    # The false-positive case this gate was added for: a mature,
    # thoroughly-profitable Standard/moat/high-growth ticker (e.g. MSFT)
    # must not qualify just because profitability was previously
    # informational-only.
    result = evaluate_speculative_growth(
        "Standard", "wide_moat", GROWTH_GATE_MIN_PCT + 10, DURABLY_PROFITABLE_NI_SERIES
    )
    assert result.qualifies is False
    assert result.not_applicable_reason is None


def test_missing_ni_series_excludes():
    result = evaluate_speculative_growth("Standard", "wide_moat", GROWTH_GATE_MIN_PCT + 10, None)
    assert result.qualifies is False


def test_non_standard_company_type_is_not_applicable_regardless_of_moat_or_growth():
    result = evaluate_speculative_growth("Bank", "wide_moat", 999.0, UNPROFITABLE_NI_SERIES)
    assert result.qualifies is False
    assert result.not_applicable_reason is not None
    assert "Bank" in result.not_applicable_reason


def test_reit_company_type_is_not_applicable():
    result = evaluate_speculative_growth("REIT/Property Developer", None, None)
    assert result.qualifies is False
    assert result.not_applicable_reason is not None


# --- is_not_durably_profitable ------------------------------------------------


def test_majority_negative_periods_passes():
    assert is_not_durably_profitable([-1.0, -2.0, -3.0, 4.0, 5.0, -6.0]) is True  # 4/6 negative


def test_majority_positive_periods_fails():
    # Mirrors TRMB: 10/11 profitable years, one bad TTM -- a mature company
    # having a rough year, not a "not yet profitable" story.
    assert is_not_durably_profitable([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, -1.0]) is False


def test_exactly_half_negative_is_not_a_majority():
    assert is_not_durably_profitable([-1.0, -2.0, 3.0, 4.0]) is False  # 2/4, tie doesn't clear ">"


def test_all_periods_negative_passes():
    assert is_not_durably_profitable([-1.0, -2.0, -3.0]) is True


def test_none_values_in_series_are_excluded_from_the_count():
    # 2 real values, both negative -- None entries aren't counted either way.
    assert is_not_durably_profitable([None, -1.0, -2.0, None]) is True


def test_empty_series_fails_closed():
    assert is_not_durably_profitable([]) is False


def test_none_series_fails_closed():
    assert is_not_durably_profitable(None) is False


def test_series_of_only_none_fails_closed():
    assert is_not_durably_profitable([None, None]) is False


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


# --- is_potential_fake_growth ---------------------------------------------------
# Revenue series are chronological (oldest -> newest annual, TTM last),
# matching Step1Out.revenue's real shape.

# MRNA-shaped: peaked at 1000 five years back, has since collapsed to 130
# (last FY) with only a small TTM uptick to 140 -- current revenue is 86%
# below its own trailing-5yr peak.
DEPRESSED_BASE_REVENUE = [1000.0, 200.0, 150.0, 140.0, 130.0, 140.0]
# BE/CRWV/IREN/SNOW/SYM-shaped: revenue only ever grows, TTM is itself the peak.
GROWING_REVENUE = [100.0, 200.0, 400.0, 600.0, 800.0, 1000.0]


def test_fake_growth_flagged_for_depressed_base_recovery():
    # forward 34.4% clears the growth gate; trailing (140/130-1)*100=7.7% is
    # under half of that -- the confirmed MRNA shape.
    assert is_potential_fake_growth(DEPRESSED_BASE_REVENUE, 34.4, 7.7) is True


def test_fake_growth_not_flagged_when_revenue_never_declined():
    # SNOW-shaped: condition (b) alone (trailing far under half of forward)
    # is true here, but condition (a) is false -- revenue never dipped, so
    # this isn't a depressed-base recovery, just decelerating growth.
    assert is_potential_fake_growth(GROWING_REVENUE, 32.5, 7.4) is False


def test_fake_growth_not_flagged_when_growth_gate_not_cleared():
    # Condition (a) alone (a real decline) isn't enough -- the ticker must
    # also actually clear the growth gate on the forward figure.
    assert is_potential_fake_growth(DEPRESSED_BASE_REVENUE, 10.0, 5.0) is False


def test_fake_growth_not_flagged_when_trailing_growth_is_close_to_forward():
    # A real decline, but trailing growth is NOT meaningfully lower than
    # forward (>= half) -- e.g. a genuine, currently-accelerating recovery.
    assert is_potential_fake_growth(DEPRESSED_BASE_REVENUE, 20.0, 15.0) is False


def test_fake_growth_boundary_exactly_30pct_decline_does_not_trigger():
    # "More than 30% below" is strict -- exactly at the boundary must not
    # trigger. Peak 1000, current exactly 700 (30.0% decline).
    revenue = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 700.0]
    assert is_potential_fake_growth(revenue, 34.4, 7.7) is False


def test_fake_growth_boundary_just_past_30pct_decline_triggers():
    # Same shape, current just below 700 (30.1% decline).
    revenue = [1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 699.0]
    assert is_potential_fake_growth(revenue, 34.4, 7.7) is True


def test_fake_growth_degrades_gracefully_with_thin_history():
    # CRWV-shaped: only 3 annual years + TTM (fewer than the 5-period
    # lookback window) -- uses whatever's available rather than erroring.
    revenue = [15.0, 228.0, 1915.0, 5131.0]  # 3 annual years + TTM
    # TTM (5131) is itself the peak -- no decline, so this must not trigger
    # regardless of how the forward/trailing growth figures compare.
    assert is_potential_fake_growth(revenue, 58.4, 10.0) is False


def test_fake_growth_none_when_revenue_series_missing():
    assert is_potential_fake_growth(None, 34.4, 7.7) is False
    assert is_potential_fake_growth([], 34.4, 7.7) is False


def test_fake_growth_none_when_forward_growth_missing():
    assert is_potential_fake_growth(DEPRESSED_BASE_REVENUE, None, 7.7) is False


def test_fake_growth_none_when_trailing_growth_missing():
    assert is_potential_fake_growth(DEPRESSED_BASE_REVENUE, 34.4, None) is False


def test_fake_growth_falls_back_to_latest_annual_when_ttm_is_none():
    # TTM missing (e.g. a fetch gap) -- falls back to the latest annual
    # figure as "current revenue" rather than treating it as unknown.
    revenue = [1000.0, 200.0, 150.0, 140.0, 130.0, None]
    assert is_potential_fake_growth(revenue, 34.4, 7.7) is True
