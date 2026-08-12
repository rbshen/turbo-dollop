import pytest

from scoring.step3 import (
    NEGATIVE_VALUE_RECENCY_YEARS,
    _positive_and_increasing,
    _revenue_growing_aggressively,
    bands_from_mean_sd,
    dividend_yield_meets_reit_threshold,
    dpu_growth_note,
    historical_pb_buy_signal,
    loss_making_pb_reference_note,
    pb_benchmark_for,
    run_20yr_engine,
    run_price_to_book,
    select_method,
    trailing_smoothed_average,
)

# --- 20yr engine: MSFT DFCF worked example -------------------------------
# Every input and expected output below is read directly from the source
# workbook (PP VMI Investing Tools - 2026 - v1_1.xlsx, sheet
# "VMI IV Calculator (20 years)"), not invented -- this is the exact
# "cross-checked cell-for-cell" worked example run_20yr_engine's own
# docstring already claims to match.


def test_run_20yr_engine_matches_msft_dfcf_worked_example():
    # Inputs: C8/F8="Microsoft", C10/F10="MSFT", C12/F12="Discounted Free
    # Cash Flow", G14 (current_value), G16 (total_debt), G18
    # (cash_and_st_investments), F20/F22/F24 (growth yr 1-5/6-10/11-20),
    # F26 (shares_outstanding), E28 (discount_rate), N30 (last_close).
    result = run_20yr_engine(
        current_value=101_030.39999999999,
        growth_yr_1_5=0.17480000000000001,
        growth_yr_6_10=0.15,
        growth_yr_11_20=0.04,
        discount_rate=0.066100000000000006,
        shares_outstanding=7466,
        total_debt=43208,
        cash_and_st_investments=102012,
        fx_rate=1.0,
        last_close=405.76,
    )

    # N14 "PV of 20 yr Free Cash Flow"
    assert result.pv_sum == pytest.approx(3_815_917.1602785662)
    # N24 "Intrinsic Value Per Share (In Financial Statement Currency)" --
    # N16 (511.106, pre debt/cash adj) - N18 (5.787 debt/share) + N20
    # (13.664 cash/share) = N24, all cross-checked against the workbook's
    # own cells during this test's construction.
    assert result.intrinsic_value_per_share == pytest.approx(518.98220737725239)
    # M28 "(Discount)/Premium" = last_close / iv_per_share - 1
    assert result.discount_premium_pct == pytest.approx(-0.21816202129440299)


# --- Regression: P/B minus-side bands must NOT reproduce the workbook's --
# --- own mislabeled SD columns -------------------------------------------
# JPM worked example, "VMI IV Calculator (Mean PB)" sheet. G12=100
# (book_value_per_share), F17:O17 (10 historical PB ratios, chronological),
# F14="5 years" (lookback -> last 5 of the 10), J28=242.28 (last_close).
JPM_HISTORICAL_PB = [1.11, 1.35, 1.6, 1.4, 1.85, 1.61, 1.83, 1.54, 1.7, 2.08]


def test_bands_from_mean_sd_matches_jpm_worked_example_not_workbooks_mislabeled_columns():
    result = run_price_to_book(
        book_value_per_share=100,
        historical_pb_ratios=JPM_HISTORICAL_PB,
        lookback="5 years",
        fx_rate=1.0,
        last_close=242.28,
    )

    # F19/J19/J22 -- mean of the last 5 ratios (1.61, 1.83, 1.54, 1.7, 2.08)
    assert result.mean_pb == pytest.approx(1.7520000000000002)
    # M19 -- sample stdev (ddof=1) of the same 5 values
    assert result.sd_pb == pytest.approx(0.21300234740490151, rel=1e-4)

    # The workbook's OWN column labeled "Mean - 1 SD" (F21/F22/F23) actually
    # holds 132.599... = mean - 2*SD, and the column labeled "Mean - 2 SD"
    # (H21/H22/H23) actually holds 153.899... = mean - 1*SD -- a labeling
    # bug in the source spreadsheet itself (see bands_from_mean_sd's own
    # docstring). This test pins the CORRECT, un-swapped values -- if a
    # future change accidentally matched the workbook's own mislabeled
    # order instead of the literal mean-N*SD formula, this would fail.
    assert result.bands["minus_1sd"] == pytest.approx(153.89976525950988, rel=1e-4)  # mean - 1*SD
    assert result.bands["minus_2sd"] == pytest.approx(132.59953051901971, rel=1e-4)  # mean - 2*SD
    assert result.bands["mean"] == pytest.approx(175.20000000000002)
    assert result.bands["plus_1sd"] == pytest.approx(196.50023474049017, rel=1e-4)
    assert result.bands["plus_2sd"] == pytest.approx(217.8004694809803, rel=1e-4)

    # J30 "(Discount)/Premium" -- JPM traded above this method's fair value.
    assert result.discount_premium_pct == pytest.approx(0.38287671232876708, rel=1e-4)


