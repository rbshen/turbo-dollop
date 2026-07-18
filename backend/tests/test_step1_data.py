import asyncio

from sqlmodel import SQLModel, create_engine

import step1_data
from step1_data import get_step1_data

PROFILE = [{"sector": "Technology", "industry": "Consumer Electronics"}]

INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 300, "grossProfit": 150, "operatingIncome": 100, "netIncome": 80},
    {"fiscalYear": "2024", "revenue": 250, "grossProfit": 120, "operatingIncome": 80, "netIncome": 60},
    {"fiscalYear": "2023", "revenue": 200, "grossProfit": 100, "operatingIncome": 60, "netIncome": 40},
]

INCOME_QUARTERLY = [
    {"date": "2026-03-31", "revenue": 80, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-12-31", "revenue": 80, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-09-30", "revenue": 80, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-06-30", "revenue": 80, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
]

CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 90},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 70},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 50},
]

CASH_FLOW_QUARTERLY = [{"netCashProvidedByOperatingActivities": 24} for _ in range(4)]


def _patch_fmp(monkeypatch, call_count, sector="Technology", industry="Consumer Electronics"):
    async def fake_profile(ticker):
        call_count["profile"] += 1
        return [{"sector": sector, "industry": industry}]

    async def fake_income_statement(ticker, period, limit):
        call_count[f"income_{period}"] += 1
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        call_count[f"cash_flow_{period}"] += 1
        return CASH_FLOW_ANNUAL if period == "annual" else CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)


def test_get_step1_data_builds_series_and_ttm_and_caches(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
    _patch_fmp(monkeypatch, call_count)

    result = asyncio.run(get_step1_data("aapl"))

    assert result.ticker == "AAPL"
    assert result.years == ["2023", "2024", "2025", "TTM"]
    assert result.revenue == [200, 250, 300, 320]
    assert result.net_income == [40, 60, 80, 84]
    assert result.cfo == [50, 70, 90, 96]
    assert result.gross_margin[0] == 50.0
    assert result.cfo_exempt_reason is None
    assert result.components["cfo"] is not None
    assert 0 <= result.score <= 100
    assert result.verdict in {"Strong Pass", "Pass with caution", "May not pass — investigate", "Fail"}
    assert call_count == {
        "profile": 1,
        "income_annual": 1,
        "income_quarter": 1,
        "cash_flow_annual": 1,
        "cash_flow_quarter": 1,
    }

    # Second call within the staleness window should hit the cache, not FMP again.
    asyncio.run(get_step1_data("aapl"))
    assert call_count == {
        "profile": 1,
        "income_annual": 1,
        "income_quarter": 1,
        "cash_flow_annual": 1,
        "cash_flow_quarter": 1,
    }


def test_bank_is_cfo_exempt(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
    _patch_fmp(monkeypatch, call_count, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step1_data("jpm"))

    assert result.cfo_exempt_reason == "Bank"
    assert result.cfo is None
    assert result.components["cfo"] is None
