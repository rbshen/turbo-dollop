import asyncio

from sqlmodel import SQLModel, create_engine

import data.financials_data as financials_data
from data.financials_data import (
    ANNUAL_WINDOW,
    BALANCE_SHEET_GROUPS,
    CASH_FLOW_GROUPS,
    INCOME_STATEMENT_FIELDS,
    get_financials_data,
)
from helpers.ttm import TOTAL_QUARTERS_NEEDED

FAKE_INCOME_ANNUAL = [
    {
        "fiscalYear": "2025",
        "date": "2025-12-31",
        "revenue": 400_000_000_000,
        "netIncome": 100_000_000_000,
        "eps": 7.0,
        "epsDiluted": 6.9,
    },
    {
        "fiscalYear": "2024",
        "date": "2024-12-31",
        "revenue": 380_000_000_000,
        "netIncome": 95_000_000_000,
        "eps": 6.5,
        "epsDiluted": 6.4,
    },
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
    {"fiscalYear": "2025", "date": "2025-12-31", "totalAssets": 350_000_000_000, "totalLiabilities": 280_000_000_000},
    {"fiscalYear": "2024", "date": "2024-12-31", "totalAssets": 330_000_000_000, "totalLiabilities": 270_000_000_000},
]

FAKE_BALANCE_SHEET_QUARTERLY = [
    {"period": "Q2", "fiscalYear": "2026", "totalAssets": 360_000_000_000, "totalLiabilities": 285_000_000_000},
    {"period": "Q1", "fiscalYear": "2026", "totalAssets": 355_000_000_000, "totalLiabilities": 282_000_000_000},
]

FAKE_CASH_FLOW_ANNUAL = [
    {
        "fiscalYear": "2025",
        "date": "2025-12-31",
        "netCashProvidedByOperatingActivities": 110_000_000_000,
        "freeCashFlow": 98_000_000_000,
    },
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
    # Padded years read "—", then the 2 real fiscal year-end dates, then "TTM".
    assert period.periods[-3:] == ["2024-12-31", "2025-12-31", "TTM"]

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


# TEAM's actual Q4 FY2026 shape (2026-08-16 investigation): the latest
# quarter's weightedAverageShsOut(Dil) reads ~1000x too small, while every
# prior quarter is normal. FLY hits the identical shape independently, so
# this is a general FMP-pipeline defect class, not a TEAM-only fixture.
TEAM_SHAPED_INCOME_QUARTERLY = [
    {
        "period": "Q4",
        "fiscalYear": "2026",
        "revenue": 6_572_308_000,
        "netIncome": -53_828_000,
        "eps": -0.21,
        "epsDiluted": -0.21,
        "weightedAverageShsOut": 260_163,
        "weightedAverageShsOutDil": 260_163,
    },
    {
        "period": "Q3",
        "fiscalYear": "2026",
        "revenue": 1_786_971_000,
        "netIncome": -98_389_000,
        "eps": -0.38,
        "epsDiluted": -0.38,
        "weightedAverageShsOut": 260_964_999,
        "weightedAverageShsOutDil": 260_964_999,
    },
    {
        "period": "Q2",
        "fiscalYear": "2026",
        "revenue": 1_586_315_000,
        "netIncome": -42_645_000,
        "eps": -0.16,
        "epsDiluted": -0.16,
        "weightedAverageShsOut": 263_409_000,
        "weightedAverageShsOutDil": 263_409_000,
    },
    {
        "period": "Q1",
        "fiscalYear": "2026",
        "revenue": 1_432_553_000,
        "netIncome": -51_870_000,
        "eps": -0.20,
        "epsDiluted": -0.20,
        "weightedAverageShsOut": 262_991_000,
        "weightedAverageShsOutDil": 262_991_000,
    },
]


def test_implausible_shares_magnitude_shift_is_suppressed_team_shaped():
    sanitized = financials_data._sanitize_shares_magnitude(
        TEAM_SHAPED_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)]
    )
    assert sanitized[0]["weightedAverageShsOut"] is None
    assert sanitized[0]["weightedAverageShsOutDil"] is None
    # Every other field on the latest quarter is untouched.
    assert sanitized[0]["revenue"] == 6_572_308_000
    # Prior quarters are untouched.
    assert sanitized[1]["weightedAverageShsOutDil"] == 260_964_999