# --- Regression: RIVN-style zero-revenue years must not poison the CAGR --
# --- base for the PSG "revenue growing aggressively" check ---------------
# Mirrors _revenue_growing_aggressively's own docstring: "$0 revenue in its
# earliest two reported years, then $55M -> $5.4B" -- a naive CAGR from
# index 0 would either divide by zero or misread the company as "revenue
# not positive across the window."
RIVN_STYLE_REVENUE = [0, 0, 55_000_000, 220_000_000, 1_100_000_000, 3_130_000_000, 5_400_000_000]


def test_revenue_growing_aggressively_uses_first_positive_year_not_index_zero_as_cagr_base():
    passed, detail = _revenue_growing_aggressively(RIVN_STYLE_REVENUE)

    assert passed is True
    # CAGR from the first positive year ($55M, index 2) to TTM ($5.4B),
    # over 4 years (index 2 -> index 6) -- NOT from index 0, which is $0.
    expected_cagr = (5_400_000_000 / 55_000_000) ** (1 / 4) - 1
    assert expected_cagr == pytest.approx(2.1478046137168754)
    assert "214.8%" in detail
    assert "4y" in detail


def test_revenue_growing_aggressively_control_case_all_positive_from_index_zero():
    # A company with no zero-revenue poisoning at all -- the base is simply
    # index 0, same answer either way. Confirms the fix didn't change
    # behavior for the common case.
    ordinary = [100, 130, 170, 220, 290, 380]
    passed, detail = _revenue_growing_aggressively(ordinary)
    assert passed is True
    # base=100 (index 0), current=380 (TTM), over 5 years.
    expected_cagr = (380 / 100) ** (1 / 5) - 1
    assert expected_cagr == pytest.approx(0.3060407249698005)
    assert "30.6%" in detail


# --- select_method: AMZN-style recency-boundary (NEGATIVE_VALUE_RECENCY) -
# Pins the exact off-by-one behavior described in _positive_and_increasing's
# own docstring (AMZN's 2022 Rivian-writedown net loss): a non-positive
# value exactly NEGATIVE_VALUE_RECENCY_YEARS (3) periods before the most
# recent one still disqualifies outright, regardless of any recovery since;
# one period older than that falls through to classify_trend instead.


def test_positive_and_increasing_recency_boundary_still_fails_at_exactly_3_years():
    assert NEGATIVE_VALUE_RECENCY_YEARS == 3
    # Negative value at index 4 of 8 (years_since_negative = 7 - 4 = 3).
    values = [100, 110, 121, 133, -50, 146, 160, 176]
    passed, detail = _positive_and_increasing(values)
    assert passed is False
    assert "non-positive value within the last 3 years" in detail


def test_positive_and_increasing_recency_boundary_passes_at_4_years_via_recovery():
    # Same shape, negative value one period older (index 3 of 8,
    # years_since_negative = 7 - 3 = 4) -- old enough to fall through to
    # classify_trend, which reads the durable recovery since as a real
    # "significant_dip_recovers" pattern.
    values = [100, 110, 121, -50, 133, 146, 160, 176]
    passed, detail = _positive_and_increasing(values)
    assert passed is True
    assert "significant_dip_recovers" in detail


