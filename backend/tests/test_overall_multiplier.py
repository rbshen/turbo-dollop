"""Overall = Steps score x Moat multiplier, end to end: the stored TickerScore row (Steps score, multiplier, Overall, formula version),
the PUT /moat recompute, and the shared fixture both implementations (scoring/overall.py and frontend/lib/overallScore.ts) must
agree on (pure-rule boundaries: scoring/test_overall.py)."""

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
from scoring.overall import SCORE_FORMULA_VERSION, StepSnapshot, compute_overall_assessment
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
        ((90, 80, 70, 60), "Pass", 52, "Fail"),  # Steps 75.0 x 0.70 = 52.5 -> 52
        ((100, 100, 100, 100), "Strong Pass", 70, "Pass"),  # perfect steps reach exactly 70 (unreachable in practice)
        ((60, 60, 60, 60), "Pass", 42, "Fail"),
    ],
)
def test_an_unrated_stock_row_is_scored_as_no_moat(monkeypatch, scores, verdict, expected_score, expected_verdict):
    engine = _engine(monkeypatch)
    s1, s2, s4, s5 = scores
    _patch_all(monkeypatch, step1=_step1(s1, verdict), step2=_step2(s2, verdict), step4=_step4(s4, verdict), step5=_step5(s5, verdict))
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.overall_score, row.overall_verdict, row.moat, row.moat_multiplier) == (expected_score, expected_verdict, None, 0.70)
    with Session(engine) as session:
        stored = session.get(TickerScore, "AAPL")
    assert (stored.overall_score, stored.overall_verdict, stored.moat_multiplier) == (expected_score, expected_verdict, 0.70)
    assert stored.formula_version == SCORE_FORMULA_VERSION
    assert stored.steps_score == pytest.approx(sum(scores) / 4)


def test_no_row_ever_reads_the_retired_moat_not_rated_verdict(monkeypatch):
    _engine(monkeypatch)
    _patch_all(monkeypatch)  # a Pass-range Steps score, Moat unset
    row = asyncio.run(compute_ticker_score("AAPL", persist=False))
    assert row.overall_verdict == "Fail" and row.overall_verdict != "moat_not_rated"


def test_an_unrated_incomplete_stock_keeps_a_null_verdict_and_no_multiplier(monkeypatch):
    _engine(monkeypatch)
    _patch_all(monkeypatch, step5=_step5(None, "insufficient_data"))
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.overall_score, row.overall_verdict, row.steps_score, row.moat_multiplier) == (None, None, None, None)


@pytest.mark.parametrize(
    ("moat", "expected_score", "expected_verdict", "multiplier"),
    [("wide_moat", 75, "Pass with caution", 1.0), ("narrow_moat", 64, "Fail", 0.85), ("no_moat", 52, "Fail", 0.70)],
)
def test_rated_rows_store_the_steps_score_and_the_multiplier_beside_overall(monkeypatch, moat, expected_score, expected_verdict, multiplier):
    engine = _engine(monkeypatch)
    _patch_all(monkeypatch)  # Steps score 75.0
    _rate(engine, moat)
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.overall_score, row.overall_verdict, row.moat_multiplier) == (expected_score, expected_verdict, multiplier)
    assert row.steps_score == pytest.approx(75.0)


def test_the_saved_narrow_multiplier_is_applied(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_all(monkeypatch)
    _rate(engine, "narrow_moat")
    with Session(engine) as session:
        session.add(MoatScoreConfig(key="default", narrow_moat_multiplier=0.9, updated_at=datetime.now()))
        session.commit()
    row = asyncio.run(compute_ticker_score("AAPL"))
    assert (row.moat_multiplier, row.overall_score) == (0.9, 68)  # 75.0 x 0.9 = 67.5 -> 68 (half to even)


def test_an_etf_row_is_unaffected(monkeypatch):
    # An ETF's steps are not scored (no Moat either), so it never reaches the Overall formula.
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


def test_rating_a_ticker_through_the_moat_endpoint_rescores_its_stored_row(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_all(monkeypatch)  # Steps score 75.0
    asyncio.run(compute_ticker_score("AAPL"))
    with Session(engine) as session:
        unrated = session.get(TickerScore, "AAPL")
        assert (unrated.overall_score, unrated.overall_verdict, unrated.moat_multiplier) == (52, "Fail", 0.70)

    with TestClient(main.app) as client:
        assert client.put("/api/tickers/AAPL/moat", json={"moat": "wide_moat"}).status_code == 200
        with Session(engine) as session:
            wide = session.get(TickerScore, "AAPL")
            assert (wide.moat, wide.overall_score, wide.overall_verdict, wide.moat_multiplier) == ("wide_moat", 75, "Pass with caution", 1.0)
        assert client.put("/api/tickers/AAPL/moat", json={"moat": "no_moat"}).status_code == 200
        with Session(engine) as session:
            none_ = session.get(TickerScore, "AAPL")
            assert (none_.overall_score, none_.overall_verdict) == (52, "Fail")


# The same cases frontend/lib/overallScore.test.ts runs through computeOverallAssessment: the two implementations
# (scoring/overall.py and lib/overallScore.ts) must agree on every one. Regenerate with tests/fixtures/generate_overall_verdict_cases.py.
_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "overall_verdict_cases.json").read_text())
_SHARED_CASES = _FIXTURE["cases"] + _FIXTURE["rounding_cases"] + _FIXTURE["parity_cases"]


