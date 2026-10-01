"""get_summary's ETF short-circuit: once the profile says isEtf/isFund the stock-only fetches (statements,
ratios, financial growth, earnings, enterprise values, Step 2 / Step 3) are skipped and no empty cached
row is written; a stock still makes every one of them.

Every FMP client method is replaced with a counting fake, and every module's own `engine` reference is
patched to one fresh in-memory engine (the repo's per-module engine-isolation convention)."""

import asyncio
import sys
from collections import Counter

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.db as core_db
from clients.fmp_client import FMPClient, fmp_client
from core.exceptions import TickerNotFoundError
from core.models import FundamentalsCache
from data.ticker_summary import get_summary

ETF_PROFILE = [{"companyName": "SPDR Gold Shares", "exchange": "AMEX", "isEtf": True, "isFund": False, "beta": 0.45}]
FUND_PROFILE = [{"companyName": "Some Mutual Fund", "exchange": "NASDAQ", "isEtf": False, "isFund": True}]
STOCK_PROFILE = [{"companyName": "Apple Inc.", "exchange": "NASDAQ", "isEtf": False, "isFund": False, "sector": "Technology"}]
QUOTE = [{"price": 382.76, "change": 1.92, "changePercentage": 0.5, "marketCap": 135e9, "yearHigh": 509.7, "yearLow": 351.4}]
PRICE_CHANGE = [{"1M": 3.2, "6M": 12.5, "ytd": -3.4, "1Y": 20.0, "5Y": 60.0, "10Y": 200.0}]
DAILY = [{"date": "2026-10-01", "close": 382.0, "volume": 5_000_000}, {"date": "2026-09-30", "close": 380.0, "volume": 6_000_000}]

# What FMP answers for a stock-only endpoint on a fund.
STOCK_ONLY_METHODS = (
    "get_earnings", "get_ratios", "get_balance_sheet_statement", "get_income_statement", "get_cash_flow_statement",
    "get_enterprise_values", "get_ratios_ttm", "get_financial_growth", "get_analyst_estimates", "get_key_metrics",
    "get_key_metrics_ttm", "get_forex_quote",
)


def _install(monkeypatch, profile):
    """Fresh in-memory engine on every module that holds its own `engine`, and a counting fake for every
    FMPClient get_* method. Returns (engine, Counter of calls by method name)."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    real_engine = core_db.engine
    for module in list(sys.modules.values()):
        if module is not core_db and getattr(module, "engine", None) is real_engine:
            monkeypatch.setattr(module, "engine", engine)

    calls: Counter = Counter()
    answers = {"get_profile": profile, "get_quote": QUOTE, "get_price_change": PRICE_CHANGE, "get_historical_price_eod": DAILY}

    def fake(name):
        async def _call(*_args, **_kwargs):
            calls[name] += 1
            return answers.get(name, [])

        return _call

    for name in dir(FMPClient):
        if name.startswith("get_") and callable(getattr(FMPClient, name)):
            monkeypatch.setattr(fmp_client, name, fake(name))
    return engine, calls


def _cached(engine) -> dict[tuple[str, str, str], str]:
    with Session(engine) as session:
        return {(r.ticker, r.statement_type, r.period): r.raw_json for r in session.exec(select(FundamentalsCache)).all()}


def test_an_etf_makes_no_stock_only_calls_and_writes_no_empty_rows(monkeypatch):
    engine, calls = _install(monkeypatch, ETF_PROFILE)

    summary = asyncio.run(get_summary("GLD"))

    assert summary.is_etf and summary.company_name == "SPDR Gold Shares"
    assert [name for name in calls if name in STOCK_ONLY_METHODS] == []
    # Everything the ETF header / Overview / score row need still comes back.
    assert summary.price == 382.76 and summary.change_percent == 0.5 and summary.exchange == "AMEX"
    assert summary.beta == 0.45 and summary.week52_high == 509.7 and summary.week52_low == 351.4
    assert summary.perf_1y == 20.0 and summary.avg_volume_30d == 5_500_000
    assert set(calls) == {"get_profile", "get_quote", "get_price_change", "get_historical_price_eod"}
    cached = _cached(engine)
    assert not [key for key, raw in cached.items() if raw == "[]"]
    assert {key[1] for key in cached} == {"profile", "quote", "price_change", "historical_price_eod"}


def test_a_fund_flagged_isfund_is_short_circuited_too(monkeypatch):
    _, calls = _install(monkeypatch, FUND_PROFILE)
    summary = asyncio.run(get_summary("FUNDX"))
    assert summary.is_etf
    assert [name for name in calls if name in STOCK_ONLY_METHODS] == []


def test_the_profile_is_fetched_first_on_the_very_first_open_of_an_etf(monkeypatch):
    _install(monkeypatch, ETF_PROFILE)
    order: list[str] = []

    def ordered(name):
        original = getattr(fmp_client, name)

        async def _call(*args, **kwargs):
            order.append(name)
            return await original(*args, **kwargs)

        return _call

    for name in dir(FMPClient):
        if name.startswith("get_") and callable(getattr(FMPClient, name)):
            monkeypatch.setattr(fmp_client, name, ordered(name))
    asyncio.run(get_summary("QQQ"))
    assert order[0] == "get_profile"
    assert "get_earnings" not in order


def test_a_stock_still_makes_every_stock_only_call(monkeypatch):
    _, calls = _install(monkeypatch, STOCK_PROFILE)

    asyncio.run(get_summary("AAPL"))

    for name in (
        "get_earnings", "get_ratios", "get_balance_sheet_statement", "get_income_statement", "get_enterprise_values",
        "get_ratios_ttm", "get_financial_growth", "get_analyst_estimates",
    ):
        assert calls[name] >= 1, name


def test_a_second_etf_open_makes_no_fmp_call_for_cached_rows(monkeypatch):
    _, calls = _install(monkeypatch, ETF_PROFILE)
    asyncio.run(get_summary("GLD"))
    calls.clear()
    asyncio.run(get_summary("GLD"))
    # Only the live quote (force-fetched on every ticker-page view) goes out again.
    assert set(calls) == {"get_quote"}


def test_the_cache_only_path_skips_the_stock_reads_for_an_etf_and_calls_nothing(monkeypatch):
    engine, calls = _install(monkeypatch, ETF_PROFILE)
    asyncio.run(get_summary("GLD"))
    calls.clear()
    before = _cached(engine)

    summary = asyncio.run(get_summary("GLD", cache_only=True))

    assert summary.is_etf and summary.price == 382.76
    assert not calls
    assert _cached(engine) == before


def test_an_unknown_ticker_still_404s_before_anything_else(monkeypatch):
    _, calls = _install(monkeypatch, [])
    with pytest.raises(TickerNotFoundError):
        asyncio.run(get_summary("ZZZZ"))
    assert set(calls) == {"get_profile"}
