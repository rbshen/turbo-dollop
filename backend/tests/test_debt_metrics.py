import asyncio

from sqlmodel import SQLModel, create_engine

import data.step2_data as step2_data
import data.step3_data as step3_data
import data.step5_data as step5_data
import data.ticker_summary as ticker_summary
from helpers.debt_metrics import compute_debt_metrics
from data.step5_data import get_step5_data
from data.ticker_summary import get_summary

BALANCE_SHEET_QUARTERLY = [
    {
        "date": "2026-03-28",
        "totalCurrentAssets": 500,
        "totalCurrentLiabilities": 400,
        "shortTermDebt": 5_000_000_000,
        "longTermDebt": 95_000_000_000,
        "totalDebt": 100_000_000_000,
        "totalAssets": 1000,
        "deferredRevenue": 20,
    }
]

INCOME_QUARTERLY = [
    {
        "date": "2026-03-28",
        "ebitda": 30_000_000_000,
        "operatingIncome": 22_000_000_000,
        "interestExpense": 800_000_000,
        "interestIncome": 50_000_000,
        "netInterestIncome": -750_000_000,
    },
    {
        "date": "2025-12-27",
        "ebitda": 29_000_000_000,
        "operatingIncome": 21_000_000_000,
        "interestExpense": 800_000_000,
        "interestIncome": 50_000_000,
        "netInterestIncome": -750_000_000,
    },
    {
        "date": "2025-09-27",
        "ebitda": 28_000_000_000,
        "operatingIncome": 20_000_000_000,
        "interestExpense": 800_000_000,
        "interestIncome": 50_000_000,
        "netInterestIncome": -750_000_000,
    },
    {
        "date": "2025-06-28",
        "ebitda": 27_000_000_000,
        "operatingIncome": 19_000_000_000,
        "interestExpense": 800_000_000,
        "interestIncome": 50_000_000,
        "netInterestIncome": -750_000_000,
    },
]

CASH_FLOW_QUARTERLY = [{"date": "2026-03-28", "netCashProvidedByOperatingActivities": 10_000_000_000} for _ in range(4)]

PROFILE = [{"companyName": "Acme Corp", "sector": "Technology", "industry": "Consumer Electronics"}]


def test_compute_debt_metrics_pure_calculation():
    result = compute_debt_metrics(BALANCE_SHEET_QUARTERLY[0], INCOME_QUARTERLY)
    assert result.total_debt == 100_000_000_000
    assert result.ebitda_ttm == 114_000_000_000
    assert result.ebit_ttm == 82_000_000_000
    assert result.interest_expense_ttm == 3_200_000_000
    assert result.interest_income_ttm == 200_000_000
    assert result.net_interest_expense_ttm == 3_000_000_000


def test_compute_debt_metrics_handles_missing_fields():
    empty_result = compute_debt_metrics({}, [])
    assert empty_result.total_debt is None
    assert empty_result.ebitda_ttm is None
    assert empty_result.ebit_ttm is None
    assert empty_result.interest_expense_ttm is None
    assert empty_result.interest_income_ttm is None
    assert empty_result.net_interest_expense_ttm is None
    assert empty_result.outlier_flags == []

    # Only one of short/long term debt present -- still computable, treating
    # the missing side as 0 rather than the whole figure as unavailable.
    result = compute_debt_metrics({"shortTermDebt": 5_000_000_000}, [])
    assert result.total_debt == 5_000_000_000
    assert result.ebitda_ttm is None
    assert result.ebit_ttm is None
    assert result.interest_expense_ttm is None
    assert result.interest_income_ttm is None
    assert result.net_interest_expense_ttm is None


# Synthetic (not TEAM's own field-for-field data -- TEAM's real ebitda
# quarter specifically was NOT a duplicate of its annual row, see
# test_ttm.py's TEAM-shaped fixture for that distinction): the latest
# quarter (a Q4) IS a content-duplicate of the annual row here, so this
# exercises compute_debt_metrics's correction path directly.
TEAM_SHAPED_INCOME_ANNUAL = [{"fiscalYear": "2026", "ebitda": 212_168_000}]

