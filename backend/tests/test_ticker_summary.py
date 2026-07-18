import asyncio

from sqlmodel import SQLModel, create_engine

import ticker_summary
from ticker_summary import get_summary

FAKE_PROFILE = [
    {
        "companyName": "Apple Inc.",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "industry": "Consumer Electronics",
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


def test_get_summary_maps_fields_and_caches(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(ticker_summary, "engine", test_engine)

    call_count = {"profile": 0, "quote": 0, "price_change": 0, "ratios": 0, "analyst_estimates": 0, "earnings": 0}

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

    monkeypatch.setattr(ticker_summary.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_quote", fake_quote)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_price_change", fake_price_change)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_ratios", fake_ratios)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_analyst_estimates", fake_estimates)
    monkeypatch.setattr(ticker_summary.fmp_client, "get_earnings", fake_earnings)

    summary = asyncio.run(get_summary("aapl"))

    assert summary.ticker == "AAPL"
    assert summary.company_name == "Apple Inc."
    assert summary.exchange == "NASDAQ"
    assert summary.sector == "Technology"
    assert summary.price == 190.5
    assert summary.change_percent == 0.66
    assert summary.market_cap == 3_000_000_000_000
    assert summary.perf_1m == 3.2
    assert summary.perf_6m == 12.5
    assert summary.pe_ratio == 30.1
    assert summary.next_earnings_date is not None and summary.next_earnings_date.isoformat() == "2026-07-30"
    assert summary.eps_growth_3_5y is not None
    assert summary.eps_growth_3_5y > 0
    assert summary.fair_value_price == 209.55
    assert summary.fair_value_verdict == "undervalued"
    assert call_count == {"profile": 1, "quote": 1, "price_change": 1, "ratios": 1, "analyst_estimates": 1, "earnings": 1}

    # Second call within the staleness window should hit the cache, not FMP again.
    asyncio.run(get_summary("aapl"))
    assert call_count == {"profile": 1, "quote": 1, "price_change": 1, "ratios": 1, "analyst_estimates": 1, "earnings": 1}


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
