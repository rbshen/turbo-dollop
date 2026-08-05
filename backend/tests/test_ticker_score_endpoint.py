from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import main
import data.ticker_score as ticker_score
from models import TickerScore
from schemas import Step1Out, Step2Out, Step4Out, Step5Out, TickerSummaryOut


def _fresh_shared_engine(monkeypatch):
    # GET /score reads via main.engine and, on a miss, falls back to
    # compute_ticker_score's own write via ticker_score.engine -- both must
    # share one DB for the fallback's persisted row to be visible.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for mod in (main, ticker_score):
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


def _patch_score_steps(monkeypatch, calls=None, company_name="Apple Inc."):
    calls = calls if calls is not None else []

    def make(name, value):
        async def fn(ticker, cache_only=False):
            calls.append((name, cache_only))
            return value

        return fn

    monkeypatch.setattr(ticker_score, "get_step1_data", make("step1", _step1()))
    monkeypatch.setattr(ticker_score, "get_step2_data", make("step2", _step2()))
    monkeypatch.setattr(ticker_score, "get_step4_data", make("step4", _step4()))
    monkeypatch.setattr(ticker_score, "get_step5_data", make("step5", _step5()))
    monkeypatch.setattr(ticker_score, "get_summary", make("summary", _summary(company_name)))
    return calls


def test_returns_an_existing_row_unchanged_without_recomputing(monkeypatch):
    engine = _fresh_shared_engine(monkeypatch)
    calls = _patch_score_steps(monkeypatch)  # would record a call if compute_ticker_score ran

    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="AAPL",
                company_name="Apple Inc.",
                overall_score=85,
                overall_verdict="Pass",
                computed_at=datetime(2026, 1, 1),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/score")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["overall_score"] == 85
    assert body["overall_verdict"] == "Pass"
    assert body["computed_at"] == "2026-01-01T00:00:00"
    assert calls == []  # a stored row is read directly, never recomputed


def test_falls_back_to_cache_only_compute_when_no_row_exists(monkeypatch):
    engine = _fresh_shared_engine(monkeypatch)
    calls = _patch_score_steps(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/score")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["company_name"] == "Apple Inc."
    assert body["overall_score"] is not None

    # cache_only=True throughout -- the fallback must never trigger a live
    # FMP call just from viewing a ticker's page.
    assert len(calls) == 5
    assert all(cache_only is True for _, cache_only in calls)

    # persisted, not just returned -- the next request for this ticker
    # takes the cheap direct-read path instead of recomputing again.
    with Session(engine) as session:
        row = session.exec(select(TickerScore).where(TickerScore.ticker == "AAPL")).first()
    assert row is not None


def test_returns_null_when_even_the_fallback_has_no_cached_profile(monkeypatch):
    _fresh_shared_engine(monkeypatch)
    _patch_score_steps(monkeypatch, company_name=None)  # compute_ticker_score's own "no data" case

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/ZZZZINVALID/score")

    assert response.status_code == 200
    assert response.json() is None
