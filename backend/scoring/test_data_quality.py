"""Tests for scoring/data_quality.py: the three cache-only checks, with the known cases of the 2026-10-09 investigation as fixtures
(values are the cached FMP rows, rounded)."""

import pytest

from scoring import data_quality as dq

M = 1_000_000


def cf(date, cfo, capex, sbc=100 * M, ni=0.0, fy=None):
    return {
        "date": date,
        "fiscalYear": fy or date[:4],
        "netCashProvidedByOperatingActivities": cfo,
        "capitalExpenditure": capex,
        "stockBasedCompensation": sbc,
        "netIncome": ni,
    }


def inc(date, revenue, ni, cont=None, fy=None):
    row = {"date": date, "fiscalYear": fy or date[:4], "revenue": revenue, "netIncome": ni}
    if cont is not None:
        row["netIncomeFromContinuingOperations"] = cont
    return row


# --- 1. zero newest capex -------------------------------------------------------------------------------------------------------


def mu():
    annual = [cf("2026-09-03", 89675 * M, 0), cf("2025-08-28", 17525 * M, -15857 * M), cf("2024-08-29", 8507 * M, -8386 * M),
              cf("2023-08-31", 1558 * M, -7708 * M)]
    quarterly = [cf("2026-09-03", 43973 * M, -17165 * M), cf("2026-05-28", 25388 * M, -7826 * M), cf("2026-02-26", 11903 * M, -6387 * M),
                 cf("2025-11-27", 8411 * M, -5389 * M), cf("2025-08-28", 5730 * M, -5658 * M)]
    income = [inc("2026-09-03", 120000 * M, 40000 * M), inc("2025-08-28", 37000 * M, 8000 * M)]
    return annual, quarterly, income


def test_mu_newest_capex_zero_with_quarterly_capex_is_flagged():
    annual, quarterly, income = mu()
    flags = dq.check_zero_newest_capex("MU", "Standard", annual, quarterly, income)
    assert len(flags) == 1
    f = flags[0]
    assert (f.check, f.field, f.fiscal_year, f.kind) == (dq.CHECK_ZERO_CAPEX, "capitalExpenditure", "2026", dq.KIND_ZERO_LINE)
    assert f.fmp_value == 0.0 and f.comparison_value == -15857 * M
    assert "FY2026 capex is 0" in f.detail and "free cash flow may be overstated" in f.detail


def test_csco_syy_stx_shapes_are_flagged():
    # CSCO FY2026, SYY FY2026, STX FY2026: newest annual capex 0, earlier years 900M-ish / 265M, quarters carry capex.
    for newest, prior, quarter in (
        (("2026-07-25", 14177 * M), (-905 * M, -670 * M, -740 * M), -192 * M),
        (("2026-06-27", 2699 * M), (-906 * M, -832 * M, -700 * M), -161 * M),
        (("2026-07-03", 3674 * M), (-265 * M, -254 * M, -316 * M), -187 * M),
    ):
        annual = [cf(newest[0], newest[1], 0)] + [
            cf(f"{2025 - i}-{newest[0][5:]}", newest[1] / 2, c, fy=str(2025 - i)) for i, c in enumerate(prior)
        ]
        quarterly = [cf(newest[0], 1000 * M, quarter), cf(f"2026-01{newest[0][7:]}", 900 * M, quarter)]
        income = [inc(newest[0], 20000 * M, 3000 * M)]
        assert len(dq.check_zero_newest_capex("X", "Standard", annual, quarterly, income)) == 1


def test_no_quarterly_rows_still_flags_on_prior_years():
    annual, _, income = mu()
    flags = dq.check_zero_newest_capex("MU", "Standard", annual, [], income)
    assert len(flags) == 1 and "after" in flags[0].detail


def test_quarters_that_agree_with_the_zero_are_not_flagged():
    annual, _, income = mu()
    quarters = [cf("2026-09-03", 1 * M, 0), cf("2026-05-28", 1 * M, 0), cf("2026-02-26", 1 * M, 0)]
    assert dq.check_zero_newest_capex("MU", "Standard", annual, quarters, income) == []


