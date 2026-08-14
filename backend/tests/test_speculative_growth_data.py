"""Orchestration tests for data/speculative_growth_data.py -- fresh
in-memory engine per CLAUDE.md's caching-policy convention (see
test_debt_metrics.py's own documented fix for the exact class of bug this
guards against): this module calls into get_step1_data/get_step2_data,
which each open their own Session bound to their own module's `engine`
import, so ALL THREE engine references must be monkeypatched to the same
fresh in-memory engine, not just this module's own. tests/conftest.py's
session-wide write-guard on the real core.db.engine is the backstop if
this is ever missed.
"""

import asyncio

import pytest
from sqlmodel import SQLModel, create_engine

import data.speculative_growth_data as speculative_growth_data
import data.step1_data as step1_data
import data.step2_data as step2_data
from data.speculative_growth_data import get_speculative_growth_data

TODAY_YEAR = 2026

PROFILE_STANDARD = [{"companyName": "Acme Corp", "sector": "Technology", "industry": "Software - Application"}]
PROFILE_BANK = [{"companyName": "Acme Bank", "sector": "Financial Services", "industry": "Banks - Regional"}]
PROFILE_COMMODITY = [{"companyName": "Acme Materials", "sector": "Energy", "industry": "Oil & Gas E&P"}]

INCOME_ANNUAL = [
    {
        "fiscalYear": "2025",
        "revenue": 100.0,
        "grossProfit": 40.0,
        "operatingIncome": -10.0,
        "netIncome": -20.0,
        "netInterestIncome": 0.0,
    },
    {
        "fiscalYear": "2024",
        "revenue": 60.0,
        "grossProfit": 25.0,
        "operatingIncome": -15.0,
        "netIncome": -25.0,
        "netInterestIncome": 0.0,
    },
]


def _income_quarter(date: str) -> dict:
    return {
        "date": date,
        "revenue": 40.0,
        "grossProfit": 16.0,
        "operatingIncome": -2.0,
        "netIncome": -5.0,
        "netInterestIncome": 0.0,
    }


# 12 quarters, most-recent-first (TOTAL_QUARTERS_NEEDED) -- identical values
# throughout, only the CFO figures (a separate statement, below) vary.
INCOME_QUARTERLY = [_income_quarter(f"2026-{i + 1:02d}-01") for i in range(12)]

# q0 (latest, index 0) is a real positive CFO quarter despite TTM (q0..q3)
# still summing negative (-85) -- so cfo_recent_direction reads
# "turning_positive" while cash_runway_years still computes off a genuinely
# negative TTM burn, exercising both at once.
CASH_FLOW_QUARTERLY = [
    {"date": "2026-03-28", "netCashProvidedByOperatingActivities": 5.0, "capitalExpenditure": -1.0},
    {"date": "2025-12-27", "netCashProvidedByOperatingActivities": -30.0, "capitalExpenditure": -1.0},
    {"date": "2025-09-27", "netCashProvidedByOperatingActivities": -30.0, "capitalExpenditure": -1.0},
    {"date": "2025-06-28", "netCashProvidedByOperatingActivities": -30.0, "capitalExpenditure": -1.0},
] + [{"date": f"2024-{q:02d}-01", "netCashProvidedByOperatingActivities": -30.0, "capitalExpenditure": -1.0} for q in range(1, 9)]

BALANCE_SHEET_QUARTERLY = [{"date": "2026-03-28", "cashAndShortTermInvestments": 850.0}]

RATIOS = [{"priceToSalesRatio": 5.0}]

# Analyst estimates -- EPS doubling over 4 years => CAGR ~18.9%, clears the
# >15% growth gate. Dates use TODAY_YEAR+1 as the nearest future fiscal year,
# matching test_step2_data.py's own BASE_YEAR convention.
_BASE_YEAR = TODAY_YEAR + 1
ESTIMATES_STRONG_GROWTH = [
    {"date": f"{_BASE_YEAR}-06-30", "epsAvg": 1.0, "epsLow": 0.9, "epsHigh": 1.1, "numAnalystsEps": 5},
    {"date": f"{_BASE_YEAR + 4}-06-30", "epsAvg": 2.0, "epsLow": 1.8, "epsHigh": 2.2, "numAnalystsEps": 5},
]
# EPS growing only slowly -- CAGR ~4.7%, fails the >15% growth gate.
ESTIMATES_WEAK_GROWTH = [
    {"date": f"{_BASE_YEAR}-06-30", "epsAvg": 1.0, "epsLow": 0.9, "epsHigh": 1.1, "numAnalystsEps": 5},
    {"date": f"{_BASE_YEAR + 4}-06-30", "epsAvg": 1.2, "epsLow": 1.1, "epsHigh": 1.3, "numAnalystsEps": 5},
]


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(speculative_growth_data, "engine", test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)
    monkeypatch.setattr(step2_data, "engine", test_engine)
    return test_engine


