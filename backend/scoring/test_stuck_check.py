"""Pure tests for scoring/stuck_check.py (no I/O). Series are synthetic and built to reproduce the shapes the docs name: a true catch
(CRWD-like), a one-off issuance (ADI-like), post-listing windows (RDDT/HOOD/ARM/FLY-like), exempt tickers (IBKR/GM), SBC not reported
(WMT-like), the cash-conversion agreement test (MSFT/AMZN/DE-like)."""

from dataclasses import replace
from datetime import date

from scoring.stuck_check import (
    DEFAULT_STUCK_SETTINGS,
    FLAGGED,
    NOT_APPLICABLE,
    NOT_REPORTED,
    OK,
    FiscalYear,
    StoredPriceValues,
    StuckRow,
    cash_conversion_row,
    evaluate_fundamental_rows,
    exempt_rows,
    footer_line,
    growth_row,
    margins_row,
    ordinal,
    post_listing_years,
    price_context_row,
    relative_strength_row,
    roic_row,
    shareholder_yield_row,
)

S = DEFAULT_STUCK_SETTINGS


def years(n=10, last=2025, **series):
    """n fiscal years ending `last` (Dec year-end). Each series is a scalar, a callable(i) or a list of n values."""
    out = []
    for i in range(n):
        values = {}
        for name, spec in series.items():
            values[name] = spec(i) if callable(spec) else spec[i] if isinstance(spec, list) else spec
        year = last - n + 1 + i
        out.append(FiscalYear(str(year), date(year, 12, 31), **values))
    return out


def rows_by_key(rows):
    return {r.key: r for r in rows}


def figure(row: StuckRow, key: str):
    return next(f for f in row.figures if f.key == key)


def evaluate(ys, company_type="Standard", ticker="XYZ", ipo=None, settings=S, sector_cagrs=()):
    return rows_by_key(evaluate_fundamental_rows(ys, company_type, ticker, ipo, settings, list(sector_cagrs)))


# --- cash conversion ---------------------------------------------------------------------------------------------------------


def test_cash_conversion_msft_like_last3_low_but_10y_fine_does_not_flag():
    fcf = [124.4 / 7] * 7 + [13.2] * 3  # last 3y 0.66, 10y 0.82
    row = cash_conversion_row(years(revenue=100.0, net_income=20.0, fcf=fcf), S, {})
    assert figure(row, "last_3y").value == 0.66 or abs(figure(row, "last_3y").value - 0.66) < 1e-9
    assert abs(figure(row, "last_10y").value - 0.82) < 1e-9
    assert row.status == OK


def test_cash_conversion_amzn_like_and_de_like_flag_when_both_windows_are_low():
    for ratio3, ratio10 in ((0.43, 0.49), (0.53, 0.46)):
        fcf = [20.0 * ratio10 * 10 / 7 - 3 * 20.0 * ratio3 / 7] * 7 + [20.0 * ratio3] * 3
        row = cash_conversion_row(years(revenue=100.0, net_income=20.0, fcf=fcf), S, {})
        assert abs(figure(row, "last_3y").value - ratio3) < 1e-9
        assert row.status == FLAGGED


def test_cash_conversion_net_income_under_two_percent_of_revenue_is_not_applicable():
    row = cash_conversion_row(years(revenue=100.0, net_income=1.5, fcf=30.0), S, {})
    assert row.status == NOT_APPLICABLE
    assert figure(row, "last_3y").text == "n/m"


def test_cash_conversion_line_is_a_setting():
    ys = years(revenue=100.0, net_income=20.0, fcf=15.0)  # 0.75 in both windows
    assert cash_conversion_row(ys, S, {}).status == OK
    assert cash_conversion_row(ys, replace(S, cash_conversion_line=0.8), {}).status == FLAGGED


def test_cash_conversion_short_history_and_single_window():
    assert cash_conversion_row(years(2, revenue=100.0, net_income=20.0, fcf=20.0), S, {}).status == NOT_REPORTED
    three = cash_conversion_row(years(3, revenue=100.0, net_income=20.0, fcf=20.0), S, {})
    assert [f.key for f in three.figures] == ["last_3y"]  # the long window is the short one: no duplicate figure


# --- SBC (rows 2-4) ----------------------------------------------------------------------------------------------------------


def crwd_like():
    return years(
        10,
        revenue=1000.0,
        net_income=-50.0,
        fcf=280.0,
        sbc=220.0,
        buybacks=0.0,
        diluted_shares=lambda i: 100 * 1.035**i,
    )


