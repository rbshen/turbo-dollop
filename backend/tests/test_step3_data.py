import asyncio

import httpx
from sqlmodel import SQLModel, create_engine

import step3_data
from step3_data import get_step3_data

PROFILE = [{"sector": "Technology", "industry": "Software - Application", "beta": 1.1}]
QUOTE = [{"price": 100.0, "marketCap": 10_000_000_000}]

# Chronological (oldest -> recent), all real, genuinely declining -- always
# positive in the annual filings, but TTM Net Income turns recently negative
# and TTM CFO/Revenue keep declining, so every check that runs against this
# data reads as a real, computed "doesn't qualify" (classify_trend
# "declining", or a recent non-positive value), never a data gap.
INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 300, "netIncome": 10},
    {"fiscalYear": "2024", "revenue": 350, "netIncome": 20},
    {"fiscalYear": "2023", "revenue": 400, "netIncome": 30},
    {"fiscalYear": "2022", "revenue": 450, "netIncome": 40},
    {"fiscalYear": "2021", "revenue": 500, "netIncome": 50},
]
INCOME_QUARTERLY = [{"date": "2026-03-31", "revenue": 70, "netIncome": -5} for _ in range(4)]

CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 40, "capitalExpenditure": -10},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 45, "capitalExpenditure": -10},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 50, "capitalExpenditure": -10},
    {"fiscalYear": "2022", "netCashProvidedByOperatingActivities": 55, "capitalExpenditure": -10},
    {"fiscalYear": "2021", "netCashProvidedByOperatingActivities": 60, "capitalExpenditure": -10},
]
CASH_FLOW_QUARTERLY = [{"netCashProvidedByOperatingActivities": 8.75, "capitalExpenditure": -2.5} for _ in range(4)]

BALANCE_SHEET_QUARTERLY = [{"cashAndCashEquivalents": 100, "totalDebt": 0}]
RATIOS_ANNUAL: list[dict] = []


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step3_data, "engine", test_engine)
    # get_step3_data also calls get_step2_data internally (for growth_yr_1_5)
    # -- it goes through its own module's engine, patch that too so it
    # doesn't touch a real DB file.
    import step2_data

    monkeypatch.setattr(step2_data, "engine", test_engine)
    return test_engine


def _patch_real_data(monkeypatch):
    async def fake_profile(ticker):
        return PROFILE

    async def fake_quote(ticker):
        return QUOTE

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_ANNUAL if period == "annual" else CASH_FLOW_QUARTERLY

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY

    async def fake_ratios(ticker, period, limit):
        return RATIOS_ANNUAL

    async def fake_analyst_estimates(ticker):
        return []

    monkeypatch.setattr(step3_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step3_data.fmp_client, "get_quote", fake_quote)
    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(step3_data.fmp_client, "get_analyst_estimates", fake_analyst_estimates)


def test_insufficient_data_flagged_on_total_fetch_failure(monkeypatch):
    # Every fetch step3_data.py depends on fails -- a genuine FMP outage.
    # Must land on selected_method="PASS" with insufficient_data=True, never
    # a fabricated numeric valuation.
    _fresh_engine(monkeypatch)

    async def raise_error(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step3_data.fmp_client, "get_profile", raise_error)
    monkeypatch.setattr(step3_data.fmp_client, "get_quote", raise_error)
    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", raise_error)
    monkeypatch.setattr(step3_data.fmp_client, "get_cash_flow_statement", raise_error)
    monkeypatch.setattr(step3_data.fmp_client, "get_balance_sheet_statement", raise_error)
    monkeypatch.setattr(step3_data.fmp_client, "get_ratios", raise_error)
    monkeypatch.setattr(step3_data.fmp_client, "get_analyst_estimates", raise_error)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.selected_method == "PASS"
    assert result.insufficient_data is True
    assert result.intrinsic_value_per_share is None
    assert result.discount_premium_pct is None


def test_insufficient_data_flagged_on_partial_fetch_failure(monkeypatch):
    # Only cash_flow_statement fails -- income statement / revenue are real
    # and genuinely declining (a real, non-gap "doesn't qualify" read for
    # Net Income/Revenue). Must still land on insufficient_data=True (caused
    # by the CFO check alone), while the trail keeps Net Income/Revenue's
    # own real, computed False readings distinguishable from CFO's None.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def raise_error(ticker, period, limit):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step3_data.fmp_client, "get_cash_flow_statement", raise_error)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.selected_method == "PASS"
    assert result.insufficient_data is True
    assert result.intrinsic_value_per_share is None
    assert result.discount_premium_pct is None

    steps_by_id = {s.step: s for s in result.method_reasoning}
    # CFO couldn't be evaluated at all -- a genuine data gap.
    assert steps_by_id["2"].passed is None
    # Net Income/Revenue DID have real data and were genuinely evaluated --
    # real False, not None, confirming the trail still distinguishes which
    # check had the gap.
    assert steps_by_id["4"].passed is False
    assert steps_by_id["5"].passed is False


def test_pass_with_real_data_is_not_flagged_as_insufficient(monkeypatch):
    # Same realistic declining-company fixture, but with cash flow data also
    # real (not failed) -- a genuine no-method-fits case must never be
    # misflagged as insufficient_data.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.selected_method == "PASS"
    assert result.insufficient_data is False
    assert result.pass_reason == "No valuation method in the tree applies to this company's data."
    assert result.intrinsic_value_per_share is None
    assert result.discount_premium_pct is None

    steps_by_id = {s.step: s for s in result.method_reasoning}
    assert steps_by_id["2"].passed is False
    assert steps_by_id["4"].passed is False
    assert steps_by_id["5"].passed is False
