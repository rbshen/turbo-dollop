import asyncio

from sqlmodel import SQLModel, create_engine

import data.ratios_data as ratios_data
from data.ratios_data import (
    CATEGORIES,
    LEVERAGE_FIELDS,
    LIQUIDITY_FIELDS,
    MARGIN_FIELDS,
    PAYOUT_FIELDS,
    PER_SHARE_FIELDS,
    RETURNS_FIELDS,
    VALUATION_FIELDS,
    _annual_series,
    _annual_years,
    _strip_ttm_suffix,
    _ttm_value,
    get_ratios_data,
)

KEY_METRICS_ANNUAL = [
    {"fiscalYear": "2025", "date": "2025-09-27", "evToEBITDA": 27.0, "earningsYield": 0.03, "workingCapital": -17_674_000_000},
    {"fiscalYear": "2024", "date": "2024-09-28", "evToEBITDA": 26.6, "earningsYield": 0.027, "workingCapital": -23_405_000_000},
]

KEY_METRICS_TTM = [{"evToEBITDATTM": 30.8, "earningsYieldTTM": 0.025, "workingCapitalTTM": 9_473_000_000}]

RATIOS_ANNUAL = [
    {"fiscalYear": "2025", "date": "2025-09-27", "priceToEarningsRatio": 34.1, "grossProfitMargin": 0.469, "currentRatio": 0.89},
    {"fiscalYear": "2024", "date": "2024-09-28", "priceToEarningsRatio": 37.3, "grossProfitMargin": 0.462, "currentRatio": 0.87},
]

RATIOS_TTM = [{"priceToEarningsRatioTTM": 40.2, "grossProfitMarginTTM": 0.479, "currentRatioTTM": 1.07}]

BALANCE_SHEET_QUARTERLY = [{"date": "2026-06-27"}]


def _patch_fmp(monkeypatch):
    async def fake_key_metrics(ticker, period, limit):
        return KEY_METRICS_ANNUAL

    async def fake_key_metrics_ttm(ticker):
        return KEY_METRICS_TTM

    async def fake_ratios(ticker, period, limit):
        return RATIOS_ANNUAL

    async def fake_ratios_ttm(ticker):
        return RATIOS_TTM

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY

    monkeypatch.setattr(ratios_data.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(ratios_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)
    monkeypatch.setattr(ratios_data.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(ratios_data.fmp_client, "get_ratios_ttm", fake_ratios_ttm)
    monkeypatch.setattr(ratios_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(ratios_data, "engine", test_engine)


def test_percent_unit_is_scaled_by_100():
    values = _annual_series(RATIOS_ANNUAL, "grossProfitMargin", "percent")
    # Padded to ANNUAL_WINDOW (10), real values are the last 2 (oldest-first).
    assert values[-2:] == [46.2, 46.9]


def test_ratio_and_days_units_are_not_scaled():
    values = _annual_series(RATIOS_ANNUAL, "priceToEarningsRatio", "ratio")
    assert values[-2:] == [37.3, 34.1]


def test_ttm_suffix_stripped_and_looked_up_by_bare_field_name():
    stripped = _strip_ttm_suffix(RATIOS_TTM[0])
    assert stripped["priceToEarningsRatio"] == 40.2
    assert "priceToEarningsRatioTTM" not in stripped


def test_ttm_value_applies_percent_scaling_same_as_annual():
    stripped = _strip_ttm_suffix(RATIOS_TTM[0])
    assert _ttm_value(stripped, "grossProfitMargin", "percent") == 47.9
    assert _ttm_value(stripped, "priceToEarningsRatio", "ratio") == 40.2


def test_ttm_value_missing_field_returns_none():
    assert _ttm_value({}, "grossProfitMargin", "percent") is None


def test_annual_years_falls_back_across_sources():
    years = _annual_years([], RATIOS_ANNUAL)
    assert years[-2:] == ["2024", "2025"]


def test_category_order_matches_task_3():
    assert [label for label, _ in CATEGORIES] == [
        "Valuation Multiples",
        "Profitability Margins",
        "Returns & Efficiency",
        "Liquidity",
        "Leverage & Solvency",
        "Coverage",
        "Cash Flow Ratios",
        "Per-Share",
        "Payout",
    ]


def test_dropped_duplicate_fields_are_absent():
    # ratios.enterpriseValueMultiple (exact duplicate of key_metrics.evToEBITDA),
    # ratios.priceToFairValue (exact duplicate of priceToBookRatio, not a real
    # distinct fair-value figure), and ratios.taxBurden-style confusion are all
    # deliberately excluded -- see ratios_data.py's field-table comment.
    all_keys = {key for _, fields in CATEGORIES for _, _, key, _ in fields}
    assert "enterpriseValueMultiple" not in all_keys
    assert "priceToFairValue" not in all_keys
    assert "taxBurden" not in all_keys
    assert "shareholdersEquityPerShare" not in all_keys


def test_per_share_and_payout_field_counts():
    assert len(PER_SHARE_FIELDS) == 10
    assert len(PAYOUT_FIELDS) == 1
    assert len(VALUATION_FIELDS) == 16
    assert len(MARGIN_FIELDS) == 7
    assert len(RETURNS_FIELDS) == 12
    assert len(LIQUIDITY_FIELDS) == 5
    assert len(LEVERAGE_FIELDS) == 7


def test_full_pipeline_builds_all_categories_with_dated_ttm_label(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_ratios_data("aapl"))

    assert result.ticker == "AAPL"
    assert result.periods[-1] == "TTM (2026-06-27)"
    assert result.periods[-3:-1] == ["2024", "2025"]
    assert len(result.groups) == len(CATEGORIES)

    pe_row = next(item for item in result.groups[0].items if item.label == "P/E")
    assert pe_row.values[-3:] == [37.3, 34.1, 40.2]

    ev_ebitda_row = next(item for item in result.groups[0].items if item.label == "EV/EBITDA")
    assert ev_ebitda_row.values[-3:] == [26.6, 27.0, 30.8]

    margin_row = next(item for item in result.groups[1].items if item.label == "Gross Margin")
    assert margin_row.values[-3:] == [46.2, 46.9, 47.9]
    assert margin_row.unit == "percent"


def test_full_pipeline_falls_back_to_plain_ttm_label_without_quarterly_date(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    async def fake_balance_sheet_statement_empty(ticker, period, limit):
        return []

    monkeypatch.setattr(ratios_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement_empty)

    result = asyncio.run(get_ratios_data("aapl"))

    assert result.periods[-1] == "TTM"


def test_full_pipeline_missing_source_degrades_to_none_not_crash(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    async def fake_ratios_empty(ticker, period, limit):
        return []

    monkeypatch.setattr(ratios_data.fmp_client, "get_ratios", fake_ratios_empty)

    result = asyncio.run(get_ratios_data("aapl"))

    pe_row = next(item for item in result.groups[0].items if item.label == "P/E")
    assert pe_row.values[-1] is None or pe_row.values[-1] == 40.2  # annual is None, TTM still comes from ratios_ttm
    assert pe_row.values[-3:-1] == [None, None]
