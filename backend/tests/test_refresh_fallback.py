"""Refresh (POST /api/tickers/{t}/refresh) when the live statement fetch fails: serve the cached statement rows and never
persist a degraded TickerScore. The chain under test is real (ticker_refresh -> clear_ticker_cache -> compute_ticker_score
-> the real step functions); only the FMP client is faked, and every module's own `engine` points at one in-memory DB."""

import json
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.speculative_growth_data as speculative_growth_data
import data.step1_data as step1_data
import data.step2_data as step2_data
import data.step3_data as step3_data
import data.step4_data as step4_data
import data.step5_data as step5_data
import data.ticker_score as ticker_score
import data.ticker_summary as ticker_summary
import pipeline.refresh as refresh
from clients.fmp_client import fmp_client
from core.history_merge import INVALIDATED_AT
from core.models import FundamentalsCache, TickerScore

MODULES = (
    main, refresh, ticker_score, step1_data, step2_data, step3_data, step4_data, step5_data, ticker_summary, speculative_growth_data,
)
PROFILE = [{"symbol": "AAPL", "companyName": "Apple Inc.", "sector": "Technology", "industry": "Consumer Electronics", "marketCap": 3e12}]


def income_row(year, quarter=None):
    period = quarter or "FY"
    end = f"{year}-{('03-31', '06-30', '09-30', '12-31')[int(quarter[1]) - 1] if quarter else '12-31'}"
    return {
        "date": end, "fiscalYear": str(year), "period": period, "revenue": 100e9 * (1 + (year - 2020) * 0.1), "netIncome": 20e9,
        "operatingIncome": 25e9, "grossProfit": 45e9, "ebitda": 30e9, "interestExpense": 1e9, "weightedAverageShsOutDil": 15e9, "eps": 1.3,
    }


def cash_flow_row(year, quarter=None):
    row = income_row(year, quarter)
    return {
        "date": row["date"], "fiscalYear": row["fiscalYear"], "period": row["period"], "netIncome": 20e9,
        "netCashProvidedByOperatingActivities": 25e9, "freeCashFlow": 20e9, "capitalExpenditure": -5e9,
        "netCashProvidedByInvestingActivities": -3e9, "netCashProvidedByFinancingActivities": -10e9,
    }


def balance_row(year, quarter=None):
    row = income_row(year, quarter)
    return {
        "date": row["date"], "fiscalYear": row["fiscalYear"], "period": row["period"], "totalAssets": 400e9, "totalLiabilities": 250e9,
        "totalCurrentAssets": 140e9, "totalCurrentLiabilities": 120e9, "shortTermDebt": 10e9, "longTermDebt": 90e9, "totalDebt": 100e9,
        "cashAndCashEquivalents": 30e9, "totalStockholdersEquity": 150e9, "netReceivables": 30e9,
    }


ANNUAL = [2025, 2024, 2023, 2022, 2021, 2020]
QUARTERLY = [(y, f"Q{q}") for y in (2025, 2024, 2023) for q in (4, 3, 2, 1)]


@pytest.fixture()
def engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(test_engine)
    for module in MODULES:
        monkeypatch.setattr(module, "engine", test_engine)
    return test_engine


def seed_cached_statements(engine, fetched_at=INVALIDATED_AT):
    rows = {
        ("income_statement", "annual"): [income_row(y) for y in ANNUAL],
        ("income_statement", "quarterly"): [income_row(y, q) for y, q in QUARTERLY],
        ("balance_sheet_statement", "annual"): [balance_row(y) for y in ANNUAL],
        ("balance_sheet_statement", "quarterly"): [balance_row(y, q) for y, q in QUARTERLY],
        ("cash_flow_statement", "annual"): [cash_flow_row(y) for y in ANNUAL],
        ("cash_flow_statement", "quarterly"): [cash_flow_row(y, q) for y, q in QUARTERLY],
    }
    with Session(engine) as session:
        for (statement_type, period), payload in rows.items():
            session.add(FundamentalsCache(ticker="AAPL", statement_type=statement_type, period=period, fetched_at=fetched_at, raw_json=json.dumps(payload)))
        session.commit()


def seed_good_score(engine):
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", overall_score=88, overall_verdict="Strong Pass", step1_score=90, computed_at=datetime(2026, 10, 1)))
        session.commit()


def fake_fmp(monkeypatch, failing=True):
    """Profile answers; every other endpoint (the statements, quote, ratios...) fails like an outage / rate limit."""
    calls = []

    async def get(endpoint, params=None, group=None):
        calls.append(endpoint)
        if endpoint == "/profile":
            return PROFILE
        if failing:
            raise httpx.ReadTimeout("FMP timed out")
        return []

    monkeypatch.setattr(fmp_client, "get", get)
    return calls


def bars_answer_empty(monkeypatch):
    """The price-history fetch (5y vs SPY) answers, so it is not the failure under test (conftest blocks it by default)."""

    async def empty(*_args, **_kwargs):
        return []

    monkeypatch.setattr(fmp_client, "get_historical_price_eod", empty)


def score_row(engine) -> TickerScore | None:
    with Session(engine) as session:
        return session.get(TickerScore, "AAPL")


def statement_rows(engine):
    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache).where(FundamentalsCache.statement_type.in_(["income_statement", "cash_flow_statement", "balance_sheet_statement"]))).all()
        return {(r.statement_type, r.period): (r.raw_json, r.fetched_at) for r in rows}


