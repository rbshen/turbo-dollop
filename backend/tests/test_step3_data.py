import asyncio
import json

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.step3_data as step3_data
from data.custom_valuation_data import activate_ticker_custom_valuation, set_ticker_custom_valuation
from data.step3_data import get_active_valuation, get_step3_data
from scoring.step3 import run_20yr_engine

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
    import data.step2_data as step2_data

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


def test_insurance_never_lands_on_cfo_based_method_end_to_end(monkeypatch):
    # PGR-shaped repro: strong, consistently-increasing CFO that would
    # otherwise qualify for DCF/DFCF -- Insurance must still skip straight
    # to the Net Income check and land on a DNI-family method.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Financial Services", "industry": "Insurance - Property & Casualty", "beta": 0.9}]

    async def fake_income_statement(ticker, period, limit):
        if period == "annual":
            return [
                {"fiscalYear": "2025", "revenue": 300, "netIncome": 50},
                {"fiscalYear": "2024", "revenue": 280, "netIncome": 40},
                {"fiscalYear": "2023", "revenue": 260, "netIncome": 30},
                {"fiscalYear": "2022", "revenue": 240, "netIncome": 20},
                {"fiscalYear": "2021", "revenue": 220, "netIncome": 10},
            ]
        return [{"date": "2026-03-31", "revenue": 80, "netIncome": 15} for _ in range(4)]

    async def fake_cash_flow_statement(ticker, period, limit):
        if period == "annual":
            return [
                {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 100, "capitalExpenditure": -5},
                {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 90, "capitalExpenditure": -5},
                {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 80, "capitalExpenditure": -5},
                {"fiscalYear": "2022", "netCashProvidedByOperatingActivities": 70, "capitalExpenditure": -5},
                {"fiscalYear": "2021", "netCashProvidedByOperatingActivities": 60, "capitalExpenditure": -5},
            ]
        return [{"netCashProvidedByOperatingActivities": 25, "capitalExpenditure": -1.25} for _ in range(4)]

    monkeypatch.setattr(step3_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step3_data("pgr"))

    assert result.company_type == "Insurance"
    assert result.selected_method in ("DNI", "DNI_NORMALIZED", "PSG", "PASS")
    steps_by_id = {s.step: s for s in result.method_reasoning}
    assert "2" not in steps_by_id
    assert "3" not in steps_by_id
    assert steps_by_id["1a"].passed is True


