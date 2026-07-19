import asyncio

from sqlmodel import SQLModel, create_engine

import step4_data
from step4_data import get_step4_data

# Revenue/AR both compound at 10%/yr so Metric 3 reads "healthy" (0 gap) in
# the baseline fixture -- tests that care about AR outpacing override AR
# explicitly rather than fighting this baseline.
INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 146.41, "netIncome": 20.0, "costOfRevenue": 87.846},
    {"fiscalYear": "2024", "revenue": 133.1, "netIncome": 18.0, "costOfRevenue": 79.86},
    {"fiscalYear": "2023", "revenue": 121.0, "netIncome": 16.0, "costOfRevenue": 72.6},
    {"fiscalYear": "2022", "revenue": 110.0, "netIncome": 14.0, "costOfRevenue": 66.0},
    {"fiscalYear": "2021", "revenue": 100.0, "netIncome": 12.0, "costOfRevenue": 60.0},
]

INCOME_QUARTERLY = [
    {"date": "2026-03-28", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
    {"date": "2025-12-27", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
    {"date": "2025-09-27", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
    {"date": "2025-06-28", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
]

BALANCE_SHEET_ANNUAL = [
    {
        "fiscalYear": "2025",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 73.205,
        "inventory": 29.28,
        "accountPayables": 43.923,
    },
    {
        "fiscalYear": "2024",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 66.55,
        "inventory": 26.62,
        "accountPayables": 39.93,
    },
    {
        "fiscalYear": "2023",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 60.5,
        "inventory": 24.2,
        "accountPayables": 36.3,
    },
    {
        "fiscalYear": "2022",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 55.0,
        "inventory": 22.0,
        "accountPayables": 33.0,
    },
    {
        "fiscalYear": "2021",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 50.0,
        "inventory": 20.0,
        "accountPayables": 30.0,
    },
]

BALANCE_SHEET_QUARTERLY = [
    {
        "date": "2026-03-28",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 80.5255,
        "inventory": 30.0,
        "accountPayables": 46.0,
    }
]

KEY_METRICS_ANNUAL = [
    {"fiscalYear": "2025", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2024", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2023", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2022", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2021", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
]

KEY_METRICS_TTM = [{"returnOnEquityTTM": 0.20, "returnOnInvestedCapitalTTM": 0.18}]


def _patch_fmp(
    monkeypatch,
    sector="Technology",
    industry="Consumer Electronics",
    balance_sheet_annual=None,
    key_metrics_annual=None,
):
    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_balance_sheet_statement(ticker, period, limit):
        if period == "annual":
            return balance_sheet_annual if balance_sheet_annual is not None else BALANCE_SHEET_ANNUAL
        return BALANCE_SHEET_QUARTERLY

    async def fake_key_metrics(ticker, period, limit):
        return key_metrics_annual if key_metrics_annual is not None else KEY_METRICS_ANNUAL

    async def fake_key_metrics_ttm(ticker):
        return KEY_METRICS_TTM

    monkeypatch.setattr(step4_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step4_data, "engine", test_engine)


def test_standard_company_full_pipeline(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.company_type == "Standard"
    assert result.years == ["2021", "2022", "2023", "2024", "2025", "TTM"]
    # returnOnEquity 0.20 -> 20% (fraction converted to percent)
    assert result.roe[0] == 20.0
    assert result.roic is not None
    assert result.roic[0] == 18.0
    assert result.ccc is not None
    assert len(result.ccc) == 6
    assert result.score is not None
    assert result.hard_fail is False
    assert result.components["roic"] is not None


def test_roic_exempt_for_bank(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step4_data("jpm"))

    assert result.company_type == "Bank"
    assert result.roic is None
    assert result.roic_exempt_reason is not None
    assert "Bank" in result.roic_exempt_reason
    assert result.components["roic"] is None


def test_ccc_exempt_when_no_inventory_across_window(monkeypatch):
    _fresh_engine(monkeypatch)
    no_inventory_annual = [{**row, "inventory": 0} for row in BALANCE_SHEET_ANNUAL]
    no_inventory_quarterly = [{**BALANCE_SHEET_QUARTERLY[0], "inventory": 0}]
    _patch_fmp(monkeypatch, balance_sheet_annual=no_inventory_annual)

    # Latest-quarter snapshot must also read as no-inventory for the
    # exemption to hold across "the recent reporting window", not just the
    # annual history.
    async def fake_balance_sheet_statement(ticker, period, limit):
        return no_inventory_annual if period == "annual" else no_inventory_quarterly

    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step4_data("crm"))

    assert result.ccc is None
    assert result.ccc_exempt_reason is not None
    assert result.components["ccc"] is None


def test_ccc_exemption_survives_a_noisy_latest_quarter_inventory_figure(monkeypatch):
    # Real-world finding (MA, NOW): FMP's latest-quarter inventory can be a
    # nonzero/negative data artifact even when all 5 annual filings show a
    # clean 0 -- the exemption must be driven by the stable annual history,
    # not a single noisy quarter.
    _fresh_engine(monkeypatch)
    no_inventory_annual = [{**row, "inventory": 0} for row in BALANCE_SHEET_ANNUAL]
    noisy_quarterly = [{**BALANCE_SHEET_QUARTERLY[0], "inventory": -28_000_000}]
    _patch_fmp(monkeypatch, balance_sheet_annual=no_inventory_annual)

    async def fake_balance_sheet_statement(ticker, period, limit):
        return no_inventory_annual if period == "annual" else noisy_quarterly

    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step4_data("now"))

    assert result.ccc is None
    assert result.ccc_exempt_reason is not None


def test_hard_fail_from_persistently_poor_roe(monkeypatch):
    _fresh_engine(monkeypatch)
    poor_roe_metrics = [{**row, "returnOnEquity": 0.03, "returnOnInvestedCapital": 0.03} for row in KEY_METRICS_ANNUAL]
    _patch_fmp(monkeypatch, key_metrics_annual=poor_roe_metrics)

    async def fake_key_metrics_ttm(ticker):
        return [{"returnOnEquityTTM": 0.03, "returnOnInvestedCapitalTTM": 0.03}]

    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.hard_fail is True
    assert result.verdict == "Fail"


def test_insufficient_data_when_no_annual_history(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, balance_sheet_annual=[])

    async def fake_income_statement(ticker, period, limit):
        return []

    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.verdict == "insufficient_data"
    assert result.score is None
