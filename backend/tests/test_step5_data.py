import asyncio

from sqlmodel import SQLModel, create_engine

import step5_data
from step5_data import get_step5_data

PROFILE = [{"sector": "Technology", "industry": "Consumer Electronics"}]

# Deliberately very different from the quarterly figures below -- if the
# code ever mistakenly fetched/used the annual balance sheet instead of
# quarterly, these numbers would produce a hard-fail Current Ratio (0.1)
# instead of the quarterly figures' 1.25, so a regression here is caught by
# the resulting ratio/tier, not just by which endpoint got called.
BALANCE_SHEET_ANNUAL = [
    {
        "date": "2025-09-27",
        "period": "FY",
        "totalCurrentAssets": 100,
        "totalCurrentLiabilities": 1000,
        "shortTermDebt": 500,
        "longTermDebt": 500,
        "totalDebt": 1000,
        "totalAssets": 2000,
        "deferredRevenue": 5,
    }
]

BALANCE_SHEET_QUARTERLY = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "totalCurrentAssets": 500,
        "totalCurrentLiabilities": 400,
        "shortTermDebt": 50,
        "longTermDebt": 150,
        "totalDebt": 200,
        "totalAssets": 1000,
        "deferredRevenue": 20,
    }
]

# 4 quarters with distinct ebitda/netInterestIncome values so a bug that
# uses only the single most recent quarter (rather than summing all 4)
# produces a detectably different, wrong result.
INCOME_QUARTERLY = [
    {"date": "2026-03-28", "ebitda": 100, "netInterestIncome": -10},
    {"date": "2025-12-27", "ebitda": 90, "netInterestIncome": -10},
    {"date": "2025-09-27", "ebitda": 80, "netInterestIncome": -10},
    {"date": "2025-06-28", "ebitda": 70, "netInterestIncome": -10},
]

CASH_FLOW_QUARTERLY = [{"date": "2026-03-28", "netCashProvidedByOperatingActivities": 50} for _ in range(4)]


def _patch_fmp(monkeypatch, sector="Technology", industry="Consumer Electronics", income_quarterly=None):
    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY if period == "quarter" else BALANCE_SHEET_ANNUAL

    async def fake_income_statement(ticker, period, limit):
        return income_quarterly if income_quarterly is not None else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step5_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step5_data, "engine", test_engine)


def test_uses_quarterly_balance_sheet_not_annual(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step5_data("aapl"))

    # 500/400 = 1.25 (acceptable) -- not the annual fixture's 100/1000 = 0.1
    # (which would hard-fail).
    assert result.ratios["current_ratio"].value == 1.25
    assert result.ratios["current_ratio"].label == "acceptable"
    assert result.hard_fail is False


def test_ebitda_and_net_interest_expense_are_ttm_summed(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step5_data("aapl"))

    # debt = 50 + 150 = 200; ebitda TTM = 100+90+80+70 = 340 -- not just the
    # latest quarter's 100, which would understate the denominator ~3.4x.
    assert result.ratios["debt_to_ebitda"].value == 200 / 340
    assert result.ratios["debt_to_ebitda"].label == "excellent"

    # net interest expense TTM = -(-10*4) = 40; CFO TTM = 50*4 = 200 ->
    # 40/200*100 = 20% -- not a single quarter's 10/50*100 = 20% (same in
    # this fixture by design of equal quarters, so this test also pins the
    # exact score/tier which would shift if only 1 quarter were summed
    # incorrectly, e.g. 3 quarters).
    assert result.ratios["debt_servicing_ratio"].value == 20.0
    assert result.ratios["debt_servicing_ratio"].label == "approaching_limit"


def test_insufficient_data_when_fewer_than_four_quarters_available(monkeypatch):
    _fresh_engine(monkeypatch)
    # Only 3 quarters -- sum_last_four_quarters requires 4 non-null values,
    # so ebitda_ttm is None and the ticker should read as insufficient data
    # rather than silently summing a partial year.
    _patch_fmp(monkeypatch, income_quarterly=INCOME_QUARTERLY[:3])

    result = asyncio.run(get_step5_data("aapl"))

    assert result.verdict == "insufficient_data"
    assert result.score is None
    assert result.ratios == {}


def test_bank_still_short_circuits_before_any_balance_sheet_fetch(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step5_data("jpm"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.score is None
