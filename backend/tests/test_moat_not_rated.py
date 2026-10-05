"""The "Moat not rated cannot pass" rule end to end: the stored TickerScore verdict, and the PUT /moat recompute that
flips it back to a normal verdict once the owner rates the ticker (pure-rule boundaries: scoring/test_overall.py)."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.ticker_score as ticker_score
from core.models import MoatScoreConfig, TickerMoat, TickerScore
from data.ticker_score import compute_ticker_score
from scoring.overall import MoatSnapshot, StepSnapshot, compute_overall_assessment
from tests.test_ticker_score import _patch_all, _step1, _step2, _step4, _step5, _summary


def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ticker_score, "engine", engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def _rate(engine, moat):
    with Session(engine) as session:
        session.add(TickerMoat(ticker="AAPL", moat=moat, updated_at=datetime.now()))
        session.commit()


@pytest.mark.parametrize(
    ("scores", "verdict", "expected_score", "expected_verdict"),
    [
        ((90, 80, 70, 60), "Pass", 76, "moat_not_rated"),  # steps-only Pass
        ((100, 100, 100, 100), "Strong Pass", 100, "moat_not_rated"),  # steps-only Strong Pass
        ((60, 60, 60, 60), "Pass", 60, "Fail"),  # steps-only Fail stays Fail
    ],
)
def test_unrated_stock_row_stores_the_steps_only_score_and_the_moat_not_rated_verdict(
    monkeypatch, scores, verdict, expected_score, expected_verdict
):
    engine = _engine(monkeypatch)
    s1, s2, s4, s5 = scores
    _patch_all(
        monkeypatch,
        step1=_step1(s1, verdict),
        step2=_step2(s2, verdict),
        step4=_step4(s4, verdict),
        step5=_step5(s5, verdict),
    )
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.overall_score, row.overall_verdict, row.moat) == (expected_score, expected_verdict, None)
    with Session(engine) as session:
        stored = session.get(TickerScore, "AAPL")
    assert (stored.overall_score, stored.overall_verdict) == (expected_score, expected_verdict)


def test_unrated_incomplete_stock_keeps_a_null_verdict(monkeypatch):
    _engine(monkeypatch)
    _patch_all(monkeypatch, step5=_step5(None, "insufficient_data"))
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.overall_score, row.overall_verdict) == (None, None)


@pytest.mark.parametrize(
    ("moat", "expected_score", "expected_verdict"),
    [("wide_moat", 83, "Pass"), ("narrow_moat", 73, "Pass"), ("no_moat", 52, "Fail")],
)
def test_rated_rows_keep_their_normal_verdicts(monkeypatch, moat, expected_score, expected_verdict):
    engine = _engine(monkeypatch)
    _patch_all(monkeypatch)  # steps-only blend 76
    _rate(engine, moat)
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.overall_score, row.overall_verdict) == (expected_score, expected_verdict)


def test_an_etf_row_is_unaffected(monkeypatch):
    # An ETF's steps are not scored (no Moat either), so it never reaches the verdict rule.
    _engine(monkeypatch)
    _patch_all(
        monkeypatch,
        step1=_step1(None, "insufficient_data"),
        step2=_step2(None, "insufficient_data"),
        step4=_step4(None, "insufficient_data", company_type="ETF"),
        step5=_step5(None, "not_supported", company_type="ETF"),
        summary=_summary(company_name="SPDR S&P 500 ETF", is_etf=True),
    )
    row = asyncio.run(compute_ticker_score("SPY"))
    assert (row.is_etf, row.overall_score, row.overall_verdict) == (True, None, None)


def test_rating_a_ticker_through_the_moat_endpoint_flips_its_stored_verdict(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_all(monkeypatch)  # steps-only blend 76
    asyncio.run(compute_ticker_score("AAPL"))
    with Session(engine) as session:
        assert session.get(TickerScore, "AAPL").overall_verdict == "moat_not_rated"

    with TestClient(main.app) as client:
        assert client.put("/api/tickers/AAPL/moat", json={"moat": "narrow_moat"}).status_code == 200
        with Session(engine) as session:
            narrow = session.get(TickerScore, "AAPL")
            assert (narrow.moat, narrow.overall_score, narrow.overall_verdict) == ("narrow_moat", 73, "Pass")
        assert client.put("/api/tickers/AAPL/moat", json={"moat": "no_moat"}).status_code == 200
        with Session(engine) as session:
            none_ = session.get(TickerScore, "AAPL")
            assert (none_.overall_score, none_.overall_verdict) == (52, "Fail")


# The same cases frontend/lib/overallScore.test.ts runs through computeOverallAssessment: the two implementations
# (scoring/overall.py and lib/overallScore.ts) must agree on every one.
_SHARED_CASES = json.loads((Path(__file__).parent / "fixtures" / "overall_verdict_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", _SHARED_CASES, ids=[c["name"] for c in _SHARED_CASES])
def test_backend_matches_the_shared_overall_verdict_cases(case):
    steps = [StepSnapshot(s["key"], s["key"], False, s["score"], s["verdict"]) for s in case["steps"]]
    moat = MoatSnapshot(case["moat"]["moat"], case["moat"]["score"]) if case["moat"] else None
    result = compute_overall_assessment(steps, moat=moat)
    expected = case["expected"]
    assert (result.status, result.score, result.verdict) == (expected["status"], expected["score"], expected["verdict"])