def test_implausible_shares_magnitude_shift_suppressed_in_quarterly_view():
    period = financials_data._quarterly_period(TEAM_SHAPED_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)])
    shares_row = next(
        item for item in period.groups[0].items if item.label == "Weighted Avg Shares Outstanding (Diluted, millions)"
    )
    # _quarterly_period is called directly here (bypassing get_financials_data's
    # own sanitize call), so this confirms _sanitize_shares_magnitude must be
    # applied upstream for the quarterly table to actually be protected --
    # get_financials_data's end-to-end test below confirms that wiring.
    assert shares_row.values[-1] == 260_163


def test_implausible_shares_magnitude_shift_suppressed_in_ttm_column():
    sanitized = financials_data._sanitize_shares_magnitude(
        TEAM_SHAPED_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)]
    )
    period = financials_data._annual_period(
        FAKE_INCOME_ANNUAL, sanitized, [(None, INCOME_STATEMENT_FIELDS)], ttm_mode="sum"
    )
    shares_row = next(
        item for item in period.groups[0].items if item.label == "Weighted Avg Shares Outstanding (Diluted, millions)"
    )
    assert shares_row.values[-1] is None


def test_normal_quarter_to_quarter_drift_is_not_sanitized():
    # FAKE_INCOME_QUARTERLY's own shares drift (14.9B vs 15.0B) is ordinary
    # -- must survive sanitization untouched.
    sanitized = financials_data._sanitize_shares_magnitude(FAKE_INCOME_QUARTERLY, [(None, INCOME_STATEMENT_FIELDS)])
    assert sanitized[0]["weightedAverageShsOut"] == 14_900_000_000


def test_sanitize_shares_magnitude_noop_with_fewer_than_two_quarters():
    single = [TEAM_SHAPED_INCOME_QUARTERLY[0]]
    sanitized = financials_data._sanitize_shares_magnitude(single, [(None, INCOME_STATEMENT_FIELDS)])
    assert sanitized == single


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


def test_get_financials_data_end_to_end_team_shaped_magnitude_defect_suppressed(monkeypatch):
    # Confirms get_financials_data actually wires _sanitize_shares_magnitude
    # in -- both the quarterly table and the TTM column must be protected,
    # not just the pure helper functions tested above in isolation.
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(financials_data, "engine", test_engine)

    async def fake_income_statement(ticker, period, limit):
        return TEAM_SHAPED_INCOME_QUARTERLY if period == "quarter" else FAKE_INCOME_ANNUAL

    async def fake_cash_flow_statement(ticker, period, limit):
        return FAKE_CASH_FLOW_QUARTERLY if period == "quarter" else FAKE_CASH_FLOW_ANNUAL

    async def fake_balance_sheet_statement(ticker, period, limit):
        return FAKE_BALANCE_SHEET_QUARTERLY if period == "quarter" else FAKE_BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(financials_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_financials_data("team"))

    quarterly_shares_row = next(
        item
        for item in result.income_statement.quarterly.groups[0].items
        if item.label == "Weighted Avg Shares Outstanding (Diluted, millions)"
    )
    assert quarterly_shares_row.values[-1] is None

    ttm_shares_row = next(
        item
        for item in result.income_statement.annual.groups[0].items
        if item.label == "Weighted Avg Shares Outstanding (Diluted, millions)"
    )
    assert ttm_shares_row.values[-1] is None

    # Revenue (a "money"-unit field) is untouched -- this guard is scoped
    # to "shares"-unit fields only, Defect B (the duplicate-annual-revenue
    # issue) is a separate fix.
    revenue_row = next(item for item in result.income_statement.quarterly.groups[0].items if item.label == "Revenue")
    assert revenue_row.values[-1] == 6_572_308_000


# TEAM's real FY2026 annual row -- fiscalYear "2026" matches
# TEAM_SHAPED_INCOME_QUARTERLY's Q4 above, so this actually exercises
# Defect B's duplicate-annual-quarter correction (FAKE_INCOME_ANNUAL above
# only goes up to fiscalYear "2025", so the earlier test's revenue_row
# assertion never triggers this correction at all).
TEAM_INCOME_ANNUAL_FY2026 = [
    {"fiscalYear": "2026", "date": "2026-06-30", "revenue": 6_572_308_000, "netIncome": -53_828_000},
]


