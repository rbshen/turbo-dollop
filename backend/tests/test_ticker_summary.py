import asyncio
from datetime import date, timedelta

from sqlmodel import SQLModel, create_engine

import step2_data
import ticker_summary
from schemas import Step3Inputs, Step3Out
from ticker_summary import get_summary
from ttm import TOTAL_QUARTERS_NEEDED

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
        "yearHigh": 199.62,
        "yearLow": 164.08,
    }
]

FAKE_PRICE_CHANGE = [{"1M": 3.2, "6M": 12.5, "ytd": 15.1, "1Y": 22.4, "5Y": 123.5, "10Y": 1277.8}]

FAKE_RATIOS = [{"priceToEarningsRatio": 30.1}]

FAKE_ESTIMATES = [
    {"date": "2030-09-27", "epsAvg": 13.38},
    {"date": "2029-09-27", "epsAvg": 11.93},
    {"date": "2028-09-27", "epsAvg": 10.70},
    {"date": "2027-09-27", "epsAvg": 9.66},
    {"date": "2026-09-27", "epsAvg": 8.31},
]

# Dates are relative to today, not hardcoded -- a fixed future date
# eventually becomes today's past and silently breaks these tests on a
# schedule (confirmed real: "2026-07-30" as the expected next-earnings
# date broke once the clock passed it). NEXT_EARNINGS_DATE is shared with
# the assertions below so the fixture and the expectation can never drift
# from each other.
_TODAY = date.today()
NEXT_EARNINGS_DATE = _TODAY + timedelta(days=25)
FAKE_EARNINGS = [
    {"date": NEXT_EARNINGS_DATE.isoformat(), "epsActual": None, "epsEstimated": 1.88},
    {"date": (_TODAY - timedelta(days=65)).isoformat(), "epsActual": 2.01, "epsEstimated": 1.95},
    {"date": (_TODAY - timedelta(days=155)).isoformat(), "epsActual": 2.85, "epsEstimated": 2.67},
]

FAKE_BALANCE_SHEET_QUARTERLY = [{"shortTermDebt": 5_000_000_000, "longTermDebt": 95_000_000_000}]