def test_true_catch_crwd_like_flags_sbc_and_share_count_and_withholds_the_footer():
    rows = evaluate(crwd_like())
    assert rows["sbc"].status == FLAGGED
    assert figure(rows["sbc"], "sbc_5y_pct_revenue").value == 22.0
    assert abs(figure(rows["sbc"], "sbc_5y_pct_fcf").value - 78.57) < 0.01
    assert rows["share_count"].status == FLAGGED
    assert rows["fcf_after_sbc"].status == OK  # FCF after SBC is still positive
    assert rows["cash_conversion"].status == NOT_APPLICABLE  # net income negative
    assert footer_line(list(rows.values())) is None


def test_buybacks_row_shows_no_buybacks_only_when_sbc_is_heavy():
    rows = evaluate(crwd_like())
    assert figure(rows["buybacks_vs_sbc"], "buybacks_multiple").text == "No buybacks"
    light = evaluate(years(10, revenue=1000.0, net_income=100.0, fcf=100.0, sbc=20.0, buybacks=50.0, diluted_shares=100.0))
    assert "buybacks_vs_sbc" not in light  # 2% of revenue: under the 5% gate
    heavy = evaluate(years(10, revenue=1000.0, net_income=100.0, fcf=300.0, sbc=100.0, buybacks=250.0, diluted_shares=100.0))
    assert figure(heavy["buybacks_vs_sbc"], "buybacks_multiple").value == 2.5


def test_sbc_percent_of_fcf_is_nm_and_counts_as_exceeding_when_fcf_is_not_positive():
    rows = evaluate(years(10, revenue=1000.0, net_income=50.0, fcf=-10.0, sbc=20.0, diluted_shares=100.0))
    f = figure(rows["sbc"], "sbc_5y_pct_fcf")
    assert f.value is None and f.text == "n/m"
    assert rows["sbc"].status == FLAGGED  # 2% of revenue is fine; the n/m FCF share flags
    assert rows["fcf_after_sbc"].status == FLAGGED


def test_sbc_share_above_100_percent_of_fcf_is_nm():
    rows = evaluate(years(10, revenue=1000.0, net_income=50.0, fcf=10.0, sbc=20.0, diluted_shares=100.0))
    assert figure(rows["sbc"], "sbc_5y_pct_fcf").text == "n/m"


def test_sbc_thresholds_are_settings():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=500.0, sbc=60.0, diluted_shares=100.0)  # 6% of revenue, 12% of FCF
    assert evaluate(ys)["sbc"].status == OK
    assert evaluate(ys, settings=replace(S, sbc_revenue_pct=5.0))["sbc"].status == FLAGGED
    assert evaluate(ys, settings=replace(S, sbc_fcf_pct=10.0))["sbc"].status == FLAGGED


def test_sbc_not_reported_wmt_like_follows_into_row_3_and_drops_row_4():
    ys = years(10, revenue=1000.0, net_income=50.0, fcf=60.0, sbc=[0.0] * 8 + [10.0] * 2, diluted_shares=100.0)  # last five: 3 zeros
    rows = evaluate(ys)
    assert rows["sbc"].status == NOT_REPORTED and "3 of the last 5" in rows["sbc"].reason
    assert rows["fcf_after_sbc"].status == NOT_REPORTED
    assert "buybacks_vs_sbc" not in rows
    two_zeros = evaluate(years(10, revenue=1000.0, net_income=50.0, fcf=60.0, sbc=[0.0] * 7 + [10.0] * 3, diluted_shares=100.0))
    assert two_zeros["sbc"].status == OK  # last five: 2 zeros
    missing = evaluate(years(10, revenue=1000.0, net_income=50.0, fcf=60.0, sbc=[None] * 8 + [10.0] * 2, diluted_shares=100.0))
    assert missing["sbc"].status == NOT_REPORTED  # missing counts like zero


def test_fcf_after_sbc_flags_on_a_negative_latest_year_or_a_non_positive_total():
    latest_negative = evaluate(
        years(10, revenue=1000.0, net_income=50.0, fcf=[300.0] * 9 + [40.0], sbc=[50.0] * 9 + [60.0], diluted_shares=100.0)
    )
    assert latest_negative["fcf_after_sbc"].status == FLAGGED
    assert figure(latest_negative["fcf_after_sbc"], "fcf_after_sbc_latest").value == -20.0
    assert figure(latest_negative["fcf_after_sbc"], "fcf_after_sbc_5y").value > 0


