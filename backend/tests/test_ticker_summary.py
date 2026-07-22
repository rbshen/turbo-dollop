import asyncio

from sqlmodel import SQLModel, create_engine

import ticker_summary
from schemas import Step3Inputs, Step3Out
from ticker_summary import get_summary

# get_summary sources fair_value_price/verdict/method from Step 3's own
# result (see ticker_summary.py::get_summary). Step 3's own fetch pipeline
# (get_step3_data) has its own extensive mocking needs and deserves its own
# dedicated test coverage -- this test's job is ticker_summary's field
# mapping, so get_step3_data itself is monkeypatched wholesale rather than
# reconstructed here, keeping this test isolated from Step 3's internals.
FAKE_STEP3_OUT = Step3Out(
    ticker="AAPL",
    company_type="Standard",
    selected_method="DCF",
    inputs=Step3Inputs(current_value=100_000_000_000.0, growth_yr_11_20=0.04, last_close=190.5),
    intrinsic_value_per_share=200.0,
    discount_premium_pct=-0.0475,
    verdict="undervalued",
)

FAKE_PROFILE = [
    {
        "companyName": "Apple Inc.",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "description": "Apple Inc. designs, manufactures, and markets smartphones and related products.",
        "beta": 1.2,
        "mktCap": 3_000_000_000_000,
    }
]

FAKE_QUOTE = [
    {
        "price": 190.5,
        "change": 1.25,
        "changePercentage": 0.66,
        "marketCap": 3_000_000_000_000,
    }
]

FAKE_PRICE_CHANGE = [{"1M": 3.2, "6M": 12.5}]

FAKE_RATIOS = [{"priceToEarningsRatio": 30.1}]

FAKE_ESTIMATES = [
    {"date": "2030-09-27", "epsAvg": 13.38},
    {"date": "2029-09-27", "epsAvg": 11.93},
    {"date": "2028-09-27", "epsAvg": 10.70},
    {"date": "2027-09-27", "epsAvg": 9.66},
    {"date": "2026-09-27", "epsAvg": 8.31},
]

FAKE_EARNINGS = [
    {"date": "2026-07-30", "epsActual": None, "epsEstimated": 1.88},
    {"date": "2026-04-30", "epsActual": 2.01, "epsEstimated": 1.95},
    {"date": "2026-01-29", "epsActual": 2.85, "epsEstimated": 2.67},
]

FAKE_BALANCE_SHEET_QUARTERLY = [{"shortTermDebt": 5_000_000_000, "longTermDebt": 95_000_000_000}]

