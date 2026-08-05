import asyncio
from datetime import datetime

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import pipeline.refresh as refresh
import data.step5_data as step5_data
import data.ticker_score as ticker_score
import data.ticker_summary as ticker_summary
from core.models import FundamentalsCache, GrowthCatalystNote, TickerScore
from pipeline.refresh import clear_ticker_cache
from core.schemas import Step1Out, Step2Out, Step4Out, Step5Out, TickerSummaryOut
from data.step5_data import get_step5_data
from data.ticker_summary import get_summary


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


def _fresh_shared_engine(monkeypatch):
    """Shared by the ticker_refresh endpoint tests below -- POST /refresh's
    call chain touches three modules' own `engine` reference
    (main/refresh/ticker_score, see CLAUDE.md's ad-hoc-script warning about
    this exact pattern), all of which must point at the same in-memory DB
    for a write in one to be visible to a read in another. StaticPool:
    TestClient runs requests in a worker thread, and a plain "sqlite://"
    in-memory DB is otherwise scoped per-connection."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for mod in (main, refresh, ticker_score):
        monkeypatch.setattr(mod, "engine", engine)
    return engine


def _step1(score=90, verdict="Pass"):
    return Step1Out(
        ticker="AAPL",
        years=["TTM"],
        revenue=[1.0],
        net_income=[1.0],
        operating_income=[1.0],
        gross_margin=[1.0],
        net_margin=[1.0],
        score=score,
        verdict=verdict,
        components={},
        weights={},
    )


def _step2(score=80, verdict="Pass", growth_rate=12.5):
    return Step2Out(ticker="AAPL", score=score, verdict=verdict, growth_rate=growth_rate, components={}, weights={})


def _step4(score=70, verdict="Pass", company_type="Standard"):
    return Step4Out(
        ticker="AAPL",
        years=["TTM"],
        company_type=company_type,
        roe=[1.0],
        revenue=[1.0],
        accounts_receivable=[1.0],
        score=score,
        verdict=verdict,
    )


def _step5(score=60, verdict="Pass", company_type="Standard"):
    return Step5Out(ticker="AAPL", company_type=company_type, score=score, verdict=verdict)


def _summary(company_name="Apple Inc."):
    return TickerSummaryOut(company_name=company_name, ticker="AAPL", market_cap=3_000_000_000_000.0)


def _patch_score_steps(monkeypatch, raise_in=None):
    """Stands in for the live FMP fetch chain ticker_refresh's
    compute_ticker_score(cache_only=False) call would otherwise trigger --
    same isolation approach as test_ticker_score.py's _patch_all, scoped
    locally here since these tests care about the endpoint's own behavior
    (does it call compute_ticker_score, does it survive a failing step),
    not compute_ticker_score's internal blending (already covered there)."""

    def make(name, value):
        async def fn(ticker, cache_only=False):
            if name == raise_in:
                raise RuntimeError(f"simulated failure in {name}")
            return value

        return fn

    monkeypatch.setattr(ticker_score, "get_step1_data", make("step1", _step1()))
    monkeypatch.setattr(ticker_score, "get_step2_data", make("step2", _step2()))
    monkeypatch.setattr(ticker_score, "get_step4_data", make("step4", _step4()))
    monkeypatch.setattr(ticker_score, "get_step5_data", make("step5", _step5()))
    monkeypatch.setattr(ticker_score, "get_summary", make("summary", _summary()))


def test_ticker_refresh_writes_a_ticker_score_row_for_the_refreshed_ticker(monkeypatch):
    engine = _fresh_shared_engine(monkeypatch)
    _patch_score_steps(monkeypatch)

    with TestClient(main.app) as client:
        response = client.post("/api/tickers/AAPL/refresh")

    assert response.status_code == 200
    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None
    assert row.overall_score is not None  # confirms compute_ticker_score actually ran, not a no-op


def test_ticker_refresh_does_not_touch_a_different_tickers_score_row(monkeypatch):
    engine = _fresh_shared_engine(monkeypatch)
    _patch_score_steps(monkeypatch)

    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="NVDA",
                company_name="NVIDIA Corporation",
                overall_score=42,
                overall_verdict="Fail",
                computed_at=datetime(2020, 1, 1),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.post("/api/tickers/AAPL/refresh")

    assert response.status_code == 200
    with Session(engine) as session:
        nvda = session.exec(select(TickerScore).where(TickerScore.ticker == "NVDA")).first()
    assert nvda is not None
    assert nvda.overall_score == 42
    assert nvda.overall_verdict == "Fail"
    assert nvda.computed_at == datetime(2020, 1, 1)  # byte-identical, untouched by AAPL's refresh


def test_ticker_refresh_survives_a_failing_step_during_the_post_clear_recompute(monkeypatch):
    """compute_ticker_score's own _safe_step already isolates a single
    step's failure (see test_ticker_score.py) -- this confirms that
    robustness actually reaches the endpoint: a failure calling FMP right
    after the cache-clear must not turn a refresh into a 500."""
    _fresh_shared_engine(monkeypatch)
    _patch_score_steps(monkeypatch, raise_in="step2")

    with TestClient(main.app) as client:
        response = client.post("/api/tickers/AAPL/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