FAKE_INCOME_QUARTERLY = [
    {"ebitda": 30_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
    {"ebitda": 29_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
    {"ebitda": 28_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
    {"ebitda": 27_000_000_000, "interestExpense": 800_000_000, "interestIncome": 50_000_000, "netInterestIncome": -750_000_000},
]

FAKE_ENTERPRISE_VALUES = [{"date": "2026-03-28", "enterpriseValue": 3_900_000_000_000}]

FAKE_RATIOS_TTM = [{"priceToEarningsGrowthRatioTTM": 1.39, "forwardPriceToEarningsGrowthRatioTTM": 3.86}]

FAKE_FINANCIAL_GROWTH = [{"revenueGrowth": 0.08, "netIncomeGrowth": 0.12}]

# Newest-first, matching FMP's actual /historical-price-eod/full ordering
# (confirmed empirically) -- only 3 rows, enough to exercise both the
# 30-calendar-day and 20-trading-day windows without a large fixture.
FAKE_DAILY_PRICES = [
    {"date": "2026-07-24", "close": 333.02, "volume": 47_000_000},
    {"date": "2026-07-23", "close": 320.00, "volume": 50_000_000},
    {"date": "2026-06-20", "close": 300.00, "volume": 60_000_000},  # outside the 30-calendar-day window
]


def test_get_summary_maps_fields_and_caches(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(ticker_summary, "engine", test_engine)
    # get_step2_data manages its own Session(engine) bound to step2_data's
    # own module-level import -- patching only ticker_summary's engine
    # leaves it pointed at the real db, so it'd silently read/write whatever
    # is already cached there instead of this test's fixtures.
    monkeypatch.setattr(step2_data, "engine", test_engine)

    call_count = {
        "profile": 0,
        "quote": 0,
        "price_change": 0,
        "ratios": 0,
        "analyst_estimates": 0,
        "earnings": 0,
        "balance_sheet": 0,
        "income_statement": 0,
        "enterprise_values": 0,
        "ratios_ttm": 0,
        "historical_price_eod": 0,
        "financial_growth": 0,
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
        # Must share Step 4/Step 5/the Financials tab's deeper limit -- a
        # regression back to limit=1 here would win the race on a fresh
        # ticker page load (this is the default tab) and cache a thin
        # 1-row result under the shared cache key for everyone else.
        assert limit == TOTAL_QUARTERS_NEEDED
        return FAKE_BALANCE_SHEET_QUARTERLY

    async def fake_income_statement(ticker, period, limit):
        call_count["income_statement"] += 1
        return FAKE_INCOME_QUARTERLY

    async def fake_enterprise_values(ticker, period, limit):
        call_count["enterprise_values"] += 1
        assert period == "quarter"
        assert limit == 1
        return FAKE_ENTERPRISE_VALUES

    async def fake_ratios_ttm(ticker):
        call_count["ratios_ttm"] += 1
        return FAKE_RATIOS_TTM

    async def fake_historical_price_eod(ticker, from_date, to_date):
        call_count["historical_price_eod"] += 1
        return FAKE_DAILY_PRICES

    async def fake_financial_growth(ticker, period, limit):
        call_count["financial_growth"] += 1
        return FAKE_FINANCIAL_GROWTH

    async def fake_get_step3_data(ticker, cache_only=False, step2_out=None):
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
    monkeypatch.setattr(ticker_summary.fmp_client, "get_enterprise_values", fake_enterprise_values)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_ratios_ttm", fake_ratios_ttm)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_historical_price_eod", fake_historical_price_eod)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_financial_growth", fake_financial_growth)

    summary = asyncio.run(get_summary("aapl"))

    assert summary.ticker == "AAPL"
    assert summary.company_name == "Apple Inc."
    assert summary.exchange == "NASDAQ"
    assert summary.sector == "Technology"
    assert summary.description == "Apple Inc. designs, manufactures, and markets smartphones and related products."
    assert summary.price == 190.5
    assert summary.change_percent == 0.66
    assert summary.market_cap == 3_000_000_000_000
    assert summary.enterprise_value == 3_900_000_000_000
    assert summary.peg_ratio == 1.39
    assert summary.forward_peg_ratio == 3.86
    # marketCap / price (latest quote) -- same formula Step 3's valuation
    # math uses (shares.py::compute_shares_outstanding), so Summary and
    # Step 3 can never disagree.
    assert summary.shares_outstanding == 3_000_000_000_000 / 190.5
    assert summary.shares_outstanding_source == "marketCap / price (latest quote)"
    # FAKE_DAILY_PRICES: most recent row is 2026-07-24; the 2026-06-20 row
    # falls outside its trailing 30-calendar-day window, so only the first
    # two rows count toward the 30-day average volume.
    assert summary.avg_volume_30d == (47_000_000 + 50_000_000) / 2
    # 20-trading-day dollar volume is a positional slice (newest-first) --
    # all 3 fixture rows fall within the first 20, so all 3 count.
    assert summary.avg_dollar_volume_20d == (333.02 * 47_000_000 + 320.00 * 50_000_000 + 300.00 * 60_000_000) / 3
    assert summary.perf_1m == 3.2
    assert summary.perf_6m == 12.5
    assert summary.perf_ytd == 15.1
    assert summary.perf_1y == 22.4
    assert summary.perf_5y == 123.5
    assert summary.perf_10y == 1277.8
    assert summary.week52_high == 199.62
    assert summary.week52_low == 164.08
    assert summary.pe_ratio == 30.1
    assert summary.next_earnings_date is not None and summary.next_earnings_date == NEXT_EARNINGS_DATE
    # Must equal Step 2's own growth_rate exactly (same _project computation,
    # same base year 2026 / target year 2030 four-years-out window) -- this
    # is the regression guard for the bug where a near-duplicate calculation
    # here disagreed with the Step 2 card because it lacked Step 2's
    # future-only date filter and could window off a different base year.
    assert summary.eps_growth_3_5y == ((13.38 / 8.31) ** (1 / 4) - 1) * 100
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
        "enterprise_values": 1,
        "ratios_ttm": 1,
        "historical_price_eod": 1,
        "financial_growth": 1,
    }
    assert call_count == expected_call_count

    # Second call within the staleness window should hit the cache for
    # everything except quote -- price is fetched fresh on every live
    # ticker-page view (see cache.force_fetch usage in get_summary), quote's
    # own independent cache key, so this doesn't force a refetch of anything
    # else bundled into the summary call.
    asyncio.run(get_summary("aapl"))
    assert call_count == {**expected_call_count, "quote": 2}

    # cache_only=True (the Screener recompute path) must still make zero FMP
    # calls, including for quote -- the force-fetch above only applies to the
    # live (cache_only=False) path.
    asyncio.run(get_summary("aapl", cache_only=True))
    assert call_count == {**expected_call_count, "quote": 2}


def test_next_earnings_date_picks_nearest_unreported():
    assert ticker_summary._next_earnings_date(FAKE_EARNINGS) == NEXT_EARNINGS_DATE
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
    # be found correctly -- the fix only excludes PAST null rows. Dates are
    # relative to today for the same reason as FAKE_EARNINGS above.
    future_date = _TODAY + timedelta(days=10)
    normal = [
        {"date": (_TODAY - timedelta(days=185)).isoformat(), "epsActual": 2.4},
        {"date": (_TODAY - timedelta(days=95)).isoformat(), "epsActual": 2.1},
        {"date": future_date.isoformat(), "epsActual": None},
    ]
    assert ticker_summary._next_earnings_date(normal) == future_date