def test_capex_present_or_never_present_is_not_flagged():
    annual, quarterly, income = mu()
    healed = [dict(annual[0], capitalExpenditure=-36767 * M)] + annual[1:]
    assert dq.check_zero_newest_capex("MU", "Standard", healed, quarterly, income) == []
    never = [dict(r, capitalExpenditure=0) for r in annual]  # COIN-like: capex is always 0
    assert dq.check_zero_newest_capex("COIN", "Standard", never, quarterly, income) == []


def test_only_one_prior_year_with_capex_is_not_enough():
    annual = [cf("2026-07-03", 3674 * M, 0), cf("2025-06-27", 1083 * M, -265 * M), cf("2024-06-28", 900 * M, 0), cf("2023-06-30", 800 * M, 0)]
    assert dq.check_zero_newest_capex("X", "Standard", annual, [], [inc("2026-07-03", 10000 * M, 1)]) == []


def test_lenders_insurers_and_reits_are_skipped():
    annual, quarterly, income = mu()
    for company_type in ("Bank", "Insurance", "REIT/Property Developer"):
        assert dq.check_zero_newest_capex("X", company_type, annual, quarterly, income) == []


def test_tiny_prior_capex_against_revenue_is_not_flagged():
    annual = [cf("2026-07-03", 3674 * M, 0), cf("2025-06-27", 1 * M, -1 * M), cf("2024-06-28", 1 * M, -1 * M), cf("2023-06-30", 1 * M, -1 * M)]
    assert dq.check_zero_newest_capex("X", "Standard", annual, [], [inc("2026-07-03", 50000 * M, 1)]) == []


def test_a_blanked_placeholder_newest_row_is_left_to_its_own_marker():
    annual, quarterly, income = mu()
    blanked = [dict(annual[0], netCashProvidedByOperatingActivities=None, capitalExpenditure=None)] + annual[1:]
    assert dq.check_zero_newest_capex("X", "Standard", blanked, quarterly, income) == []


# --- 2. SBC gap ------------------------------------------------------------------------------------------------------------------


def sbc_rows(values):
    """values oldest first -> most-recent-first cash-flow rows, one per year ending 2025."""
    n = len(values)
    return [cf(f"{2025 - i}-12-31", 1000 * M, -100 * M, sbc=v * M) for i, v in enumerate(reversed(values))]


def test_zero_between_non_zero_years_is_flagged():
    flags = dq.check_sbc_gap("X", sbc_rows([100, 110, 0, 130, 140]))
    assert [(f.fiscal_year, f.kind) for f in flags] == [("2023", dq.KIND_ZERO_BETWEEN)]
    assert flags[0].comparison_value == 110 * M and flags[0].fmp_value == 0.0


def test_zero_in_the_newest_year_after_non_zero_years_is_flagged():
    flags = dq.check_sbc_gap("X", sbc_rows([100, 110, 120, 130, 0]))
    assert [(f.fiscal_year, f.kind) for f in flags] == [("2025", dq.KIND_ZERO_NEWEST)]


def test_all_zero_and_leading_zero_histories_are_not_gap_flags():
    assert dq.check_sbc_gap("GM", sbc_rows([0, 0, 0, 0, 0])) == []
    assert dq.check_sbc_gap("X", sbc_rows([0, 0, 100, 110, 120])) == []  # zeros before the first non-zero year


def test_missing_value_counts_as_zero():
    rows = sbc_rows([100, 110, 120, 130, 140])
    rows[2]["stockBasedCompensation"] = None
    assert [f.fiscal_year for f in dq.check_sbc_gap("X", rows)] == ["2023"]


def test_sbc_zero_year_count_covers_the_last_five_years():
    assert dq.sbc_zero_years(sbc_rows([100, 110, 0, 130, 140])) == dq.SbcZeroYears(1, 5, ("2023",))
    assert dq.sbc_zero_years(sbc_rows([0, 0, 0, 0, 0])).zero_years == 5
    assert dq.sbc_zero_years(sbc_rows([0, 0, 100, 110, 120, 130, 140])).zero_years == 0  # the oldest years fall outside the window
    assert dq.sbc_zero_years(sbc_rows([100, 110])) == dq.SbcZeroYears(0, 2, ())


# --- 3. net income disagreement -------------------------------------------------------------------------------------------------


def ni_case(pairs):
    """pairs: [(year, income NI, cash-flow NI, continuing NI or None)] newest first, revenue 10B."""
    income = [inc(f"{y}-12-31", 10_000 * M, i * M, cont=None if c is None else c * M) for y, i, _, c in pairs]
    cash = [cf(f"{y}-12-31", 500 * M, -50 * M, ni=n * M) for y, _, n, _ in pairs]
    return income, cash