TEAM_SHAPED_INCOME_QUARTERLY = [
    {"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "ebitda": 212_168_000},
    {"date": "2026-03-31", "period": "Q3", "fiscalYear": "2026", "ebitda": 10_000_000},
    {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "ebitda": 8_000_000},
    {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "ebitda": 6_000_000},
]


def test_compute_debt_metrics_corrects_team_shaped_ebitda_when_annual_passed():
    result = compute_debt_metrics(BALANCE_SHEET_QUARTERLY[0], TEAM_SHAPED_INCOME_QUARTERLY, TEAM_SHAPED_INCOME_ANNUAL)
    # True isolated Q4 = 212,168,000 - (10,000,000+8,000,000+6,000,000) =
    # 188,168,000; TTM = corrected_Q4 + other 3 = the annual figure itself,
    # 212,168,000 -- not 236,168,000 (the raw, double-counted sum a pre-fix
    # Fathom would have computed).
    assert result.ebitda_ttm == 212_168_000
    assert result.outlier_flags == []


def test_compute_debt_metrics_unaffected_when_income_annual_omitted():
    # Backward compatibility: ticker_summary.py doesn't fetch income_annual,
    # so this call site's figures must stay exactly as before this
    # parameter existed -- the raw, uncorrected sum.
    result = compute_debt_metrics(BALANCE_SHEET_QUARTERLY[0], TEAM_SHAPED_INCOME_QUARTERLY)
    assert result.ebitda_ttm == 212_168_000 + 10_000_000 + 8_000_000 + 6_000_000


def test_ticker_summary_and_step5_agree_on_the_same_raw_figures(monkeypatch):
    """The header's raw metric tiles and Step 5's debt ratios must never
    diverge for the same ticker -- both call compute_debt_metrics with data
    from the same cache keys, so this proves they land on identical numbers,
    not just similar-looking ones from two separate implementations."""
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step5_data, "engine", test_engine)
    monkeypatch.setattr(ticker_summary, "engine", test_engine)
    # get_summary() also calls get_step2_data()/get_step3_data() (see
    # ticker_summary.py), each of which manages its own independent
    # Session(engine) bound to step2_data's/step3_data's own module-level
    # import -- patching only step5_data/ticker_summary's engine leaves
    # these two writing straight to the real core.db.engine. Confirmed
    # root cause of the PEP/ACME fixture-contamination recurrence
    # (2026-08-04, see CLAUDE.md) -- this is the exact fix.
    monkeypatch.setattr(step2_data, "engine", test_engine)
    monkeypatch.setattr(step3_data, "engine", test_engine)

    async def fake_profile(ticker):
        return PROFILE

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY

    async def fake_income_statement(ticker, period, limit):
        return INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_QUARTERLY

    async def fake_empty_list(*args, **kwargs):
        return []

    for mod in (step5_data, ticker_summary):
        monkeypatch.setattr(mod.fmp_client, "get_profile", fake_profile)
        monkeypatch.setattr(mod.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
        monkeypatch.setattr(mod.fmp_client, "get_income_statement", fake_income_statement)

    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_quote", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_price_change", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_ratios", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_analyst_estimates", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_earnings", fake_empty_list)

    step5_result = asyncio.run(get_step5_data("acme"))
    summary_result = asyncio.run(get_summary("acme"))

    assert summary_result.total_debt == 100_000_000_000
    assert summary_result.ebitda_ttm == 114_000_000_000
    assert summary_result.interest_expense_ttm == 3_200_000_000
    assert summary_result.interest_income_ttm == 200_000_000

    # Re-derive Step 5's debt_to_ebitda from the header's raw figures and
    # confirm it matches Step 5's own ratio exactly -- same numbers, not a
    # coincidentally-close reimplementation.
    expected_debt_to_ebitda = summary_result.total_debt / summary_result.ebitda_ttm
    assert step5_result.ratios["debt_to_ebitda"].value == expected_debt_to_ebitda
    assert step5_result.outlier_warnings == []
    assert summary_result.outlier_warnings == []


# 4 recent quarters (most-recent-first) with an anomalous interestExpense in
# the most recent one, plus 8 stable baseline quarters -- mirrors the real
# PEP Q2 2026 case (confirmed a data error, ~10x the trailing median).
INCOME_QUARTERLY_WITH_OUTLIER = [
    {"date": "2026-06-13", "ebitda": 5_000_000_000, "interestExpense": 2_300_000_000, "interestIncome": 0, "netInterestIncome": -2_300_000_000},
    {"date": "2026-03-21", "ebitda": 4_800_000_000, "interestExpense": 301_000_000, "interestIncome": 0, "netInterestIncome": -301_000_000},
    {"date": "2025-12-27", "ebitda": 4_700_000_000, "interestExpense": 333_000_000, "interestIncome": 0, "netInterestIncome": -333_000_000},
    {"date": "2025-09-06", "ebitda": 4_600_000_000, "interestExpense": 264_000_000, "interestIncome": 0, "netInterestIncome": -264_000_000},
] + [
    {"date": f"baseline-{i}", "ebitda": 4_500_000_000, "interestExpense": v, "interestIncome": 0, "netInterestIncome": -v}
    for i, v in enumerate([260_000_000, 264_000_000, 264_000_000, 219_000_000, 230_000_000, 240_000_000, 250_000_000, 245_000_000])
]


def test_outlier_warning_propagates_through_step5_and_ticker_summary(monkeypatch):
    """The PEP-style anomaly must surface in both API responses -- as a
    warning only, never changing the ratio/score/verdict it's attached to."""
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step5_data, "engine", test_engine)
    monkeypatch.setattr(ticker_summary, "engine", test_engine)
    # get_summary() also calls get_step2_data()/get_step3_data() (see
    # ticker_summary.py), each of which manages its own independent
    # Session(engine) bound to step2_data's/step3_data's own module-level
    # import -- patching only step5_data/ticker_summary's engine leaves
    # these two writing straight to the real core.db.engine. Confirmed
    # root cause of the PEP/ACME fixture-contamination recurrence
    # (2026-08-04, see CLAUDE.md) -- this is the exact fix.
    monkeypatch.setattr(step2_data, "engine", test_engine)
    monkeypatch.setattr(step3_data, "engine", test_engine)

    async def fake_profile(ticker):
        return PROFILE

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY

    async def fake_income_statement(ticker, period, limit):
        return INCOME_QUARTERLY_WITH_OUTLIER

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_QUARTERLY

    async def fake_empty_list(*args, **kwargs):
        return []

    for mod in (step5_data, ticker_summary):
        monkeypatch.setattr(mod.fmp_client, "get_profile", fake_profile)
        monkeypatch.setattr(mod.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
        monkeypatch.setattr(mod.fmp_client, "get_income_statement", fake_income_statement)

    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_quote", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_price_change", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_ratios", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_analyst_estimates", fake_empty_list)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_earnings", fake_empty_list)

    # This test predates the SEC EDGAR cross-check and isn't testing it --
    # short-circuit to "no CIK found" so it doesn't hit the real network
    # (get_step5_data now calls it whenever net_interest_expense_ttm is
    # flagged, which it is here). The cross-check itself is covered by
    # test_sec_edgar.py and the dedicated tests in test_step5_data.py.
    async def fake_get_cik(session, ticker, staleness_days):
        return None

    monkeypatch.setattr(step5_data.sec_edgar, "get_cik", fake_get_cik)

    step5_result = asyncio.run(get_step5_data("pep"))
    summary_result = asyncio.run(get_summary("pep"))

    # The raw TTM sum itself is unaffected -- still includes the flagged
    # $2.3B quarter exactly as fetched, not dropped or adjusted.
    assert summary_result.interest_expense_ttm == 2_300_000_000 + 301_000_000 + 333_000_000 + 264_000_000

    # Both interest_expense_ttm and net_interest_expense_ttm are genuinely
    # anomalous here (interestIncome is a constant 0, so netInterestIncome
    # mirrors -interestExpense exactly) -- both correctly flag.
    for warnings in (step5_result.outlier_warnings, summary_result.outlier_warnings):
        assert len(warnings) == 2
        metrics = {w.metric for w in warnings}
        assert metrics == {"interest_expense_ttm", "net_interest_expense_ttm"}
        assert all(w.date == "2026-06-13" for w in warnings)

    # Purely informational -- doesn't change Step 5's verdict/score/tiers.
    assert step5_result.verdict in {"Pass", "Strong Pass", "Fail"}
    assert step5_result.score is not None