def test_select_method_amzn_style_recency_boundary_changes_the_selected_method():
    # Same two CFO shapes as above, run through the full tree. Net Income is
    # positive and comfortably below 1.5x CFO, so *if* the CFO check
    # qualifies, step 3's ratio check cleanly fails and DCF is selected --
    # isolating the CFO recency boundary as the only variable that decides
    # whether DCF is even reachable at all (when CFO is disqualified, step 2
    # itself blocks entry to step 3 entirely, so DCF can never be reached
    # regardless of how NI/Revenue read).
    real_ni = [90, 95, 100, 105, 110, 120]  # 1.5x120=180 > cfo_ttm=176 -- ratio check fails cleanly
    flat_revenue = [500, 490, 480, 470, 460, 450]

    still_disqualified = [100, 110, 121, 133, -50, 146, 160, 176]
    result_fail = select_method(
        company_type="Standard",
        cfo_series=still_disqualified,
        cfo_ttm=176,
        net_income_series=real_ni,
        net_income_ttm=120,
        fcf_series=None,
        capex_series=None,
        revenue_series=flat_revenue,
    )
    cfo_step_fail = next(s for s in result_fail.decision_trail if s.step == "2")
    assert cfo_step_fail.passed is False
    assert "3" not in {s.step for s in result_fail.decision_trail}  # never reached
    assert result_fail.method != "DCF"

    now_recovered = [100, 110, 121, -50, 133, 146, 160, 176]
    result_pass = select_method(
        company_type="Standard",
        cfo_series=now_recovered,
        cfo_ttm=176,
        net_income_series=real_ni,
        net_income_ttm=120,
        fcf_series=None,
        capex_series=None,
        revenue_series=flat_revenue,
    )
    cfo_step_pass = next(s for s in result_pass.decision_trail if s.step == "2")
    step3_pass = next(s for s in result_pass.decision_trail if s.step == "3")
    assert cfo_step_pass.passed is True
    assert step3_pass.passed is False  # CFO=176 vs 1.5x NI=180 -- fails cleanly
    assert result_pass.method == "DCF"
    assert result_pass.current_value_source == "cfo_ttm"


# --- select_method: full decision-tree branch coverage -------------------
# One test per terminal branch/node named in valuation.md's §1 decision
# tree. Genuine
# PASS (insufficient_data=False) and both insufficient_data=True paths
# (total/partial fetch failure) are already covered in
# tests/test_step3_data.py from the recent Step 3 fix -- not duplicated
# here.


def test_select_method_bank_reit_uses_price_to_book():
    # Step 1 YES branch -- short-circuits immediately, no other data needed.
    result = select_method(
        company_type="Bank",
        cfo_series=None,
        cfo_ttm=None,
        net_income_series=None,
        net_income_ttm=None,
        fcf_series=None,
        capex_series=None,
        revenue_series=None,
    )
    assert result.method == "PRICE_TO_BOOK"
    assert result.current_value_source is None
    assert len(result.decision_trail) == 1
    assert result.decision_trail[0].step == "1"
    assert result.decision_trail[0].passed is True
    assert result.decision_trail[0].detail == "company_type=Bank"


def test_select_method_insurance_skips_cfo_family_even_with_strong_cfo_data():
    # PGR-shaped repro: even when CFO data would otherwise clearly qualify
    # for DCF/DFCF (positive, increasing, > 1.5x NI, FCF positive and
    # consistent), Insurance must never land on a CFO-based method --
    # confirmed as a real regression via investigation (PGR landed on plain
    # DCF before this fix, contradicting the framework's own rationale that
    # insurer OCF is unreliable). Net Income here also increases every year,
    # so this should land on DNI via step 4, having skipped 2/3/3a/3b
    # entirely.
    cfo = [100, 110, 121, 133, 146, 160]
    ni = [50, 60, 70, 80, 90, 100]
    fcf = [c * 0.7 for c in cfo]
    capex = [-c * 0.3 for c in cfo]
    result = select_method(
        company_type="Insurance",
        cfo_series=cfo,
        cfo_ttm=160,
        net_income_series=ni,
        net_income_ttm=100,
        fcf_series=fcf,
        capex_series=capex,
        revenue_series=[500, 520, 540, 560, 580, 600],
    )
    assert result.method == "DNI"
    assert result.current_value_source == "net_income_ttm"
    steps_by_id = {s.step: s for s in result.decision_trail}
    assert "2" not in steps_by_id
    assert "3" not in steps_by_id
    assert "3a" not in steps_by_id
    assert "3b" not in steps_by_id
    assert steps_by_id["1a"].passed is True
    assert steps_by_id["4"].passed is True


def test_select_method_insurance_falls_back_to_dni_normalized_when_ni_inconsistent():
    # MET-shaped: choppy Net Income (not a clean uptrend) but profitable now
    # and smoothed-positive -- lands on DNI_NORMALIZED via the same 4/4a/4a-1
    # fallback Standard companies use, having still skipped the CFO family.
    choppy_ni = [50, -10, 40, -5, 45, 30]
    result = select_method(
        company_type="Insurance",
        cfo_series=[100, 110, 90, 105, 95, 98],
        cfo_ttm=98,
        net_income_series=choppy_ni,
        net_income_ttm=30,
        fcf_series=None,
        capex_series=None,
        revenue_series=[100, 110, 90, 105, 95, 98],
    )
    assert result.method == "DNI_NORMALIZED"
    assert result.current_value_source == "net_income_smoothed"
    steps_by_id = {s.step: s for s in result.decision_trail}
    assert "2" not in steps_by_id