def test_reit_gets_dividend_dpu_fields_and_pb_benchmark(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Real Estate", "industry": "REIT - Retail", "beta": 1.0}]

    async def fake_ratios(ticker, period, limit):
        return [
            {
                "fiscalYear": str(2025 - i),
                "priceToBookRatio": 1.3 + i * 0.02,
                "bookValuePerShare": 50.0,
                "revenuePerShare": 10.0,
                "dividendYield": 0.045,
                "dividendPerShare": 2.0 + (9 - i) * 0.1,
            }
            for i in range(10)
        ]

    monkeypatch.setattr(step3_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step3_data.fmp_client, "get_ratios", fake_ratios)

    result = asyncio.run(get_step3_data("o"))

    assert result.company_type == "REIT/Property Developer"
    assert result.selected_method == "PRICE_TO_BOOK"
    # dividendYield 0.045 -> 4.5%, above the 4% REIT threshold.
    assert result.dividend_yield_pct == pytest.approx(4.5)
    assert result.dividend_yield_meets_reit_threshold is True
    assert result.dpu_growth_note is not None
    assert "grew" in result.dpu_growth_note
    # REIT benchmark: no fixed low, 1.2 fair-value ceiling, conditional note.
    assert result.benchmark_pb_low is None
    assert result.benchmark_pb_high == 1.2
    assert "1.5" in result.benchmark_pb_note


def test_bank_gets_pb_benchmark_and_buy_signal(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Financial Services", "industry": "Banks - Diversified", "beta": 1.1}]

    async def fake_quote(ticker):
        # Deliberately below the -1SD band computed from the ratios below
        # (mean 1.0, sd ~0 given flat 1.0 history -> -1SD == 1.0 * 50 == 50) --
        # picking a price well under that to trip the buy signal.
        return [{"price": 10.0, "marketCap": 10_000_000_000}]

    async def fake_ratios(ticker, period, limit):
        return [{"fiscalYear": str(2025 - i), "priceToBookRatio": 1.0, "bookValuePerShare": 50.0} for i in range(10)]

    async def fake_balance_sheet_statement(ticker, period, limit):
        # shares_outstanding = marketCap/price = 10_000_000_000/10.0 =
        # 1_000_000_000 (see fake_quote above); totalAssets -
        # goodwillAndIntangibleAssets - totalLiabilities = 50_000_000_000,
        # so book_value_per_share = 50.0 -- same figure the old
        # ratios_annual-based bookValuePerShare mock above used to supply
        # directly, now sourced from the balance sheet per Piece 1.
        return [
            {
                "cashAndCashEquivalents": 100,
                "totalDebt": 0,
                "totalAssets": 60_000_000_000,
                "goodwillAndIntangibleAssets": 0,
                "totalLiabilities": 10_000_000_000,
            }
        ]

    monkeypatch.setattr(step3_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step3_data.fmp_client, "get_quote", fake_quote)
    monkeypatch.setattr(step3_data.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(step3_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step3_data("jpm"))

    assert result.company_type == "Bank"
    assert result.selected_method == "PRICE_TO_BOOK"
    assert result.benchmark_pb_low == 1.2
    assert result.benchmark_pb_high == 1.4
    assert result.benchmark_pb_note is None
    # Bank isn't REIT -- no dividend/DPU fields.
    assert result.dividend_yield_pct is None
    assert result.dividend_yield_meets_reit_threshold is None
    assert result.dpu_growth_note is None
    # Flat P/B history -> sd=0 -> minus_1sd == mean == 50.0; price 10.0 is
    # well below that, so the buy signal should read True.
    assert result.historical_pb_buy_signal is True


def test_standard_company_has_no_benchmark_or_dividend_fields(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.company_type == "Standard"
    assert result.benchmark_pb_low is None
    assert result.benchmark_pb_high is None
    assert result.dividend_yield_pct is None


# --- Non-USD reportedCurrency conversion -------------------------------------


def test_usd_reporter_never_fetches_fx_and_stays_1_0(monkeypatch):
    # INCOME_ANNUAL/etc. (the shared _patch_real_data fixture) never sets
    # reportedCurrency at all -- same as a genuine USD-reporting ticker's
    # real FMP payload. Must resolve fx_rate=1.0 with zero forex fetches,
    # not just a coincidentally-correct fx_rate.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fail_if_called(from_currency):
        raise AssertionError(f"get_forex_quote should never be called for a USD reporter (got {from_currency!r})")

    monkeypatch.setattr(step3_data.fmp_client, "get_forex_quote", fail_if_called)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.inputs.reported_currency is None
    assert result.inputs.fx_rate == 1.0
    assert result.inputs.fx_rate_as_of is None


def test_non_usd_reporter_converts_every_monetary_input_to_usd(monkeypatch):
    # Bank/P-B fixture (same shape as test_bank_gets_pb_benchmark_and_buy_
    # signal) -- picked because P/B's math is the easiest to hand-verify:
    # mean_pb(1.0) * book_value_per_share(50.0 TWD) * fx_rate(0.05) == 2.5
    # USD, with no engine/discount-rate machinery involved.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Financial Services", "industry": "Banks - Diversified", "beta": 1.1}]

    async def fake_income_statement(ticker, period, limit):
        rows = INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY
        return [{**row, "reportedCurrency": "TWD"} for row in rows]

    async def fake_ratios(ticker, period, limit):
        return [{"fiscalYear": str(2025 - i), "priceToBookRatio": 1.0, "bookValuePerShare": 50.0} for i in range(10)]

    async def fake_forex_quote(from_currency):
        assert from_currency == "TWD"
        return [{"symbol": "TWDUSD", "price": 0.05}]

    async def fake_balance_sheet_statement(ticker, period, limit):
        # shares_outstanding = marketCap/price = 10_000_000_000/100.0 =
        # 100_000_000 (module-level QUOTE, not overridden by this test);
        # totalAssets - goodwillAndIntangibleAssets - totalLiabilities =
        # 5_000_000_000 TWD, so book_value_per_share = 50.0 TWD pre-fx --
        # matching the comment above (50.0 TWD * 0.05 == 2.5 USD).
        return [
            {
                "cashAndCashEquivalents": 100,
                "totalDebt": 0,
                "totalAssets": 6_000_000_000,
                "goodwillAndIntangibleAssets": 0,
                "totalLiabilities": 1_000_000_000,
            }
        ]

    monkeypatch.setattr(step3_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(step3_data.fmp_client, "get_forex_quote", fake_forex_quote)
    monkeypatch.setattr(step3_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step3_data("jpm"))

    assert result.company_type == "Bank"
    assert result.selected_method == "PRICE_TO_BOOK"
    assert result.inputs.reported_currency == "TWD"
    assert result.inputs.fx_rate == pytest.approx(0.05)
    assert result.inputs.fx_rate_as_of is not None
    # book_value_per_share converted (50.0 TWD * 0.05 == 2.5 USD) -- the
    # displayed/pre-fill-able raw input, not just the final band.
    assert result.inputs.book_value_per_share == pytest.approx(2.5)
    assert result.pb_bands is not None
    assert result.pb_bands.mean == pytest.approx(2.5)
    assert result.intrinsic_value_per_share == pytest.approx(2.5)


# --- TTM-period-duplicate exclusion (net_income_smoothed/cfo_smoothed/
# fcf_smoothed) -- end-to-end wiring, not just the pure-function unit tests
# in scoring/test_step3.py and tests/test_ttm.py ---------------------------

# 6 annual years (most-recent-first, FMP's own order); FY2026's netIncome
# (900) is also exactly what the 4 quarterly rows below sum to -- no
# quarter has posted since FY2026 closed, so TTM duplicates FY2026.
INCOME_ANNUAL_TTM_DUP = [
    {"fiscalYear": "2026", "revenue": 300, "netIncome": 900},
    {"fiscalYear": "2025", "revenue": 300, "netIncome": 100},
    {"fiscalYear": "2024", "revenue": 300, "netIncome": 100},
    {"fiscalYear": "2023", "revenue": 300, "netIncome": 100},
    {"fiscalYear": "2022", "revenue": 300, "netIncome": 100},
    {"fiscalYear": "2021", "revenue": 300, "netIncome": 500},
]
INCOME_QUARTERLY_TTM_DUP = [
    {"fiscalYear": "2026", "period": "Q4", "revenue": 75, "netIncome": 225},
    {"fiscalYear": "2026", "period": "Q3", "revenue": 75, "netIncome": 225},
    {"fiscalYear": "2026", "period": "Q2", "revenue": 75, "netIncome": 225},
    {"fiscalYear": "2026", "period": "Q1", "revenue": 75, "netIncome": 225},
]
CASH_FLOW_ANNUAL_TTM_DUP = [
    {"fiscalYear": "2026", "netCashProvidedByOperatingActivities": 900, "capitalExpenditure": -50},
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 100, "capitalExpenditure": -50},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 100, "capitalExpenditure": -50},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 100, "capitalExpenditure": -50},
    {"fiscalYear": "2022", "netCashProvidedByOperatingActivities": 100, "capitalExpenditure": -50},
    {"fiscalYear": "2021", "netCashProvidedByOperatingActivities": 500, "capitalExpenditure": -50},
]
CASH_FLOW_QUARTERLY_TTM_DUP = [
    {"fiscalYear": "2026", "period": "Q4", "netCashProvidedByOperatingActivities": 225, "capitalExpenditure": -12.5},
    {"fiscalYear": "2026", "period": "Q3", "netCashProvidedByOperatingActivities": 225, "capitalExpenditure": -12.5},
    {"fiscalYear": "2026", "period": "Q2", "netCashProvidedByOperatingActivities": 225, "capitalExpenditure": -12.5},
    {"fiscalYear": "2026", "period": "Q1", "netCashProvidedByOperatingActivities": 225, "capitalExpenditure": -12.5},
]


def test_smoothed_candidates_exclude_duplicate_ttm_and_use_prior_5_distinct_years(monkeypatch):
    # SNDK-shaped fixture (see CLAUDE.md's Item 2 note): without the fix,
    # net_income_smoothed would average the last 5 elements of [500, 100,
    # 100, 100, 100, 900, 900] (annual + duplicated TTM) = (100+100+100+900
    # +900)/5 = 440, double-weighting the 900 spike year at 2/5 instead of
    # the intended 1/5. With the fix, TTM is dropped and the prior 5
    # DISTINCT fiscal years are averaged instead: (100+100+100+100+900)/5
    # = 260.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL_TTM_DUP if period == "annual" else INCOME_QUARTERLY_TTM_DUP

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_ANNUAL_TTM_DUP if period == "annual" else CASH_FLOW_QUARTERLY_TTM_DUP

    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step3_data("TEST"))

    candidates = result.inputs.current_value_candidates
    assert candidates.net_income_ttm == pytest.approx(900.0)
    assert candidates.net_income_smoothed == pytest.approx((100 + 100 + 100 + 100 + 900) / 5)
    assert candidates.cfo_ttm == pytest.approx(900.0)
    assert candidates.cfo_smoothed == pytest.approx((100 + 100 + 100 + 100 + 900) / 5)
    # FCF = CFO + CapEx (CapEx already negative): annual FCF is [450, 50,
    # 50, 50, 50, 850] chronologically, TTM FCF = 900 + (-50) = 850 (a
    # duplicate of FY2026's own FCF the same way NI/CFO are).
    assert candidates.fcf_ttm == pytest.approx(850.0)
    assert candidates.fcf_smoothed == pytest.approx((50 + 50 + 50 + 50 + 850) / 5)


def test_non_usd_reporter_with_no_fx_rate_available_is_insufficient_data(monkeypatch):
    # FX fetch fails AND no cached rate (fresh or stale) exists at all --
    # must never silently fall back to fx_rate=1.0 (which would render a
    # raw-TWD-scale number as if it were USD). Must read insufficient_data,
    # same shape as a genuine total-fetch-failure case elsewhere in this
    # file, never a fabricated numeric valuation.
    _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    async def fake_income_statement(ticker, period, limit):
        rows = INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY
        return [{**row, "reportedCurrency": "TWD"} for row in rows]

    async def fake_forex_quote(from_currency):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_forex_quote", fake_forex_quote)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.selected_method == "PASS"
    assert result.insufficient_data is True
    assert result.intrinsic_value_per_share is None
    assert result.inputs.reported_currency == "TWD"
    assert result.inputs.fx_rate is None
    assert "TWD" in result.pass_reason
    assert "→USD" in result.pass_reason


def test_non_usd_reporter_falls_back_to_stale_cached_fx_rate_on_fetch_failure(monkeypatch):
    # A real rate was cached previously (now past the 1-day staleness
    # window) and the live refetch fails -- must reuse the stale rate
    # rather than treating this the same as "no rate ever available."
    from datetime import datetime, timedelta

    from core.models import FundamentalsCache

    test_engine = _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    with Session(test_engine) as session:
        session.add(
            FundamentalsCache(
                ticker="TWDUSD",
                statement_type="forex_rate",
                period="latest",
                fetched_at=datetime.now() - timedelta(days=30),
                raw_json=json.dumps([{"symbol": "TWDUSD", "price": 0.031}]),
            )
        )
        session.commit()

    async def fake_income_statement(ticker, period, limit):
        rows = INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY
        return [{**row, "reportedCurrency": "TWD"} for row in rows]

    async def fake_forex_quote(from_currency):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step3_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step3_data.fmp_client, "get_forex_quote", fake_forex_quote)

    result = asyncio.run(get_step3_data("TEST"))

    assert result.inputs.reported_currency == "TWD"
    assert result.inputs.fx_rate == pytest.approx(0.031)
    assert result.insufficient_data is False