FAKE_INCOME_QUARTERLY = [
    {"ebitda": 30_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
    {"ebitda": 29_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
    {"ebitda": 28_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
    {"ebitda": 27_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
]


def test_get_summary_maps_fields_and_caches(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(ticker_summary, "engine", test_engine)

    call_count = {
        "profile": 0,
        "quote": 0,
        "price_change": 0,
        "ratios": 0,
        "analyst_estimates": 0,
        "earnings": 0,
        "balance_sheet": 0,
        "income_statement": 0,
    }

    async def fake_profile(ticker):
        call_count["profile"] += 1
        return FAKE_PROFILE

    async def fake_quote(ticker):
        call_count["quote"] += 1
        return FAKE_QUOTE

    async def fake_price_change(ticker):
        call_count["price_change"] += 1
        return FAKE_PRICE_CHANGE

    async def fake_ratios(ticker):
        call_count["ratios"] += 1
        return FAKE_RATIOS

    async def fake_estimates(ticker):
        call_count["analyst_estimates"] += 1
        return FAKE_ESTIMATES

    async def fake_earnings(ticker):
        call_count["earnings"] += 1
        return FAKE_EARNINGS

    async def fake_balance_sheet_statement(ticker, period, limit):
        call_count["balance_sheet"] += 1
        return FAKE_BALANCE_SHEET_QUARTERLY

    async def fake_income_statement(ticker, period, limit):
        call_count["income_statement"] += 1
        return FAKE_INCOME_QUARTERLY

    async def fake_get_step3_data(ticker, cache_only=False):
        return FAKE_STEP3_OUT

    monkeypatch.setattr(ticker_summary, "get_step3_data", fake_get_step3_data)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_quote", fake_quote)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_price_change", fake_price_change)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_analyst_estimates", fake_estimates)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_earnings", fake_earnings)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_income_statement", fake_income_statement)

    summary = asyncio.run(get_summary("aapl"))

    assert summary.ticker == "AAPL"
    assert summary.company_name == "Apple Inc."
    assert summary.exchange == "NASDAQ"
    assert summary.sector == "Technology"
    assert summary.description == "Apple Inc. designs, manufactures, and markets smartphones and related products."
    assert summary.price == 190.5
    assert summary.change_percent == 0.66
    assert summary.market_cap == 3_000_000_000_000
    assert summary.perf_1m == 3.2
    assert summary.perf_6m == 12.5
    assert summary.pe_ratio == 30.1
    assert summary.next_earnings_date is not None and summary.next_earnings_date.isoformat() == "2026-07-30"
    assert summary.eps_growth_3_5y is not None
    assert summary.eps_growth_3_5y > 0
    assert summary.fair_value_price == 200.0
    assert summary.fair_value_verdict == "undervalued"
    assert summary.fair_value_method == "DCF"
    # Same shared calculation Step 5's debt ratios use (backend/debt_metrics.py):
    # total_debt = 5B + 95B; ebitda_ttm = 30+29+28+27B; interest expense TTM
    # = 800M*4; interest income TTM = 50M*4.
    assert summary.total_debt == 100_000_000_000
    assert summary.ebitda_ttm == 114_000_000_000
    assert summary.interest_expense_ttm == 3_200_000_000
    assert summary.interest_income_ttm == 200_000_000
    expected_call_count = {
        "profile": 1,
        "quote": 1,
        "price_change": 1,
        "ratios": 1,
        "analyst_estimates": 1,
        "earnings": 1,
        "balance_sheet": 1,
        "income_statement": 1,
    }
    assert call_count == expected_call_count

    # Second call within the staleness window should hit the cache, not FMP again.
    asyncio.run(get_summary("aapl"))
    assert call_count == expected_call_count


def test_eps_cagr_requires_at_least_two_positive_estimates():
    assert ticker_summary._compute_eps_cagr([]) is None
    assert ticker_summary._compute_eps_cagr([{"date": "2026-12-31", "epsAvg": 1.0}]) is None
    assert (
        ticker_summary._compute_eps_cagr(
            [
                {"date": "2026-12-31", "epsAvg": -1.0},
                {"date": "2027-12-31", "epsAvg": -2.0},
            ]
        )
        is None
    )


def test_eps_cagr_prefers_estimate_closest_to_four_years_out():
    # base=2026 (eps 8), then 2027/2028/2029/2030 — 2030 is 4y out, should be preferred.
    cagr = ticker_summary._compute_eps_cagr(
        [
            {"date": "2026-09-27", "epsAvg": 8.0},
            {"date": "2027-09-27", "epsAvg": 9.0},
            {"date": "2028-09-27", "epsAvg": 10.0},
            {"date": "2029-09-27", "epsAvg": 11.0},
            {"date": "2030-09-27", "epsAvg": 16.0},
        ]
    )
    assert cagr == (16.0 / 8.0) ** (1 / 4) - 1


def test_next_earnings_date_picks_nearest_unreported():
    assert ticker_summary._next_earnings_date(FAKE_EARNINGS).isoformat() == "2026-07-30"
    assert ticker_summary._next_earnings_date([]) is None


def test_next_earnings_date_returns_none_for_etf_shaped_data():
    # ETFs (SPY, QQQ, ...) never report earnings, so FMP returns historical
    # distribution/dividend rows with epsActual always null. Without also
    # requiring the date to be in the future, `min()` over the entire
    # history picks the OLDEST row -- a garbage decades-old "next earnings
    # date" -- instead of correctly reading as "no earnings".
    etf_shaped = [
        {"date": "2010-03-19", "epsActual": None},
        {"date": "2015-06-19", "epsActual": None},
        {"date": "2020-12-18", "epsActual": None},
    ]
    assert ticker_summary._next_earnings_date(etf_shaped) is None


def test_next_earnings_date_still_finds_a_genuine_future_date_among_null_rows():
    # Regression guard: a normal ticker with a real upcoming earnings date
    # (also epsActual=None, since it hasn't been reported yet) must still
    # be found correctly -- the fix only excludes PAST null rows.
    normal = [
        {"date": "2025-01-30", "epsActual": 2.4},
        {"date": "2025-04-30", "epsActual": 2.1},
        {"date": "2026-08-15", "epsActual": None},
    ]
    assert ticker_summary._next_earnings_date(normal).isoformat() == "2026-08-15"