def _patch_fmp(
    monkeypatch,
    profile: list[dict],
    estimates: list[dict] | None = None,
    forbid_deep_fetches: bool = False,
):
    async def fake_profile(ticker):
        return profile

    async def fake_earnings(ticker):
        return []

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        if forbid_deep_fetches:
            raise AssertionError("cash_flow_statement should not be fetched for a non-Standard/excluded ticker")
        return CASH_FLOW_QUARTERLY

    async def fake_balance_sheet_statement(ticker, period, limit):
        if forbid_deep_fetches:
            raise AssertionError("balance_sheet_statement should not be fetched for a non-Standard/excluded ticker")
        return BALANCE_SHEET_QUARTERLY

    async def fake_ratios(ticker, *args, **kwargs):
        if forbid_deep_fetches:
            raise AssertionError("ratios should not be fetched for a non-Standard/excluded ticker")
        return RATIOS

    async def fake_estimates(ticker):
        return estimates or []

    for mod in (speculative_growth_data, step1_data, step2_data):
        monkeypatch.setattr(mod.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(speculative_growth_data.fmp_client, "get_earnings", fake_earnings)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(speculative_growth_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(speculative_growth_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(speculative_growth_data.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(step2_data.fmp_client, "get_analyst_estimates", fake_estimates)


def _set_moat(engine, ticker: str, moat: str) -> None:
    from datetime import datetime

    from sqlmodel import Session

    from core.models import TickerMoat

    with Session(engine) as session:
        session.add(TickerMoat(ticker=ticker, moat=moat, updated_at=datetime.now()))
        session.commit()


def test_standard_ticker_with_moat_and_strong_growth_qualifies_end_to_end(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, PROFILE_STANDARD, estimates=ESTIMATES_STRONG_GROWTH)
    _set_moat(engine, "TEST", "narrow_moat")

    result = asyncio.run(get_speculative_growth_data("TEST"))

    assert result.qualifies is True
    assert result.company_type == "Standard"
    assert result.not_applicable_reason is None
    assert result.moat == "narrow_moat"
    assert result.growth_rate_pct is not None and result.growth_rate_pct > 15.0
    # TTM revenue (4 * 40 = 160) vs last FY (100) -> 60% trailing growth.
    assert result.trailing_revenue_growth_pct == pytest.approx(60.0)
    # TTM gross margin: 64 / 160 = 40%.
    assert result.gross_margin_ttm_pct == pytest.approx(40.0)
    # TTM net income: 4 * -5 = -20.
    assert result.net_income_ttm == pytest.approx(-20.0)
    # TTM CFO: 5 - 30 - 30 - 30 = -85, a real burn.
    assert result.cfo_ttm == pytest.approx(-85.0)
    assert result.cfo_recent_direction == "turning_positive"
    assert result.cash_and_st_investments == pytest.approx(850.0)
    assert result.cash_runway_years == pytest.approx(10.0)
    assert result.price_to_sales_ttm == pytest.approx(5.0)
    assert result.psg_ratio == pytest.approx(5.0 / 60.0)


def test_bank_ticker_excluded_before_any_deep_fetch(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, PROFILE_BANK, forbid_deep_fetches=True)

    result = asyncio.run(get_speculative_growth_data("TEST"))

    assert result.qualifies is False
    assert result.company_type == "Bank"
    assert result.not_applicable_reason is not None
    assert result.moat is None
    assert result.cash_runway_years is None


def test_standard_ticker_without_moat_does_not_qualify(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, PROFILE_STANDARD, estimates=ESTIMATES_STRONG_GROWTH)
    # No _set_moat call -- moat stays unset (None).

    result = asyncio.run(get_speculative_growth_data("TEST"))

    assert result.qualifies is False
    assert result.company_type == "Standard"
    assert result.not_applicable_reason is None  # in-scope, just didn't clear the moat gate
    assert result.moat is None
    # Informational fields still populate -- only `qualifies` is gated.
    assert result.growth_rate_pct is not None and result.growth_rate_pct > 15.0


def test_standard_ticker_with_weak_growth_does_not_qualify(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, PROFILE_STANDARD, estimates=ESTIMATES_WEAK_GROWTH)
    _set_moat(engine, "TEST", "wide_moat")

    result = asyncio.run(get_speculative_growth_data("TEST"))

    assert result.qualifies is False
    assert result.moat == "wide_moat"
    assert result.growth_rate_pct is not None and result.growth_rate_pct <= 15.0


def test_commodity_company_excluded_even_though_shared_classifier_says_standard(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, PROFILE_COMMODITY, estimates=ESTIMATES_STRONG_GROWTH)
    _set_moat(engine, "TEST", "narrow_moat")

    result = asyncio.run(get_speculative_growth_data("TEST"))

    # scoring.classification.classify_company_type has no Basic Materials/
    # Energy branch (it falls through to "Standard"), but Step1's own
    # _detect_exemption catches Commodity Company specifically -- confirms
    # this module defers to the stricter of the two rather than only the
    # shared classifier.
    assert result.qualifies is False
    assert result.company_type == "Commodity Company"
    assert result.not_applicable_reason is not None