def test_fcf_after_sbc_flags_on_a_non_positive_total_even_when_the_latest_year_is_positive():
    ys = years(10, revenue=1000.0, net_income=50.0, fcf=[100.0] * 5 + [-300.0, 100.0, 100.0, 100.0, 120.0], sbc=[50.0] * 9 + [60.0], diluted_shares=100.0)
    row = evaluate(ys)["fcf_after_sbc"]
    assert figure(row, "fcf_after_sbc_5y").value == -140.0  # FCF 120 minus SBC 260 over the last five years
    assert figure(row, "fcf_after_sbc_latest").value == 60.0
    assert row.status == FLAGGED
    # and neither rule holds: positive total, positive latest year
    ok = evaluate(years(10, revenue=1000.0, net_income=50.0, fcf=100.0, sbc=50.0, diluted_shares=100.0))["fcf_after_sbc"]
    assert ok.status == OK


# --- post-listing windows ----------------------------------------------------------------------------------------------------


def test_post_listing_years_start_with_the_first_full_fiscal_year():
    ys = years(10, revenue=1.0)
    kept = post_listing_years(ys, date(2024, 3, 21))
    assert [y.fiscal_year for y in kept] == ["2025"]
    assert [y.fiscal_year for y in post_listing_years(ys, date(2025, 1, 1))] == ["2025"]
    assert len(post_listing_years(ys, None)) == 10


def listing_case(ipo):
    return evaluate(
        years(10, revenue=1000.0, net_income=50.0, fcf=200.0, sbc=300.0, diluted_shares=lambda i: 100 * 1.1**i),
        ipo=ipo,
    )


def test_rddt_like_one_year_since_listing_shows_latest_figures_without_a_label():
    rows = listing_case(date(2024, 3, 21))
    assert rows["sbc"].status is None and rows["fcf_after_sbc"].status is None
    assert figure(rows["sbc"], "sbc_latest").value == 300.0
    assert [f.key for f in rows["sbc"].figures] == ["sbc_latest", "sbc_latest_pct_revenue"]
    assert rows["share_count"].status == NOT_APPLICABLE
    assert "buybacks_vs_sbc" not in rows


def test_arm_like_two_years_since_listing_is_still_unlabelled():
    rows = listing_case(date(2023, 9, 14))
    assert rows["sbc"].status is None and rows["share_count"].status == NOT_APPLICABLE


def test_hood_like_four_years_since_listing_is_labelled_on_the_post_listing_window_only():
    rows = listing_case(date(2021, 7, 29))  # FY2022-FY2025
    assert rows["sbc"].status == FLAGGED
    assert figure(rows["sbc"], "sbc_5y_pct_revenue").label == "4-year total, % of revenue"
    assert rows["share_count"].status == FLAGGED  # 10%/yr over a 4-year window, steady


def test_fly_like_no_year_since_listing():
    rows = listing_case(date(2026, 1, 15))
    assert rows["sbc"].status == NOT_REPORTED and rows["share_count"].status == NOT_APPLICABLE


def test_unlabelled_rows_do_not_count_toward_the_footer():
    rows = list(listing_case(date(2024, 3, 21)).values())
    assert footer_line(rows) == "Nothing flagged (1 of 4 labelled rows assessed)"  # only cash conversion is assessed


# --- exemptions --------------------------------------------------------------------------------------------------------------


def test_ibkr_and_gm_seed_exemptions():
    ys = years(10, revenue=1000.0, net_income=200.0, fcf=-500.0, sbc=50.0, diluted_shares=lambda i: 100 * 1.07**i)
    ibkr = evaluate(ys, ticker="IBKR")
    for key in ("cash_conversion", "fcf_after_sbc", "share_count", "shareholder_yield"):
        assert ibkr[key].status == NOT_APPLICABLE and "Broker" in ibkr[key].reason
    assert ibkr["sbc"].status == OK  # % of revenue still assessed; the %-of-FCF half is exempt
    assert not any(f.key == "sbc_5y_pct_fcf" for f in ibkr["sbc"].figures)
    gm = evaluate(ys, ticker="gm")
    assert [gm[k].status for k in ("cash_conversion", "fcf_after_sbc", "shareholder_yield")] == [NOT_APPLICABLE] * 3
    assert gm["share_count"].status == FLAGGED  # GM's share row is not exempt


def test_exemption_list_is_editable():
    from scoring.stuck_check import Exemption

    custom = replace(S, exemptions=(Exemption("ABC", "Hand-checked", ("1",)),))
    assert exempt_rows("abc", "Standard", custom) == {"1": "Hand-checked"}
    assert exempt_rows("IBKR", "Standard", custom) == {}


