import asyncio

from sqlmodel import SQLModel, create_engine

import step5_data
import ticker_summary
from debt_metrics import compute_debt_metrics
from step5_data import get_step5_data
from ticker_summary import get_summary

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
    {"date": "2026-03-28", "ebitda": 30_000_000_000, "netInterestIncome": -750_000_000},
    {"date": "2025-12-27", "ebitda": 29_000_000_000, "netInterestIncome": -750_000_000},
    {"date": "2025-09-27", "ebitda": 28_000_000_000, "netInterestIncome": -750_000_000},
    {"date": "2025-06-28", "ebitda": 27_000_000_000, "netInterestIncome": -750_000_000},
]

CASH_FLOW_QUARTERLY = [{"date": "2026-03-28", "netCashProvidedByOperatingActivities": 10_000_000_000} for _ in range(4)]

PROFILE = [{"companyName": "Acme Corp", "sector": "Technology", "industry": "Consumer Electronics"}]


def test_compute_debt_metrics_pure_calculation():
    result = compute_debt_metrics(BALANCE_SHEET_QUARTERLY[0], INCOME_QUARTERLY)
    assert result.total_debt == 100_000_000_000
    assert result.ebitda_ttm == 114_000_000_000
    assert result.net_interest_expense_ttm == 3_000_000_000


def test_compute_debt_metrics_handles_missing_fields():
    assert compute_debt_metrics({}, []) == (None, None, None)
    # Only one of short/long term debt present -- still computable, treating
    # the missing side as 0 rather than the whole figure as unavailable.
    result = compute_debt_metrics({"shortTermDebt": 5_000_000_000}, [])
    assert result.total_debt == 5_000_000_000
    assert result.ebitda_ttm is None
    assert result.net_interest_expense_ttm is None


def test_ticker_summary_and_step5_agree_on_the_same_raw_figures(monkeypatch):
    """The header's 3 new metric tiles and Step 5's debt ratios must never
    diverge for the same ticker -- both call compute_debt_metrics with data
    from the same cache keys, so this proves they land on identical numbers,
    not just similar-looking ones from two separate implementations."""
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step5_data, "engine", test_engine)
    monkeypatch.setattr(ticker_summary, "engine", test_engine)

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
    assert summary_result.net_interest_expense_ttm == 3_000_000_000

    # Re-derive Step 5's debt_to_ebitda from the header's raw figures and
    # confirm it matches Step 5's own ratio exactly -- same numbers, not a
    # coincidentally-close reimplementation.
    expected_debt_to_ebitda = summary_result.total_debt / summary_result.ebitda_ttm
    assert step5_result.ratios["debt_to_ebitda"].value == expected_debt_to_ebitda