def test_select_method_insurance_can_still_fall_through_to_psg_or_pass():
    # An unprofitable insurer with genuinely weak Net Income still degrades
    # gracefully to PSG (if revenue is growing aggressively) or PASS --
    # Insurance is never forced onto a fabricated DNI value regardless of
    # data quality, same discipline the rest of this app already applies to
    # data gaps.
    result = select_method(
        company_type="Insurance",
        cfo_series=None,
        cfo_ttm=None,
        net_income_series=[-500, -400, -300, -200, -100, -50],
        net_income_ttm=-50,
        fcf_series=None,
        capex_series=None,
        revenue_series=[100, 100, 100, 100, 100, 100],
    )
    assert result.method == "PASS"
    steps_by_id = {s.step: s for s in result.decision_trail}
    assert "2" not in steps_by_id
    assert steps_by_id["1a"].passed is True


def test_select_method_dcf_when_cfo_not_1_5x_net_income():
    # Step 2 YES, step 3 NO -- CFO qualifies but isn't > 1.5x Net Income.
    cfo = [100, 110, 121, 133, 146, 160]
    ni = [90, 95, 100, 105, 110, 115]
    result = select_method(
        company_type="Standard",
        cfo_series=cfo,
        cfo_ttm=160,
        net_income_series=ni,
        net_income_ttm=115,
        fcf_series=None,
        capex_series=None,
        revenue_series=[500, 480, 460, 440, 420, 400],
    )
    assert result.method == "DCF"
    assert result.current_value_source == "cfo_ttm"
    step3 = next(s for s in result.decision_trail if s.step == "3")
    assert step3.passed is False


def test_select_method_dfcf_via_raw_fcf():
    # Step 2 YES, step 3 YES, step 3a YES -- raw FCF is positive/consistent.
    cfo = [100, 110, 121, 133, 146, 160]
    ni = [30, 32, 34, 36, 38, 40]
    fcf = [c * 0.7 for c in cfo]
    capex = [-c * 0.3 for c in cfo]
    result = select_method(
        company_type="Standard",
        cfo_series=cfo,
        cfo_ttm=160,
        net_income_series=ni,
        net_income_ttm=40,
        fcf_series=fcf,
        capex_series=capex,
        revenue_series=[500, 480, 460, 440, 420, 400],
    )
    assert result.method == "DFCF"
    assert result.current_value_source == "fcf_ttm"
    step3a = next(s for s in result.decision_trail if s.step == "3a")
    assert step3a.passed is True


def test_select_method_dfcf_via_normalized_fcf():
    # Step 3a NO (a recent CapEx spike drags raw FCF negative in the most
    # recent year), step 3b YES -- normalizing CapEx to its 5yr trailing
    # average smooths the spike out and rescues a positive/consistent read.
    cfo = [100, 105, 110, 115, 120, 125]
    capex = [-30, -30, -30, -30, -30, -140]
    ni = [30, 32, 34, 36, 38, 40]
    fcf = [c + x for c, x in zip(cfo, capex)]
    assert fcf[-1] < 0  # confirms the raw series genuinely fails 3a

    result = select_method(
        company_type="Standard",
        cfo_series=cfo,
        cfo_ttm=125,
        net_income_series=ni,
        net_income_ttm=40,
        fcf_series=fcf,
        capex_series=capex,
        revenue_series=[500, 480, 460, 440, 420, 400],
    )
    assert result.method == "DFCF"
    assert result.current_value_source == "fcf_normalized"
    step3a = next(s for s in result.decision_trail if s.step == "3a")
    step3b = next(s for s in result.decision_trail if s.step == "3b")
    assert step3a.passed is False
    assert step3b.passed is True


# --- trailing_smoothed_average: DNI_NORMALIZED/CF_NORMALIZED/FCF_NORMALIZED's
# shared TTM-duplicate-aware smoothing ------------------------------------


def test_trailing_smoothed_average_no_duplicate_averages_last_5_points_as_is():
    clean_series = [5.0, 10.0, 20.0, 30.0, 40.0, 50.0]  # 5yr annual + genuine TTM
    result = trailing_smoothed_average(clean_series, ttm_period_duplicates_last_fy=False)
    assert result == pytest.approx((10 + 20 + 30 + 40 + 50) / 5)