def refresh_endpoint():
    with TestClient(main.app) as client:
        return client.post("/api/tickers/AAPL/refresh")


def test_a_statement_fetch_failure_during_refresh_must_not_overwrite_a_good_score_with_a_degraded_one(engine, monkeypatch):
    seed_cached_statements(engine)  # the cached rows Refresh keeps (marked invalid)
    seed_good_score(engine)
    before = statement_rows(engine)
    fake_fmp(monkeypatch)

    response = refresh_endpoint()

    assert response.status_code == 200
    row = score_row(engine)
    assert row.overall_score == 88 and row.step1_score == 90  # untouched: nothing degraded was persisted
    assert statement_rows(engine) == before  # statement rows kept as they were, still marked invalid
    assert all(fetched_at == INVALIDATED_AT for _, fetched_at in before.values())


def test_the_cached_statement_rows_are_served_to_the_steps_when_only_the_statement_fetches_fail(engine, monkeypatch):
    """Quote, ratios and the rest answer; only the statements fail. The Refresh serves the kept (stale-marked) statement
    rows, so the score is computed from them rather than from nothing, and is persisted."""
    seed_cached_statements(engine)
    seed_good_score(engine)
    bars_answer_empty(monkeypatch)

    async def get(endpoint, params=None, group=None):
        if endpoint == "/profile":
            return PROFILE
        if endpoint in ("/income-statement", "/cash-flow-statement", "/balance-sheet-statement"):
            raise httpx.HTTPStatusError("429", request=httpx.Request("GET", "https://x"), response=httpx.Response(429))
        return []

    monkeypatch.setattr(fmp_client, "get", get)
    before = statement_rows(engine)

    response = refresh_endpoint()

    assert response.status_code == 200
    row = score_row(engine)
    assert row.step1_score is not None  # built from the cached income + cash-flow rows, not from nothing
    assert row.computed_at > datetime(2026, 10, 2)  # it was persisted (a fresh computation)
    assert statement_rows(engine) == before  # rows untouched: not re-stamped, still marked invalid


def test_a_failure_with_nothing_cached_keeps_the_previous_score_row(engine, monkeypatch):
    seed_good_score(engine)  # no statement rows cached at all
    fake_fmp(monkeypatch)

    response = refresh_endpoint()

    assert response.status_code == 200
    assert score_row(engine).overall_score == 88
    assert statement_rows(engine) == {}


def test_a_ticker_without_a_previous_score_gets_none_written_on_a_failed_refresh(engine, monkeypatch):
    seed_cached_statements(engine)
    fake_fmp(monkeypatch)

    refresh_endpoint()

    assert score_row(engine) is None


def test_a_successful_refresh_still_persists_and_rewrites_the_statement_rows(engine, monkeypatch):
    seed_cached_statements(engine)
    bars_answer_empty(monkeypatch)

    async def get(endpoint, params=None, group=None):
        if endpoint == "/profile":
            return PROFILE
        if endpoint == "/income-statement":
            return [income_row(y, q) for y, q in QUARTERLY] if (params or {}).get("period") == "quarter" else [income_row(y) for y in ANNUAL]
        if endpoint == "/cash-flow-statement":
            return [cash_flow_row(y, q) for y, q in QUARTERLY] if (params or {}).get("period") == "quarter" else [cash_flow_row(y) for y in ANNUAL]
        return []

    monkeypatch.setattr(fmp_client, "get", get)

    refresh_endpoint()

    assert score_row(engine) is not None
    assert all(fetched_at > INVALIDATED_AT for _, fetched_at in statement_rows(engine).values())  # re-fetched and stamped


def test_outside_the_refresh_a_failed_fetch_still_returns_empty_and_persists_as_before(engine, monkeypatch):
    """The fallback is opt-in (track_fetch_failures): the nightly jobs, page loads and every other caller keep today's
    behaviour, including the cached row being bypassed by safe_fetch's {}."""
    import asyncio
    from core.cache import get_or_fetch_earnings_aware, safe_fetch

    seed_cached_statements(engine)

    async def failing():
        raise httpx.ReadTimeout("slow")

    with Session(engine) as session:
        result = asyncio.run(
            safe_fetch("x", get_or_fetch_earnings_aware(session, "AAPL", "income_statement", "annual", failing, 7, None))
        )

    assert result == {}


def test_the_tracker_is_scoped_to_the_block_and_records_both_kinds_of_failure(engine):
    import asyncio
    from core.cache import current_fetch_failure_tracker, get_or_fetch, safe_fetch, track_fetch_failures

    seed_cached_statements(engine)

    async def failing():
        raise httpx.ReadTimeout("slow")

    async def run():
        with Session(engine) as session:
            with track_fetch_failures() as tracker:
                cached = await safe_fetch("a", get_or_fetch(session, "AAPL", "income_statement", "annual", failing, 7))
                missing = await safe_fetch("b", get_or_fetch(session, "AAPL", "ratios", "annual_10y", failing, 7))
            return tracker, cached, missing

    tracker, cached, missing = asyncio.run(run())

    assert isinstance(cached, list) and len(cached) == len(ANNUAL)  # served from the cached row
    assert missing == {} and tracker.unrecovered == ["b"] and tracker.served_from_cache == ["income_statement/annual"]
    assert current_fetch_failure_tracker() is None
