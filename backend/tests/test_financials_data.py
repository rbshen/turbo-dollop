import asyncio

from sqlmodel import SQLModel, create_engine

import financials_data
from financials_data import (
    ANNUAL_WINDOW,
    BALANCE_SHEET_GROUPS,
    CASH_FLOW_GROUPS,
    INCOME_STATEMENT_FIELDS,
    get_financials_data,
)
from ttm import TOTAL_QUARTERS_NEEDED

FAKE_INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 400_000_000_000, "netIncome": 100_000_000_000, "eps": 7.0, "epsDiluted": 6.9},
    {"fiscalYear": "2024", "revenue": 380_000_000_000, "netIncome": 95_000_000_000, "eps": 6.5, "epsDiluted": 6.4},
]

# Most-recent-first (FMP's own ordering), as sum_last_four_quarters requires.
FAKE_INCOME_QUARTERLY = [
    {
        "period": "Q2",
        "fiscalYear": "2026",
        "revenue": 110_000_000_000,
        "netIncome": 28_000_000_000,
        "eps": 1.9,
        "epsDiluted": 1.85,
        "weightedAverageShsOut": 14_900_000_000,
    },
    {
        "period": "Q1",
        "fiscalYear": "2026",
        "revenue": 105_000_000_000,
        "netIncome": 26_000_000_000,
        "eps": 1.8,
        "epsDiluted": 1.75,
        "weightedAverageShsOut": 15_000_000_000,
    },
    {
        "period": "Q4",
        "fiscalYear": "2025",
        "revenue": 120_000_000_000,
        "netIncome": 32_000_000_000,
        "eps": 2.1,
        "epsDiluted": 2.05,
        "weightedAverageShsOut": 15_100_000_000,
    },
    {
        "period": "Q3",
        "fiscalYear": "2025",
        "revenue": 90_000_000_000,
        "netIncome": 20_000_000_000,
        "eps": 1.4,
        "epsDiluted": 1.35,
        "weightedAverageShsOut": 15_200_000_000,
    },
]

FAKE_BALANCE_SHEET_ANNUAL = [
    {"fiscalYear": "2025", "totalAssets": 350_000_000_000, "totalLiabilities": 280_000_000_000},
    {"fiscalYear": "2024", "totalAssets": 330_000_000_000, "totalLiabilities": 270_000_000_000},
]

FAKE_BALANCE_SHEET_QUARTERLY = [
    {"period": "Q2", "fiscalYear": "2026", "totalAssets": 360_000_000_000, "totalLiabilities": 285_000_000_000},
    {"period": "Q1", "fiscalYear": "2026", "totalAssets": 355_000_000_000, "totalLiabilities": 282_000_000_000},
]

FAKE_CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 110_000_000_000, "freeCashFlow": 98_000_000_000},
]

FAKE_CASH_FLOW_QUARTERLY = [
    {"period": "Q2", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 30_000_000_000, "freeCashFlow": 26_000_000_000},
    {"period": "Q1", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 28_000_000_000, "freeCashFlow": 24_000_000_000},
    {"period": "Q4", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 32_000_000_000, "freeCashFlow": 28_000_000_000},
    {"period": "Q3", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 20_000_000_000, "freeCashFlow": 20_000_000_000},
]


def test_income_statement_annual_ttm_is_summed_from_quarters():
    period = financials_data._annual_period(
        FAKE_INCOME_ANNUAL, FAKE_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)], ttm_mode="sum"
    )
    assert len(period.periods) == ANNUAL_WINDOW + 1
    assert period.periods[-1] == "TTM"
    # Padded years read "—", then the 2 real fiscal years, then "TTM".
    assert period.periods[-3:] == ["2024", "2025", "TTM"]

    assert len(period.groups) == 1
    group = period.groups[0]
    assert group.label is None

    revenue_row = next(item for item in group.items if item.label == "Revenue")
    ttm_revenue = 110_000_000_000 + 105_000_000_000 + 120_000_000_000 + 90_000_000_000
    assert revenue_row.values[-1] == ttm_revenue
    assert revenue_row.values[-3:-1] == [380_000_000_000, 400_000_000_000]
    assert revenue_row.unit == "money"

    eps_row = next(item for item in group.items if item.label == "EPS (Basic)")
    assert eps_row.unit == "per_share"


def test_income_statement_field_order_and_emphasis_matches_spec():
    period = financials_data._annual_period(
        FAKE_INCOME_ANNUAL, FAKE_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)], ttm_mode="sum"
    )
    labels = [item.label for item in period.groups[0].items]
    assert labels == [spec[0] for spec in INCOME_STATEMENT_FIELDS]

    net_income_row = next(item for item in period.groups[0].items if item.label == "Net Income")
    assert net_income_row.emphasis is True
    revenue_row = next(item for item in period.groups[0].items if item.label == "Revenue")
    assert revenue_row.emphasis is False


def test_balance_sheet_annual_ttm_is_latest_quarter_not_summed():
    period = financials_data._annual_period(
        FAKE_BALANCE_SHEET_ANNUAL, FAKE_BALANCE_SHEET_QUARTERLY, BALANCE_SHEET_GROUPS, ttm_mode="latest"
    )
    assert period.periods[-1] == "TTM"

    assets_group = next(g for g in period.groups if g.label == "Assets")
    total_assets_row = next(item for item in assets_group.items if item.label == "Total Assets")
    # Latest quarter's raw snapshot, NOT the sum of quarterly figures.
    assert total_assets_row.values[-1] == 360_000_000_000