def test_trailing_smoothed_average_duplicate_drops_ttm_and_uses_prior_5_distinct_years():
    # SNDK-shaped: a memory-supercycle FY (11433) is both the latest annual
    # figure AND (since no newer quarter has posted) TTM -- appended
    # unadjusted, it would count twice in a 5-point average. Dropping the
    # duplicate TTM and averaging the prior 5 distinct fiscal years instead
    # (Option B) keeps a true 5-point window and doesn't double-weight the
    # spike year. Real cached values, confirmed against the live app during
    # this fix's investigation.
    clean_series = [1064.0, -2143.0, -672.0, -1641.0, 11433.0, 11433.0]
    result = trailing_smoothed_average(clean_series, ttm_period_duplicates_last_fy=True)
    assert result == pytest.approx((1064 - 2143 - 672 - 1641 + 11433) / 5)


def test_trailing_smoothed_average_duplicate_falls_back_when_too_few_points_remain():
    # Dropping TTM would leave only 1 point (len(clean_series) - 1 == 1 <
    # 2) -- the fallback guard keeps TTM rather than shrinking below 2
    # points, same "never make it less scoreable" convention as
    # step4.py::recovery_excluded_prefix_length.
    clean_series = [4.0, 10.0]
    result = trailing_smoothed_average(clean_series, ttm_period_duplicates_last_fy=True)
    assert result == pytest.approx((4 + 10) / 2)


def test_trailing_smoothed_average_respects_custom_window():
    clean_series = [1.0, 2.0, 3.0, 4.0]
    result = trailing_smoothed_average(clean_series, ttm_period_duplicates_last_fy=False, window=2)
    assert result == pytest.approx((3 + 4) / 2)


def test_trailing_smoothed_average_empty_series_is_none():
    assert trailing_smoothed_average([], ttm_period_duplicates_last_fy=False) is None


def test_select_method_falls_through_to_step4_when_current_cfo_or_ni_missing():
    # Step 3 can't run at all (cfo_ttm/net_income_ttm missing) even though
    # CFO's own trend check (step 2) qualifies -- falls through to step 4
    # without ever evaluating FCF (no step "3a"/"3b" in the trail). Net
    # Income and Revenue both genuinely fail here too, and net_income_ttm is
    # also missing, so this lands on PASS with insufficient_data=True (step
    # 3 and step 4a both read as data gaps, not genuine disqualifications).
    result = select_method(
        company_type="Standard",
        cfo_series=[100, 110, 121, 133, 146, 160],
        cfo_ttm=None,
        net_income_series=[50, 40, 30, 20, 10, -5],
        net_income_ttm=None,
        fcf_series=None,
        capex_series=None,
        revenue_series=[500, 450, 400, 350, 300, 280],
    )
    steps_by_id = {s.step: s for s in result.decision_trail}
    assert steps_by_id["3"].passed is None
    assert "3a" not in steps_by_id
    assert "3b" not in steps_by_id
    assert steps_by_id["4"].passed is False  # genuine: recently negative NI
    assert steps_by_id["4a"].passed is None  # genuine gap: TTM NI missing
    assert result.method == "PASS"
    assert result.insufficient_data is True


def test_select_method_dni_when_net_income_consistently_increasing():
    # Step 4 YES -- no CFO data supplied at all (not this test's focus),
    # Net Income increases every year.
    ni = [50, 60, 70, 80, 90, 100]
    result = select_method(
        company_type="Standard",
        cfo_series=None,
        cfo_ttm=None,
        net_income_series=ni,
        net_income_ttm=100,
        fcf_series=None,
        capex_series=None,
        revenue_series=[500, 520, 540, 560, 580, 600],
    )
    assert result.method == "DNI"
    assert result.current_value_source == "net_income_ttm"
    step4 = next(s for s in result.decision_trail if s.step == "4")
    assert step4.passed is True


def test_select_method_dni_normalized_when_profitable_but_inconsistent():
    # Step 4 NO (choppy, not a clean uptrend), step 4a YES (profitable now),
    # step 4a-1 YES (5yr smoothed average is still positive).
    choppy_ni = [50, -10, 40, -5, 45, 30]
    result = select_method(
        company_type="Standard",
        cfo_series=None,
        cfo_ttm=None,
        net_income_series=choppy_ni,
        net_income_ttm=30,
        fcf_series=None,
        capex_series=None,
        revenue_series=[100, 110, 90, 105, 95, 98],
    )
    assert result.method == "DNI_NORMALIZED"
    assert result.current_value_source == "net_income_smoothed"
    steps_by_id = {s.step: s for s in result.decision_trail}
    assert steps_by_id["4"].passed is False
    assert steps_by_id["4a"].passed is True
    assert steps_by_id["4a-1"].passed is True