# --- get_active_valuation: Auto vs. an active/inactive TickerCustomValuation ---

_PSG_PARAMS = {
    "current_value": None,
    "growth_yr_1_5": None,
    "growth_yr_6_10": None,
    "growth_yr_11_20": None,
    "discount_rate": None,
    "shares_outstanding": None,
    "total_debt": None,
    "cash_and_st_investments": None,
    "book_value_per_share": None,
    "pb_mean_ratio": None,
    "pb_sd_ratio": None,
    "sales_per_share": 10.0,
    "projected_growth_rate": 0.10,
    "fair_psg_ratio": 0.2,
}


def test_get_active_valuation_falls_back_to_auto_when_nothing_saved(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)

    result = asyncio.run(get_active_valuation("TEST"))

    assert result.valuation_source == "auto"
    # Same result get_step3_data itself would have returned -- TEST's own
    # fixture lands on PASS (see test_pass_with_real_data_is_not_flagged_as_
    # insufficient above).
    assert result.selected_method == "PASS"


def test_get_active_valuation_ignores_a_saved_but_inactive_custom_valuation(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "TEST", "PSG", json.dumps(_PSG_PARAMS))
        # Deliberately NOT activated.

    result = asyncio.run(get_active_valuation("TEST"))

    assert result.valuation_source == "auto"
    assert result.selected_method == "PASS"