def test_balance_sheet_groups_match_spec():
    period = financials_data._annual_period(
        FAKE_BALANCE_SHEET_ANNUAL, FAKE_BALANCE_SHEET_QUARTERLY, BALANCE_SHEET_GROUPS, ttm_mode="latest"
    )
    assert [g.label for g in period.groups] == ["Assets", "Liabilities", "Equity", "Supplemental"]


def test_cash_flow_annual_ttm_is_summed_from_quarters():
    period = financials_data._annual_period(
        FAKE_CASH_FLOW_ANNUAL, FAKE_CASH_FLOW_QUARTERLY, CASH_FLOW_GROUPS, ttm_mode="sum"
    )
    operating_group = next(g for g in period.groups if g.label == "Operating")
    cfo_row = next(item for item in operating_group.items if item.label == "Net Cash from Operating Activities")
    expected_ttm = 30_000_000_000 + 28_000_000_000 + 32_000_000_000 + 20_000_000_000
    assert cfo_row.values[-1] == expected_ttm
    assert cfo_row.emphasis is True


def test_annual_ttm_label_includes_latest_quarter_date_when_available():
    dated_quarterly = [{**row, "date": "2026-06-30"} for row in FAKE_INCOME_QUARTERLY]
    period = financials_data._annual_period(
        FAKE_INCOME_ANNUAL, dated_quarterly, [(None, INCOME_STATEMENT_FIELDS)], ttm_mode="sum"
    )
    assert period.periods[-1] == "TTM (2026-06-30)"


def test_quarterly_period_has_no_ttm_column():
    period = financials_data._quarterly_period(FAKE_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)])
    assert len(period.periods) == TOTAL_QUARTERS_NEEDED
    assert "TTM" not in period.periods
    # Real quarters read oldest-to-newest, labeled "Q# YYYY".
    assert period.periods[-2:] == ["Q1 2026", "Q2 2026"]


def test_missing_field_degrades_to_none_not_crash():
    sparse_annual = [{"fiscalYear": "2025"}]  # no revenue/netIncome/eps at all
    period = financials_data._annual_period(
        sparse_annual, FAKE_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)], ttm_mode="sum"
    )
    revenue_row = next(item for item in period.groups[0].items if item.label == "Revenue")
    assert revenue_row.values[-2] is None  # the 2025 annual row, revenue missing


def test_full_field_list_row_counts():
    # Guards against silent drift in the "show every real line item" lists.
    assert len(INCOME_STATEMENT_FIELDS) == 31
    assert sum(len(fields) for _, fields in BALANCE_SHEET_GROUPS) == 53
    assert sum(len(fields) for _, fields in CASH_FLOW_GROUPS) == 37


def test_duplicate_alias_fields_excluded():
    # operatingCashFlow/investmentsInPropertyPlantAndEquipment are literal
    # duplicate aliases of netCashProvidedByOperatingActivities/
    # capitalExpenditure (confirmed identical across 5 real tickers) --
    # must never appear as their own row.
    cash_flow_keys = {key for _, fields in CASH_FLOW_GROUPS for _, key, _, _ in fields}
    assert "operatingCashFlow" not in cash_flow_keys
    assert "investmentsInPropertyPlantAndEquipment" not in cash_flow_keys
    assert "netCashProvidedByOperatingActivities" in cash_flow_keys
    assert "capitalExpenditure" in cash_flow_keys


def test_weighted_average_shares_ttm_is_latest_quarter_not_summed():
    period = financials_data._annual_period(
        FAKE_INCOME_ANNUAL, FAKE_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)], ttm_mode="sum"
    )
    shares_row = next(
        item for item in period.groups[0].items if item.label == "Weighted Avg Shares Outstanding (Basic, millions)"
    )
    assert shares_row.unit == "shares"
    # Latest quarter's own value (14.9B), NOT the sum of all 4 quarters
    # (which would be ~60.2B -- a meaningless inflated share count).
    assert shares_row.values[-1] == 14_900_000_000


def test_get_financials_data_end_to_end(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(financials_data, "engine", test_engine)

    call_count = {"income": 0, "cash_flow": 0, "balance_sheet": 0}

    async def fake_income_statement(ticker, period, limit):
        call_count["income"] += 1
        return FAKE_INCOME_QUARTERLY if period == "quarter" else FAKE_INCOME_ANNUAL

    async def fake_cash_flow_statement(ticker, period, limit):
        call_count["cash_flow"] += 1
        return FAKE_CASH_FLOW_QUARTERLY if period == "quarter" else FAKE_CASH_FLOW_ANNUAL

    async def fake_balance_sheet_statement(ticker, period, limit):
        call_count["balance_sheet"] += 1
        return FAKE_BALANCE_SHEET_QUARTERLY if period == "quarter" else FAKE_BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(financials_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_financials_data("aapl"))

    assert result.ticker == "AAPL"
    assert result.income_statement.annual.periods[-1] == "TTM"
    assert result.income_statement.quarterly.periods[-1] == "Q2 2026"
    assert result.balance_sheet.annual.periods[-1] == "TTM"
    assert result.cash_flow.annual.periods[-1] == "TTM"
    # income + cash_flow each fetched twice (annual + quarterly); balance
    # sheet also twice.
    assert call_count == {"income": 2, "cash_flow": 2, "balance_sheet": 2}

    # Second call within the staleness window should hit the cache, not FMP again.
    asyncio.run(get_financials_data("aapl"))
    assert call_count == {"income": 2, "cash_flow": 2, "balance_sheet": 2}