def test_select_method_psg_when_unprofitable_but_revenue_growing_aggressively():
    # Step 5 YES -- reuses the RIVN-shaped revenue series from the CAGR-base
    # regression test above: a company that clears the zero-revenue-
    # poisoning fix and clears the 15% CAGR bar is actually selected for
    # PSG end-to-end, not just correctly classified in isolation.
    result = select_method(
        company_type="Standard",
        cfo_series=None,
        cfo_ttm=None,
        net_income_series=[-500, -400, -300, -200, -100, -50],
        net_income_ttm=-50,
        fcf_series=None,
        capex_series=None,
        revenue_series=RIVN_STYLE_REVENUE,
    )
    assert result.method == "PSG"
    step5 = next(s for s in result.decision_trail if s.step == "5")
    assert step5.passed is True
    assert "214.8%" in step5.detail


# --- Additive informational fields (never affect verdict/score) ----------


def test_historical_pb_buy_signal_true_at_or_below_minus_1sd():
    assert historical_pb_buy_signal(last_close=90.0, minus_1sd_iv_per_share=100.0) is True
    assert historical_pb_buy_signal(last_close=100.0, minus_1sd_iv_per_share=100.0) is True


def test_historical_pb_buy_signal_false_above_minus_1sd():
    assert historical_pb_buy_signal(last_close=110.0, minus_1sd_iv_per_share=100.0) is False


def test_historical_pb_buy_signal_none_when_data_missing():
    assert historical_pb_buy_signal(None, 100.0) is None
    assert historical_pb_buy_signal(100.0, None) is None


def test_pb_benchmark_for_bank():
    b = pb_benchmark_for("Bank")
    assert b.low == 1.2
    assert b.high == 1.4
    assert b.note is None


def test_pb_benchmark_for_reit_has_conditional_stretch_note():
    b = pb_benchmark_for("REIT/Property Developer")
    assert b.low is None
    assert b.high == 1.2
    assert "1.5" in b.note


def test_pb_benchmark_for_other_types_is_none():
    assert pb_benchmark_for("Standard") is None
    assert pb_benchmark_for("Insurance") is None


def test_dividend_yield_meets_reit_threshold():
    assert dividend_yield_meets_reit_threshold(5.0, threshold_pct=5.0) is True
    assert dividend_yield_meets_reit_threshold(5.5, threshold_pct=5.0) is True
    assert dividend_yield_meets_reit_threshold(4.9, threshold_pct=5.0) is False
    assert dividend_yield_meets_reit_threshold(None, threshold_pct=5.0) is None
    # threshold_pct is a real parameter, not a vestigial one -- a
    # differently-configured threshold changes the result for the same
    # dividend_yield_pct.
    assert dividend_yield_meets_reit_threshold(4.5, threshold_pct=4.0) is True
    assert dividend_yield_meets_reit_threshold(4.5, threshold_pct=5.0) is False


def test_dpu_growth_note_growing():
    note = dpu_growth_note([1.0, 1.1, 1.2, 1.3])
    assert "grew from 1.00 to 1.30" in note


def test_dpu_growth_note_declining():
    note = dpu_growth_note([1.3, 1.2, 1.1, 1.0])
    assert "declined from 1.30 to 1.00" in note


def test_dpu_growth_note_none_when_insufficient_data():
    assert dpu_growth_note([]) is None
    assert dpu_growth_note([1.0]) is None
    assert dpu_growth_note([None, None]) is None


def test_loss_making_pb_reference_note_none_when_either_input_missing():
    assert loss_making_pb_reference_note(None, 50.0) is None
    assert loss_making_pb_reference_note(0.4, None) is None
    assert loss_making_pb_reference_note(None, None) is None


def test_loss_making_pb_reference_note_text_shape():
    note = loss_making_pb_reference_note(0.35, 10.0)
    assert note is not None
    assert "negative TTM earnings" in note
    assert "liquidation value" in note
    assert "0.50x" in note
    assert "Current PB: 0.35x" in note
    assert "Book Value/Share: $10.00" in note
    assert "Manual Calculation" in note
    # Not a fair-value estimate -- the spec is explicit this stays a
    # reference point regardless of which side of 0.50 the ratio lands on.
    assert "not a fair-value estimate" in note
