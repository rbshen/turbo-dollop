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

# No usable NPL tags -- the default for every non-Bank test and any Bank
# test that isn't specifically exercising the NPL computation.
FULL_AS_REPORTED_QUARTERLY_MISSING = [{"date": "2026-03-28", "period": "Q2", "data": {}}]

# total_loans (400) is 40% of BALANCE_SHEET_QUARTERLY's totalAssets (1000)
# -- well above the plausibility floor, so this reads as a trustworthy tag
# pair. nonaccrual 8 / total_loans 400 * 100 = 2% ("good" tier).
FULL_AS_REPORTED_QUARTERLY_GOOD = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "data": {
            "financingreceivableexcludingaccruedinterestnonaccrual": 8,
            "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 400,
        },
    }
]

# total_loans (50) is only 5% of totalAssets (1000) -- below the 10% floor,
# same failure mode confirmed during investigation for BAC/WFC (the tag
# resolves to a mis-scoped disclosure-table value, not the true total loan
# book).
FULL_AS_REPORTED_QUARTERLY_IMPLAUSIBLE = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "data": {
            "financingreceivableexcludingaccruedinterestnonaccrual": 2,
            "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 50,
        },
    }
]


def _patch_fmp(
    monkeypatch,
    sector="Technology",
    industry="Consumer Electronics",
    income_quarterly=None,
    full_as_reported=None,
):
    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY if period == "quarter" else BALANCE_SHEET_ANNUAL

    async def fake_income_statement(ticker, period, limit):
        return income_quarterly if income_quarterly is not None else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_QUARTERLY

    async def fake_full_as_reported(ticker, period, limit):
        return full_as_reported if full_as_reported is not None else FULL_AS_REPORTED_QUARTERLY_MISSING

    monkeypatch.setattr(step5_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_financial_statement_full_as_reported", fake_full_as_reported)


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


def test_bank_overall_verdict_stays_not_supported_regardless_of_npl(monkeypatch):
    # CET1 is still unavailable -- NPL is a partial signal only, must never
    # by itself produce a scored Bank verdict.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported=FULL_AS_REPORTED_QUARTERLY_GOOD,
    )

    result = asyncio.run(get_step5_data("jpm"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.score is None


def test_bank_npl_ratio_computed_when_tags_present_and_plausible(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported=FULL_AS_REPORTED_QUARTERLY_GOOD,
    )

    result = asyncio.run(get_step5_data("jpm"))

    assert result.ratios["npl_ratio"].value == 2.0  # 8 / 400 * 100
    assert result.ratios["npl_ratio"].label == "good"


def test_bank_npl_ratio_unavailable_when_total_loans_implausibly_small(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported=FULL_AS_REPORTED_QUARTERLY_IMPLAUSIBLE,
    )

    result = asyncio.run(get_step5_data("bac"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.ratios == {}


def test_bank_npl_ratio_unavailable_when_tags_missing(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step5_data("gs"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.ratios == {}