def test_get_financials_data_end_to_end_team_shaped_duplicate_annual_quarter_corrected(monkeypatch):
    # Confirms get_financials_data wires the Defect B correction into the
    # TTM column via _ttm_row_summed(..., annual_rows) -- the raw per-quarter
    # columns stay untouched (see _ttm_row_summed's own docstring), only the
    # derived TTM figure is corrected.
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(financials_data, "engine", test_engine)

    async def fake_income_statement(ticker, period, limit):
        return TEAM_SHAPED_INCOME_QUARTERLY if period == "quarter" else TEAM_INCOME_ANNUAL_FY2026

    async def fake_cash_flow_statement(ticker, period, limit):
        return FAKE_CASH_FLOW_QUARTERLY if period == "quarter" else FAKE_CASH_FLOW_ANNUAL

    async def fake_balance_sheet_statement(ticker, period, limit):
        return FAKE_BALANCE_SHEET_QUARTERLY if period == "quarter" else FAKE_BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(financials_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_financials_data("team"))

    ttm_revenue_row = next(item for item in result.income_statement.annual.groups[0].items if item.label == "Revenue")
    # Resolves to the annual figure itself -- not 11,378,147,000 (the raw,
    # double-counted TTM sum a pre-fix Fathom would have shown).
    assert ttm_revenue_row.values[-1] == 6_572_308_000

    # Raw per-quarter column is untouched -- still literally what FMP
    # reported (this tab's "raw, un-converted" convention). Coincidentally
    # the same number as the now-corrected TTM figure above, but for an
    # entirely different reason: the TTM figure is genuinely correct (the
    # annual total, mathematically the true TTM once Q4 closes the fiscal
    # year), while this raw "Q4 2026" cell is still the uncorrected FMP
    # defect -- the true isolated Q4 (annual minus Q1-Q3) would actually be
    # ~$1.77B, not this. Never "corrected" here since the raw quarterly
    # table's whole purpose is showing exactly what FMP reported.
    quarterly_revenue_row = next(
        item for item in result.income_statement.quarterly.groups[0].items if item.label == "Revenue"
    )
    assert quarterly_revenue_row.values[-1] == 6_572_308_000


def test_reported_currency_is_cosmetic_label_only_not_converted(monkeypatch):
    # CLAUDE.md's non-USD currency investigation, decided scope #1: Financials
    # gets a cosmetic label only, the figures themselves stay raw/un-converted
    # -- unlike Step 3's Valuation tab, which does convert.
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(financials_data, "engine", test_engine)

    async def fake_income_statement(ticker, period, limit):
        rows = FAKE_INCOME_QUARTERLY if period == "quarter" else FAKE_INCOME_ANNUAL
        return [{**row, "reportedCurrency": "TWD"} for row in rows]

    async def fake_cash_flow_statement(ticker, period, limit):
        return FAKE_CASH_FLOW_QUARTERLY if period == "quarter" else FAKE_CASH_FLOW_ANNUAL

    async def fake_balance_sheet_statement(ticker, period, limit):
        return FAKE_BALANCE_SHEET_QUARTERLY if period == "quarter" else FAKE_BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(financials_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_financials_data("tsm"))

    assert result.reported_currency == "TWD"
    # Raw revenue figure, un-converted -- same value FAKE_INCOME_ANNUAL[0]
    # ("revenue") declares, not multiplied by any FX rate.
    revenue_row = next(item for item in result.income_statement.annual.groups[0].items if item.label == "Revenue")
    assert revenue_row.values[-2] == 400_000_000_000


def test_reported_currency_none_for_usd_reporter(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(financials_data, "engine", test_engine)

    async def fake_income_statement(ticker, period, limit):
        return FAKE_INCOME_QUARTERLY if period == "quarter" else FAKE_INCOME_ANNUAL

    async def fake_cash_flow_statement(ticker, period, limit):
        return FAKE_CASH_FLOW_QUARTERLY if period == "quarter" else FAKE_CASH_FLOW_ANNUAL

    async def fake_balance_sheet_statement(ticker, period, limit):
        return FAKE_BALANCE_SHEET_QUARTERLY if period == "quarter" else FAKE_BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(financials_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(financials_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_financials_data("aapl"))

    assert result.reported_currency is None