# TEAM's actual FY2026/Q4 FY2026 cash-flow shape (2026-08-16 investigation):
# the Q4 quarterly row is byte-identical to the annual row for CFO --
# get_step5_data now fetches cash_flow_statement/annual specifically to
# correct this before summing (a fetch this test file didn't previously
# need to cover, since it didn't exist before this fix).
TEAM_ANNUAL_CASH_FLOW = [{"fiscalYear": "2026", "netCashProvidedByOperatingActivities": 1_353_135_000}]

TEAM_QUARTERLY_CASH_FLOW = [
    {"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 1_353_135_000},
    {"date": "2026-03-31", "period": "Q3", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 567_475_000},
    {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 177_805_000},
    {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 128_715_000},
]


def test_step5_cfo_ttm_corrects_team_shaped_duplicate_annual_quarter(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step5_data, "engine", test_engine)

    async def fake_profile(ticker):
        return PROFILE

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY

    async def fake_income_statement(ticker, period, limit):
        return INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return TEAM_QUARTERLY_CASH_FLOW if period == "quarter" else TEAM_ANNUAL_CASH_FLOW

    monkeypatch.setattr(step5_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    step5_result = asyncio.run(get_step5_data("team"))

    # True isolated Q4 CFO = 1,353,135,000 - (567,475,000+177,805,000+
    # 128,715,000) = 479,140,000; TTM = corrected_Q4 + other 3 = the annual
    # figure itself, 1,353,135,000 -- not 2,227,130,000 (the raw, double-
    # counted sum a pre-fix Fathom would have computed). Not directly
    # exposed on Step5Out, so cross-checked via debt_servicing_ratio (=
    # net_interest_expense_ttm / cfo_ttm * 100 -- see step5_data.py). Reused
    # INCOME_QUARTERLY gives net_interest_expense_ttm = 750,000,000 * 4 =
    # 3,000,000,000.
    expected_dsr = 3_000_000_000 / 1_353_135_000 * 100
    assert step5_result.ratios["debt_servicing_ratio"].value == expected_dsr
    # No CFO-related outlier warning -- correctly resolved, not just flagged.
    assert not any(w.metric == "cfo_ttm" for w in step5_result.outlier_warnings)
