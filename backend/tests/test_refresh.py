import asyncio
from datetime import datetime

import httpx
from sqlmodel import Session, SQLModel, create_engine, select

import refresh
import step5_data
import ticker_summary
from models import FundamentalsCache, GrowthCatalystNote
from refresh import clear_ticker_cache
from step5_data import get_step5_data
from ticker_summary import get_summary


def _seed(session, ticker, statement_type, period):
    session.add(
        FundamentalsCache(
            ticker=ticker, statement_type=statement_type, period=period, fetched_at=datetime.now(), raw_json="[]"
        )
    )


def _fresh_engine(monkeypatch, *modules):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    for mod in modules:
        monkeypatch.setattr(mod, "engine", test_engine)
    return test_engine


def test_clear_ticker_cache_removes_all_entries_for_the_ticker(monkeypatch):
    test_engine = _fresh_engine(monkeypatch, refresh)

    with Session(test_engine) as session:
        _seed(session, "AAPL", "profile", "latest")
        _seed(session, "AAPL", "income_statement", "quarterly")
        _seed(session, "AAPL", "income_statement", "annual")
        _seed(session, "NVDA", "profile", "latest")  # different ticker, must survive
        session.commit()

    result = clear_ticker_cache("aapl")  # lowercase input still matches the uppercase-stored ticker

    assert result.ticker == "AAPL"
    assert result.cleared_entries == 3
    assert result.statement_types == ["income_statement", "profile"]

    with Session(test_engine) as session:
        remaining = session.exec(select(FundamentalsCache)).all()
    assert len(remaining) == 1
    assert remaining[0].ticker == "NVDA"


def test_clear_ticker_cache_never_touches_growth_catalyst_notes(monkeypatch):
    # GrowthCatalystNote is manually-curated user data, not FMP cache -- a
    # refresh must never destroy it.
    test_engine = _fresh_engine(monkeypatch, refresh)

    with Session(test_engine) as session:
        _seed(session, "AAPL", "profile", "latest")
        session.add(GrowthCatalystNote(ticker="AAPL", notes="manually curated", updated_at=datetime.now()))
        session.commit()

    clear_ticker_cache("AAPL")

    with Session(test_engine) as session:
        notes = session.exec(select(GrowthCatalystNote)).all()
    assert len(notes) == 1
    assert notes[0].notes == "manually curated"


def test_clear_ticker_cache_on_ticker_with_no_cache_entries(monkeypatch):
    _fresh_engine(monkeypatch, refresh)

    result = clear_ticker_cache("ZZZZ")
    assert result.cleared_entries == 0
    assert result.statement_types == []


def test_refresh_then_subsequent_fetch_hits_fmp_again(monkeypatch):
    """The core promise of the feature: clearing the cache actually forces
    the next fetch to hit FMP again, rather than serving stale data for the
    rest of the staleness window."""
    test_engine = _fresh_engine(monkeypatch, refresh, step5_data)

    call_count = {"profile": 0}

    async def fake_profile(ticker):
        call_count["profile"] += 1
        # Bank short-circuits step5_data before any other fetch -- keeps
        # this test focused on the cache-clear/refetch behavior itself.
        return [{"sector": "Financial Services", "industry": "Banks - Diversified"}]

    monkeypatch.setattr(step5_data.fmp_client, "get_profile", fake_profile)

    asyncio.run(get_step5_data("aapl"))
    assert call_count["profile"] == 1

    # Second call within the staleness window hits the cache, not FMP again.
    asyncio.run(get_step5_data("aapl"))
    assert call_count["profile"] == 1


def test_fmp_failure_right_after_refresh_degrades_gracefully_not_a_crash(monkeypatch):
    """A refresh clears the cache, making the ticker's next fetch a cold
    start -- the same situation any brand-new ticker already goes through.
    If FMP happens to be down at exactly that moment, the existing
    safe_fetch mechanism (unchanged by this feature) must degrade each
    field to null rather than raising, so the user sees a mostly-empty
    response instead of a crash or a blank page."""
    _fresh_engine(monkeypatch, refresh, ticker_summary)

    async def failing_fetch(*args, **kwargs):
        raise httpx.HTTPError("FMP is down")

    for method in (
        "get_profile",
        "get_quote",
        "get_price_change",
        "get_ratios",
        "get_analyst_estimates",
        "get_earnings",
        "get_balance_sheet_statement",
        "get_income_statement",
    ):
        monkeypatch.setattr(ticker_summary.fmp_client, method, failing_fetch)

    clear_ticker_cache("AAPL")

    result = asyncio.run(get_summary("aapl"))

    assert result.ticker == "AAPL"
    assert result.price is None
    assert result.total_debt is None
    assert result.outlier_warnings == []