def test_get_active_valuation_overrides_result_fields_only_when_active(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "TEST", "PSG", json.dumps(_PSG_PARAMS))
        activate_ticker_custom_valuation(session, "TEST")

    auto = asyncio.run(get_step3_data("TEST"))
    result = asyncio.run(get_active_valuation("TEST"))

    # PSG: 0.2 * 10.0 * 0.10 * 100 = 20.0; last_close is 100.0 (QUOTE
    # fixture) -> discount_premium_pct = 100/20 - 1 = 4.0 -> overvalued.
    # This is the required PASS-ticker-with-an-active-custom-valuation
    # scenario: Auto genuinely can't value TEST at all, but the active
    # custom valuation still produces a real, non-None verdict.
    assert result.valuation_source == "custom"
    assert result.selected_method == "PSG"
    assert result.intrinsic_value_per_share == pytest.approx(20.0)
    assert result.discount_premium_pct == pytest.approx(4.0)
    assert result.verdict == "overvalued"
    # inputs/method_reasoning/company_type/pass_reason must stay Auto's own,
    # never overridden -- they still describe what Auto's tree actually did.
    assert result.company_type == auto.company_type
    assert result.method_reasoning == auto.method_reasoning
    assert result.pass_reason == auto.pass_reason
    assert result.inputs == auto.inputs


