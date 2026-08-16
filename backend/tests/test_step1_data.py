import asyncio

import httpx
from sqlmodel import SQLModel, create_engine

import data.step1_data as step1_data
from data.step1_data import get_step1_data

PROFILE = [{"sector": "Technology", "industry": "Consumer Electronics"}]

INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 300, "netInterestIncome": 130, "grossProfit": 150, "operatingIncome": 100, "netIncome": 80},
    {"fiscalYear": "2024", "revenue": 250, "netInterestIncome": 110, "grossProfit": 120, "operatingIncome": 80, "netIncome": 60},
    {"fiscalYear": "2023", "revenue": 200, "netInterestIncome": 90, "grossProfit": 100, "operatingIncome": 60, "netIncome": 40},
]

INCOME_QUARTERLY = [
    {"date": "2026-03-31", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-12-31", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-09-30", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-06-30", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
]

CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 90, "capitalExpenditure": -20},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 70, "capitalExpenditure": -15},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 50, "capitalExpenditure": -10},
]

CASH_FLOW_QUARTERLY = [{"netCashProvidedByOperatingActivities": 24, "capitalExpenditure": -5} for _ in range(4)]


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


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)
    return test_engine


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
    assert result.revenue_label == "Revenue"
    assert result.net_income == [40, 60, 80, 84]
    assert result.cfo == [50, 70, 90, 96]
    # capitalExpenditure is already negative (FMP convention) -- FCF = CFO +
    # capitalExpenditure: 50-10=40, 70-15=55, 90-20=70, TTM 96-20=76.
    assert result.fcf == [40, 55, 70, 76]
    assert result.gross_margin[0] == 50.0
    assert result.cfo_exempt_reason is None
    assert result.components["cfo"] is not None
    assert result.components["fcf"]["pattern"] == "consistently_positive"
    assert result.components["fcf"]["score"] == 100
    assert 0 <= result.score <= 100
    assert result.verdict in {"Strong Pass", "Pass", "Fail"}
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


# TEAM's actual FY2026/Q4 FY2026 shape (2026-08-16 investigation): the Q4
# quarterly row is byte-identical to the annual row for revenue/netIncome/
# CFO (but not for other fields like ebitda -- not modeled here, out of
# scope for Step 1). Real values.
TEAM_INCOME_ANNUAL = [{"fiscalYear": "2026", "revenue": 6_572_308_000, "netInterestIncome": 0, "grossProfit": 5_575_478_000, "operatingIncome": 11_366_000, "netIncome": -53_828_000}]