def test_bank_insurance_reit_utility_skip_rows_1_and_3_but_keep_the_sbc_revenue_test():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=-50.0, sbc=30.0, diluted_shares=100.0)
    for company_type in ("Bank", "Insurance", "REIT/Property Developer", "Utility"):
        rows = evaluate(ys, company_type=company_type)
        assert rows["cash_conversion"].status == NOT_APPLICABLE
        assert rows["fcf_after_sbc"].status == NOT_APPLICABLE
        assert rows["sbc"].status == OK  # 3% of revenue; negative FCF is not held against a type whose FCF is not comparable
        assert not any(f.key == "sbc_5y_pct_fcf" for f in rows["sbc"].figures)


# --- share count -------------------------------------------------------------------------------------------------------------


def test_adi_like_one_off_issuance_is_ok_with_a_note():
    shares = [100.0] * 4 + [100.0, 100.0, 100.0, 100.0, 100.0, 165.0]  # the whole jump in the last year
    rows = evaluate(years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=shares))
    assert rows["share_count"].status == OK
    assert any("One-off issuance in FY2025" in n for n in rows["share_count"].notes)


def test_steady_dilution_is_flagged_and_the_line_is_a_setting():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=lambda i: 100 * 1.03**i)
    assert evaluate(ys)["share_count"].status == FLAGGED
    assert evaluate(ys, settings=replace(S, share_growth_pct=4.0))["share_count"].status == OK


def test_one_off_line_is_a_setting():
    shares = [100.0] * 8 + [110.0, 160.0]  # 2nd-to-last small, last big: the big one is ~79% of the log dilution
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=shares)
    assert evaluate(ys)["share_count"].status == OK
    assert evaluate(ys, settings=replace(S, one_off_pct=90.0))["share_count"].status == FLAGGED


def test_reit_and_utility_share_count_is_a_figure_with_no_label():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=lambda i: 100 * 1.2**i)
    for company_type in ("REIT/Property Developer", "Utility"):
        row = evaluate(ys, company_type=company_type)["share_count"]
        assert row.status is None and figure(row, "share_cagr").value > 19


def test_shrinking_share_count_is_ok():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=lambda i: 100 * 0.97**i)
    assert evaluate(ys)["share_count"].status == OK


def test_missing_share_counts_are_not_reported():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=None)
    assert evaluate(ys)["share_count"].status == NOT_REPORTED


# --- footer ------------------------------------------------------------------------------------------------------------------


def clean_years():
    return years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=100.0)


def test_nothing_flagged_footer_counts_only_assessed_labelled_rows():
    rows = list(evaluate(clean_years()).values())
    assert footer_line(rows) == "Nothing flagged (4 of 4 labelled rows assessed)"
    wmt = list(evaluate(years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=0.0, diluted_shares=100.0)).values())
    assert footer_line(wmt) == "Nothing flagged (2 of 4 labelled rows assessed)"


def test_footer_is_withheld_when_any_of_the_four_rows_is_flagged():
    ys = years(10, revenue=1000.0, net_income=100.0, fcf=120.0, sbc=20.0, diluted_shares=lambda i: 100 * 1.05**i)
    assert footer_line(list(evaluate(ys).values())) is None


# --- shareholder yield, margins, growth, ROIC --------------------------------------------------------------------------------


def test_shareholder_yield_is_a_figure_only_and_nm_on_non_positive_fcf():
    ys = years(10, fcf=100.0, dividends=30.0, net_buybacks=45.0)
    row = shareholder_yield_row(ys, {})
    assert row.status is None and figure(row, "shareholder_yield_pct_fcf").value == 75.0
    assert figure(shareholder_yield_row(years(10, fcf=-1.0, dividends=1.0, net_buybacks=1.0), {}), "shareholder_yield_pct_fcf").text == "n/m"


def test_margins_first_vs_last_three_years_with_slope_and_gross_margin_secondary():
    ys = years(5, revenue=100.0, operating_income=[10.0, 12.0, 14.0, 16.0, 18.0], gross_profit=50.0)
    row = margins_row(ys, "Standard", {})
    assert figure(row, "operating_margin_first3").value == 12.0
    assert figure(row, "operating_margin_last3").value == 16.0
    assert abs(figure(row, "operating_margin_slope").value - 2.0) < 1e-9
    assert figure(row, "gross_margin_last3").value == 50.0


def test_gross_margin_is_dropped_near_100_percent_and_for_banks():
    near_100 = margins_row(years(5, revenue=100.0, operating_income=10.0, gross_profit=100.0), "Standard", {})
    assert not any(f.key.startswith("gross") for f in near_100.figures) and near_100.notes
    bank = margins_row(years(5, revenue=100.0, operating_income=10.0, gross_profit=40.0), "Bank", {})
    assert not any(f.key.startswith("gross") for f in bank.figures)