_CF_NORMALIZED_PARAMS = {
    "current_value": 1000.0,
    "growth_yr_1_5": 0.05,
    "growth_yr_6_10": 0.04,
    "growth_yr_11_20": 0.04,
    "discount_rate": 0.08,
    "shares_outstanding": 100.0,
    "total_debt": 200.0,
    "cash_and_st_investments": 50.0,
    "book_value_per_share": None,
    "pb_mean_ratio": None,
    "pb_sd_ratio": None,
    "sales_per_share": None,
    "projected_growth_rate": None,
    "fair_psg_ratio": None,
}


def test_get_active_valuation_supports_cf_normalized_manual_only_method(monkeypatch):
    # CF_NORMALIZED/FCF_NORMALIZED are Manual Calculation/Custom
    # Valuation-only method choices (see CLAUDE.md's Item 3 note) --
    # select_method's own tree never produces either, but a saved, activated
    # Custom Valuation using one must still resolve to a real computed value
    # via the same 20yr engine DCF/DFCF/DNI/DNI_NORMALIZED already share.
    engine = _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "TEST", "CF_NORMALIZED", json.dumps(_CF_NORMALIZED_PARAMS))
        activate_ticker_custom_valuation(session, "TEST")

    result = asyncio.run(get_active_valuation("TEST"))

    expected = run_20yr_engine(
        current_value=1000.0,
        growth_yr_1_5=0.05,
        growth_yr_6_10=0.04,
        growth_yr_11_20=0.04,
        discount_rate=0.08,
        shares_outstanding=100.0,
        total_debt=200.0,
        cash_and_st_investments=50.0,
        fx_rate=1.0,
        last_close=100.0,  # QUOTE fixture's price
    )

    assert result.valuation_source == "custom"
    assert result.selected_method == "CF_NORMALIZED"
    assert result.intrinsic_value_per_share == pytest.approx(expected.intrinsic_value_per_share)
    assert result.discount_premium_pct == pytest.approx(expected.discount_premium_pct)


def test_get_active_valuation_falls_back_to_auto_on_corrupt_saved_json(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_real_data(monkeypatch)
    with Session(engine) as session:
        set_ticker_custom_valuation(session, "TEST", "PSG", "not valid json")
        activate_ticker_custom_valuation(session, "TEST")

    result = asyncio.run(get_active_valuation("TEST"))

    assert result.valuation_source == "auto"
    assert result.selected_method == "PASS"
    assert result.dpu_growth_note is None