TEAM_INCOME_QUARTERLY = [
    {"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "revenue": 6_572_308_000, "netInterestIncome": 20_260_000, "grossProfit": 5_575_478_000, "operatingIncome": 10_355_000, "netIncome": -53_828_000},
    {"date": "2026-03-31", "period": "Q3", "fiscalYear": "2026", "revenue": 1_786_971_000, "netInterestIncome": 20_260_000, "grossProfit": 1_500_000_000, "operatingIncome": 2_000_000, "netIncome": -98_389_000},
    {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "revenue": 1_586_315_000, "netInterestIncome": 20_260_000, "grossProfit": 1_300_000_000, "operatingIncome": 1_000_000, "netIncome": -42_645_000},
    {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "revenue": 1_432_553_000, "netInterestIncome": 20_260_000, "grossProfit": 1_200_000_000, "operatingIncome": 500_000, "netIncome": -51_870_000},
]

TEAM_CASH_FLOW_ANNUAL = [{"fiscalYear": "2026", "netCashProvidedByOperatingActivities": 1_353_135_000, "capitalExpenditure": -34_060_000}]

TEAM_CASH_FLOW_QUARTERLY = [
    {"period": "Q4", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 1_353_135_000, "capitalExpenditure": -34_060_000},
    {"period": "Q3", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 567_475_000, "capitalExpenditure": -6_211_000},
    {"period": "Q2", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 177_805_000, "capitalExpenditure": -9_289_000},
    {"period": "Q1", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 128_715_000, "capitalExpenditure": -14_112_000},
]


def test_get_step1_data_corrects_team_shaped_duplicate_annual_quarter(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    async def fake_profile(ticker):
        return PROFILE

    async def fake_income_statement(ticker, period, limit):
        return TEAM_INCOME_ANNUAL if period == "annual" else TEAM_INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return TEAM_CASH_FLOW_ANNUAL if period == "annual" else TEAM_CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("team"))

    # TTM revenue/net_income/cfo all resolve to the annual figure itself
    # (the true isolated Q4 + the other 3 known-good quarters always sum
    # back to it by construction) -- not the raw, ~1.7x-inflated double-count
    # a pre-fix Fathom would have shown (revenue TTM would have read
    # ~$11.38B against real cached TEAM data with this same shape).
    assert result.revenue[-1] == 6_572_308_000
    assert result.net_income[-1] == -53_828_000
    assert result.cfo[-1] == 1_353_135_000
    # No revenue/net_income/cfo outlier warning -- correctly resolved by the
    # duplicate-annual correction, not just flagged as anomalous.
    flagged_metrics = {w.metric for w in result.outlier_warnings}
    assert "revenue" not in flagged_metrics
    assert "net_income" not in flagged_metrics
    assert "cfo" not in flagged_metrics


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

    # FCF mirrors CFO's exemption exactly -- derived from CFO, so it's not a
    # reliable signal for Banks either.
    assert result.fcf is None
    assert result.components["fcf"] is None

    # Change 1: Banks show Net Interest Income in place of Revenue, clearly
    # labeled -- not silently substituted under the old "Revenue" label.
    assert result.revenue_label == "Net Interest Income"
    assert result.revenue == [90, 110, 130, 140]

    # Margins must stay tied to real Revenue, not NII -- gross margin here
    # should read against the 200/250/300/320 revenue series, not NII.
    assert result.gross_margin[0] == 50.0  # grossProfit 100 / revenue 200 * 100


def test_insurance_is_cfo_exempt_but_keeps_revenue_label(monkeypatch):
    # MET/PGR-shaped: sector "Financial Services", industry "Insurance -
    # Life" -- Insurance now gets the same CFO/FCF de-emphasis Bank already
    # had (claim timing/reserve movements/investment portfolio fluctuations
    # make OCF noisy for insurers too), but must NOT get Bank's Net Interest
    # Income revenue-label swap -- that's Bank-only.
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
    _patch_fmp(monkeypatch, call_count, sector="Financial Services", industry="Insurance - Life")

    result = asyncio.run(get_step1_data("met"))

    assert result.cfo_exempt_reason == "Insurance"
    assert result.cfo is None
    assert result.components["cfo"] is None
    assert result.fcf is None
    assert result.components["fcf"] is None

    # Unlike Bank, Insurance keeps the plain Revenue label/series -- no NII
    # swap.
    assert result.revenue_label == "Revenue"
    assert result.revenue == [200, 250, 300, 320]


def test_insufficient_data_when_cash_flow_fetch_fails(monkeypatch):
    # Mirrors the confirmed Step 1 repro: a genuine FMP fetch failure on ONE
    # of Step 1's 5 independently-isolated safe_fetch calls (cash flow) must
    # not fabricate a scored Fail out of an otherwise-strong ticker -- Revenue/
    # Net Income/Margins here are all real and strong (grows_every_year /
    # stable_or_expanding); only CFO/FCF read as insufficient_data. Same
    # insufficient_data convention as Step 2's fix (see CLAUDE.md).
    _fresh_engine(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("TEST"))

    assert result.score is None
    assert result.verdict == "insufficient_data"
    assert result.components == {}


def test_insufficient_data_when_total_fetch_failure(monkeypatch):
    # Every underlying fetch failing (profile + income statement + cash
    # flow) must collapse to the same insufficient_data state as the
    # single-endpoint failure above, not a maximally-negative fabricated
    # Fail.
    _fresh_engine(monkeypatch)

    async def raise_error(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", raise_error)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", raise_error)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", raise_error)

    result = asyncio.run(get_step1_data("TEST"))

    assert result.score is None
    assert result.verdict == "insufficient_data"
    assert result.components == {}


def test_insufficient_data_when_genuinely_thin_cash_flow_history(monkeypatch):
    # Not a fetch failure -- FMP responds successfully but with zero annual
    # cash-flow filings (a real data gap for this ticker, e.g. a data
    # provider coverage gap). Must land on the same insufficient_data state
    # as an actual fetch failure above, not a scored Fail -- the two are
    # deliberately indistinguishable downstream (see CLAUDE.md's Step 1/
    # Step 2 deviations).
    _fresh_engine(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return [] if period == "annual" else CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("TEST"))

    assert result.score is None
    assert result.verdict == "insufficient_data"