def test_growth_cagr_percentile_and_ordinals():
    ys = years(10, revenue=lambda i: 100 * 1.2**i)
    row = growth_row(ys, [5.0, 8.0, 10.0, 12.0, 15.0, 30.0], {})
    assert abs(figure(row, "revenue_cagr_5y").value - 20.0) < 1e-9
    assert figure(row, "sector_median_cagr").value == 11.0
    assert figure(row, "sector_percentile").text == "83rd percentile"  # 5 of 6 peers below
    assert abs(figure(row, "latest_vs_cagr").value) < 1e-9
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 93, 100)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "93rd", "100th"]


def test_growth_without_enough_sector_peers_has_no_median():
    row = growth_row(years(10, revenue=lambda i: 100 * 1.1**i), [5.0, 6.0], {})
    assert not any(f.key == "sector_median_cagr" for f in row.figures) and row.notes


def test_growth_covid_trough_base_year_note():
    revenue = [100.0, 100.0, 100.0, 100.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0]  # FY2016-2025; base = FY2020 (down 30%)
    ys = years(10, revenue=revenue)
    row = growth_row(ys, [], {})
    # base year = 6th from the end = FY2020, FYE 2020-12-31 (inside the window), 30% under FY2019
    assert any("COVID" in n for n in row.notes)
    mild = growth_row(years(10, revenue=[100.0] * 4 + [90.0] + [100.0] * 5), [], {})
    assert not any("COVID" in n for n in mild.notes)  # only 10% below
    late = growth_row(years(10, last=2030, revenue=revenue), [], {})
    assert not any("COVID" in n for n in late.notes)  # base FYE outside 2020-03..2021-03


def test_growth_needs_six_years():
    assert growth_row(years(5, revenue=100.0), [], {}).status == NOT_REPORTED


def test_roic_drops_exact_zeros_and_is_standard_only():
    ys = years(5, roic_pct=[0.0, 10.0, 12.0, 14.0, 16.0])
    row = roic_row(ys, "Standard", {})
    assert figure(row, "roic_first").value == 10.0 and abs(figure(row, "roic_slope").value - 2.0) < 1e-9
    assert roic_row(ys, "Utility", {}).status == NOT_APPLICABLE
    assert roic_row(years(5, roic_pct=[0.0, 0.0, 0.0, 5.0, 6.0]), "Standard", {}).status == NOT_REPORTED


# --- price rows --------------------------------------------------------------------------------------------------------------


def test_price_context_passes_the_stored_values_through_untouched():
    row = price_context_row(
        StoredPriceValues("Pass with caution", "undervalued", "decline", date(2026, 3, 2), True, "underperform", -14.2)
    )
    assert row.status is None
    assert figure(row, "overall_verdict").text == "Pass with caution"
    assert figure(row, "weinstein_stage").text == "decline"
    assert figure(row, "perf_5y_vs_spy").value == -14.2 and figure(row, "perf_5y_vs_spy").text == "underperform"
    assert figure(row, "weinstein_since").text == "2026-03-02" and row.notes
    assert price_context_row(None).status == NOT_REPORTED


def test_relative_strength_words_band_and_weight_note():
    stock = {1: 3.0, 3: 5.0, 6: 20.0, 12: 10.0}
    sector = {1: 1.0, 3: 5.5, 6: 10.0, 12: 14.0}
    spy = {1: 0.0, 3: 0.0, 6: 19.0, 12: 0.0}
    row = relative_strength_row(stock, sector, spy, "XLK", 2.0, sector_weight_pct=12.0)
    words = {f.key: f.text for f in row.figures}
    assert words["vs_sector_6m"] == "leads" and words["vs_sector_12m"] == "trails"
    assert words["vs_sector_3m"] == "in line"  # -0.5 pp, inside +/-2
    assert words["vs_sector_1m"] == "in line"  # exactly on the 2 pp edge
    assert words["vs_spy_6m"] == "in line" and words["vs_spy_12m"] == "leads"
    assert [f.key for f in row.figures][:2] == ["vs_sector_6m", "vs_sector_12m"]  # headline first
    assert row.notes and "12%" in row.notes[0]
    assert not relative_strength_row(stock, sector, spy, "XLK", 2.0, sector_weight_pct=9.0).notes
    assert relative_strength_row(stock, sector, spy, "XLK", 0.5).figures[3].text == "leads"  # band is a setting


def test_relative_strength_states():
    assert relative_strength_row({6: 1.0}, None, {}, None, 2.0).status == NOT_APPLICABLE
    assert relative_strength_row({}, {6: 1.0}, {}, "XLK", 2.0).status == NOT_REPORTED