def test_wtw_sign_difference_is_a_data_error():
    income, cash = ni_case([(2025, 1605, 1613, 1613), (2024, -98, 1248, -88), (2023, 1055, 1055, 1064)])
    flags = dq.check_net_income_disagreement("WTW", income, cash)
    assert len(flags) == 1
    f = flags[0]
    assert (f.fiscal_year, f.kind, f.fmp_value, f.comparison_value) == ("2024", dq.KIND_SIGN_DIFFERS, -98 * M, 1248 * M)
    assert "opposite signs" in f.detail


def test_ibkr_attributable_vs_consolidated_is_a_definition_not_an_error():
    income, cash = ni_case([(2025, 984, 4357, 4357), (2024, 755, 3407, 3407), (2023, 600, 2812, 2812), (2022, 380, 1842, 1842), (2021, 308, 1636, 1636)])
    flags = dq.check_net_income_disagreement("IBKR", income, cash)
    assert [(f.fiscal_year, f.kind) for f in flags] == [("2025", dq.KIND_DEFINITION)]
    assert "not an error" in flags[0].detail


def test_cash_flow_matching_continuing_operations_is_a_definition_even_in_one_year():
    # JNJ FY2023: net earnings 35,153 include a 21.8B discontinued-operations gain; the cash-flow line is continuing income.
    income, cash = ni_case([(2024, 14066, 14066, 14066), (2023, 35153, 13326, 13326)])
    flags = dq.check_net_income_disagreement("JNJ", income, cash)
    assert [f.kind for f in flags] == [dq.KIND_DEFINITION]


def test_persistent_higher_cash_flow_figure_without_a_continuing_field_is_a_definition():
    income, cash = ni_case([(y, 100 + y - 2021, 300 + y - 2021, None) for y in (2025, 2024, 2023, 2022, 2021)])
    assert [f.kind for f in dq.check_net_income_disagreement("X", income, cash)] == [dq.KIND_DEFINITION]


def test_unexplained_large_gap_in_one_year_is_flagged_and_small_gaps_are_not():
    income, cash = ni_case([(2025, 1605, 1613, None), (2024, 1000, 1010, None), (2023, 1000, 400, None)])
    flags = dq.check_net_income_disagreement("X", income, cash)
    assert [(f.fiscal_year, f.kind) for f in flags] == [("2023", dq.KIND_LARGE_GAP)]


def test_immaterial_gap_against_revenue_is_ignored():
    income = [inc("2025-12-31", 10_000_000 * M, 100 * M)]
    cash = [cf("2025-12-31", 5 * M, -1 * M, ni=-50 * M)]  # opposite signs but 150M on 10T revenue
    assert dq.check_net_income_disagreement("X", income, cash) == []


def test_old_years_beyond_the_scan_window_are_not_flagged():
    income, cash = ni_case([(2025, 100, 100, None), (2024, 100, 100, None), (2023, 100, 100, None), (2022, 1000, -400, None)])
    assert dq.check_net_income_disagreement("X", income, cash) == []


def test_blanked_cash_flow_row_is_skipped():
    income, cash = ni_case([(2025, 1000, 5, None)])
    cash[0]["netCashProvidedByOperatingActivities"] = None
    assert dq.check_net_income_disagreement("X", income, cash) == []


# --- all checks --------------------------------------------------------------------------------------------------------------------


def test_run_checks_returns_every_check_in_a_stable_order():
    annual, quarterly, income = mu()
    annual[2]["stockBasedCompensation"] = 0
    flags = dq.run_checks("MU", "Standard", income, annual, quarterly)
    # the fixture's cash-flow net income is 0 beside real income-statement figures, so the third check fires too (two years)
    assert [f.check for f in flags] == [dq.CHECK_ZERO_CAPEX, dq.CHECK_SBC_GAP, dq.CHECK_NET_INCOME, dq.CHECK_NET_INCOME]
    assert all(isinstance(f, dq.QualityFlag) for f in flags)


@pytest.mark.parametrize("check", dq.CHECKS)
def test_empty_inputs_never_raise(check):
    assert dq.run_checks("X", None, [], [], []) == []