def test_the_fixtures_defaults_are_the_real_defaults():
    # The TS tests take their default weights and multipliers from the fixture; this is what ties them to the backend constants.
    from scoring.overall import (
        DEFAULT_NARROW_MOAT_MULTIPLIER,
        MOAT_NOT_RATED_NOTE,
        NARROW_MOAT_MULTIPLIER_OPTIONS,
        NO_MOAT_MULTIPLIER,
        WIDE_MOAT_MULTIPLIER,
    )
    from scoring.weights import DEFAULT_WEIGHTS, OVERALL_TOTAL, as_dict

    assert _FIXTURE["defaults"] == {
        "overall": as_dict(DEFAULT_WEIGHTS.overall),
        "overall_total": OVERALL_TOTAL,
        "narrow_multiplier": DEFAULT_NARROW_MOAT_MULTIPLIER,
        "narrow_multiplier_options": list(NARROW_MOAT_MULTIPLIER_OPTIONS),
        "wide_multiplier": WIDE_MOAT_MULTIPLIER,
        "no_moat_multiplier": NO_MOAT_MULTIPLIER,
        "not_rated_note": MOAT_NOT_RATED_NOTE,
    }


def _run_case(case):
    from scoring.overall import DEFAULT_NARROW_MOAT_MULTIPLIER
    from scoring.weights import DEFAULT_WEIGHTS, OverallWeights

    steps = [StepSnapshot(s["key"], s["key"], False, s["score"], s["verdict"]) for s in case["steps"]]
    weights = OverallWeights(**case["weights"]["overall"]) if "weights" in case else DEFAULT_WEIGHTS.overall
    return compute_overall_assessment(
        steps, moat=case["moat"], weights=weights, narrow_multiplier=case.get("narrow_multiplier", DEFAULT_NARROW_MOAT_MULTIPLIER)
    )


@pytest.mark.parametrize("case", _SHARED_CASES, ids=[c["name"] for c in _SHARED_CASES])
def test_backend_matches_the_shared_overall_verdict_cases(case):
    result = _run_case(case)
    expected = case["expected"]
    assert (
        result.status,
        result.score,
        result.verdict,
        result.steps_score,
        result.moat_multiplier,
        result.moat_note,
        result.caution_steps,
        result.weak_steps,
        result.caution_reasons,
    ) == (
        expected["status"],
        expected["score"],
        expected["verdict"],
        expected["steps_score"],
        expected["moat_multiplier"],
        expected["moat_note"],
        expected["caution_steps"],
        expected["weak_steps"],
        expected["caution_reasons"],
    )


def test_the_rounding_cases_really_sit_on_an_exact_half():
    # Half-to-even and half-up disagree on these: that is what they are in the fixture for.
    import math

    assert _FIXTURE["rounding_cases"]
    for case in _FIXTURE["rounding_cases"]:
        result = _run_case(case)
        product = result.steps_score * result.moat_multiplier
        assert product % 1 == 0.5, case["name"]
        assert result.score == math.floor(product) == round(product), case["name"]  # rounded down to the even neighbour
        assert math.floor(product + 0.5) == result.score + 1  # JS Math.round would say one more


def test_the_parity_cases_cover_every_moat_state_and_the_exempt_and_incomplete_paths():
    parity = _FIXTURE["parity_cases"]
    assert len(parity) == 150
    assert {c["moat"] for c in parity} == {"wide_moat", "narrow_moat", "no_moat", None}
    assert {m for c in parity if c["moat"] == "narrow_moat" for m in [c["narrow_multiplier"]]} == {0.8, 0.82, 0.85, 0.87, 0.9}
    assert {c["expected"]["status"] for c in parity} == {"complete", "incomplete"}
    assert any(s["verdict"] == "not_supported" for c in parity for s in c["steps"])
