"""Saved score weights: the loader, the settings endpoints and their validation, the compute path that uses them, the stale
check, and the Moat points cap (data/score_weights.py, core/main.py, scoring/weights.py)."""

import asyncio
import copy
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.moat as moat_module
import data.score_weights as score_weights
import data.step1_data as step1_data
import data.ticker_score as ticker_score
from core.models import MoatScoreConfig, ScoreWeightSettings, TickerScore
from data.score_weights import get_score_weights_row, load_score_weights, reset_score_weights, save_score_weights
from scoring.weights import (
    BOUNDS,
    DEFAULT_WEIGHTS,
    OverallWeights,
    ScoreWeights,
    Step1Weights,
    Step2Weights,
    Step4Weights,
    Step5Weights,
    validate_weights,
    weights_to_dict,
)
from tests.test_ticker_score import _step1, _step2, _step4, _step5, _summary


def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    for mod in (main, ticker_score, step1_data, moat_module):
        if hasattr(mod, "engine"):
            monkeypatch.setattr(mod, "engine", engine)
    return engine


CUSTOM = ScoreWeights(
    overall=OverallWeights(17, 17, 17, 18),
    step1=Step1Weights(30, 20, 20, 20, 10),
    step2=Step2Weights(60, 40),
    step4=Step4Weights(25, 25, 25, 25),
    step5=Step5Weights(20, 40, 40),
)


def _body(weights=CUSTOM):
    return copy.deepcopy(weights_to_dict(weights))


# --- the pure rules --------------------------------------------------------------------------------------------------------


def test_the_test_set_used_below_is_itself_valid():
    assert validate_weights(CUSTOM) == []


def test_defaults_satisfy_every_rule():
    assert validate_weights(DEFAULT_WEIGHTS) == []


def test_every_default_sits_inside_its_bounds():
    for group, fields in weights_to_dict(DEFAULT_WEIGHTS).items():
        for field, value in fields.items():
            low, high = BOUNDS[group][field]
            assert low <= value <= high, (group, field)


def test_bounds_are_the_owners_numbers():
    assert BOUNDS["overall"] == {"financials": (10, 30), "growth": (5, 30), "profitability": (5, 30), "debt": (10, 30)}
    assert BOUNDS["step1"] == {"revenue": (20, 50), "net_income": (10, 40), "cfo": (10, 40), "margins": (0, 25), "fcf": (0, 15)}
    assert BOUNDS["step2"] == {"magnitude": (50, 100), "agreement": (0, 50)}
    assert BOUNDS["step4"] == {"roe": (15, 60), "roic": (15, 60), "ar": (0, 30), "ccc": (0, 30)}
    assert BOUNDS["step5"] == {"current_ratio": (15, 60), "debt_to_ebitda": (15, 60), "debt_servicing": (15, 60)}


def test_the_four_overall_weights_cap_below_moat():
    assert max(high for _, high in BOUNDS["overall"].values()) == 30 < 31


def test_messages_name_the_set_and_the_rule():
    bad = ScoreWeights(
        overall=OverallWeights(30, 30, 30, 30),
        step1=Step1Weights(35, 20, 30, 10, 5),
        step2=Step2Weights(40, 60),
        step4=Step4Weights(25, 35, 20, 20),
        step5=Step5Weights(33, 33, 31),
    )
    messages = validate_weights(bad)
    assert "Overall weights must add up to 69 (they add up to 120)." in messages
    assert "Growth Rate: Growth Magnitude must be between 50 and 100." in messages
    assert "Growth Rate: Estimate Agreement must be between 0 and 50." in messages
    assert "Debt weights must add up to 100 (they add up to 97)." in messages
    assert not any(m.startswith("Financials") for m in messages)


# --- the loader ------------------------------------------------------------------------------------------------------------


def test_an_unseeded_database_serves_the_defaults_without_writing(monkeypatch):
    engine = _engine(monkeypatch)
    snapshot = load_score_weights(engine)
    assert snapshot.weights == DEFAULT_WEIGHTS and snapshot.version == 1 and snapshot.updated_at is None
    with Session(engine) as session:
        assert session.get(ScoreWeightSettings, "default") is None  # a read never seeds


def test_the_row_is_seeded_from_the_defaults_and_save_bumps_the_version(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        row = get_score_weights_row(session)
        assert row.weights_version == 1 and row.step5_debt_servicing == 34 and row.overall_debt == 15
        saved = save_score_weights(session, CUSTOM)
        assert saved.weights_version == 2
        again = save_score_weights(session, CUSTOM)
        assert again.weights_version == 3  # every save bumps it, even an identical one
    snapshot = load_score_weights(engine)
    assert snapshot.weights == CUSTOM and snapshot.version == 3


def test_a_save_drops_the_cache_but_a_second_read_is_served_from_it(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        save_score_weights(session, CUSTOM)
    assert load_score_weights(engine).weights == CUSTOM
    with Session(engine) as session:  # a write that bypasses the helpers is not seen until the TTL (or an invalidation)
        session.get(ScoreWeightSettings, "default").overall_debt = 99
        session.commit()
    assert load_score_weights(engine).weights.overall.debt == 18
    score_weights.invalidate_cache()
    assert load_score_weights(engine).weights.overall.debt == 99


def test_reset_restores_the_defaults_and_still_bumps_the_version(monkeypatch):
    engine = _engine(monkeypatch)
    with Session(engine) as session:
        save_score_weights(session, CUSTOM)
        row = reset_score_weights(session)
        assert row.weights_version == 3
    assert load_score_weights(engine).weights == DEFAULT_WEIGHTS


# --- the endpoints ---------------------------------------------------------------------------------------------------------


def test_get_returns_weights_defaults_bounds_and_the_locked_moat_weight(monkeypatch):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        body = client.get("/api/config/score-weights").json()
    assert body["weights"] == body["defaults"] == weights_to_dict(DEFAULT_WEIGHTS)
    assert body["moat_weight"] == 31 and body["overall_total"] == 69
    assert body["bounds"]["step5"]["current_ratio"] == {"min": 15, "max": 60}
    assert body["bounds"]["overall"]["debt"] == {"min": 10, "max": 30}
    assert body["sums"] == {"overall": 69, "step1": 100, "step2": 100, "step4": 100, "step5": 100}
    assert body["weights_version"] == 1 and body["recompute"] is None
    assert "moat" not in body["weights"]


def test_put_saves_a_valid_set_and_bumps_the_version(monkeypatch):
    engine = _engine(monkeypatch)
    with TestClient(main.app) as client:
        response = client.put("/api/config/score-weights", json=_body())
        assert response.status_code == 200
        assert response.json()["weights"] == _body() and response.json()["weights_version"] == 2
        assert client.get("/api/config/score-weights").json()["weights"] == _body()
    assert load_score_weights(engine).weights == CUSTOM


def test_reset_endpoint_restores_the_defaults(monkeypatch):
    engine = _engine(monkeypatch)
    import data.score_recompute as score_recompute

    with TestClient(main.app) as client:
        client.put("/api/config/score-weights", json=_body())
        score_recompute.fail_run(1, "test: the first run is over", engine)  # one recompute at a time
        response = client.post("/api/config/score-weights/reset")
    assert response.status_code == 200
    assert response.json()["weights"] == weights_to_dict(DEFAULT_WEIGHTS) and response.json()["weights_version"] == 3


def _put_error(client, body):
    response = client.put("/api/config/score-weights", json=body)
    assert response.status_code == 422
    return response.json()["detail"]


def test_put_rejects_a_wrong_sum_naming_the_set(monkeypatch):
    engine = _engine(monkeypatch)
    body = _body()
    body["step1"]["revenue"] += 3
    with TestClient(main.app) as client:
        detail = _put_error(client, body)
    assert "Financials weights must add up to 100 (they add up to 103)." in str(detail)
    assert load_score_weights(engine).weights == DEFAULT_WEIGHTS  # nothing saved


def test_put_rejects_a_value_outside_its_bounds(monkeypatch):
    _engine(monkeypatch)
    body = _body(DEFAULT_WEIGHTS)
    body["overall"]["financials"], body["overall"]["debt"] = 31, 8  # still sums to 69
    body["step5"]["current_ratio"], body["step5"]["debt_servicing"] = 10, 56  # still sums to 100
    with TestClient(main.app) as client:
        detail = str(_put_error(client, body))
    assert "Overall: Financials must be between 10 and 30." in detail
    assert "Overall: Debt must be between 10 and 30." in detail
    assert "Debt: Current Ratio must be between 15 and 60." in detail


@pytest.mark.parametrize("value", [33.0, 33.5, "33", None, True])
def test_put_rejects_anything_but_a_whole_number(monkeypatch, value):
    _engine(monkeypatch)
    body = _body(DEFAULT_WEIGHTS)
    body["step5"]["current_ratio"] = value
    with TestClient(main.app) as client:
        assert client.put("/api/config/score-weights", json=body).status_code == 422


def test_moat_is_not_an_accepted_field(monkeypatch):
    _engine(monkeypatch)
    for tamper in (lambda b: b.update(moat=31), lambda b: b["overall"].update(moat=31), lambda b: b["step1"].update(extra=1)):
        body = _body(DEFAULT_WEIGHTS)
        tamper(body)
        with TestClient(main.app) as client:
            assert client.put("/api/config/score-weights", json=body).status_code == 422


def test_put_rejects_a_missing_group(monkeypatch):
    _engine(monkeypatch)
    body = _body(DEFAULT_WEIGHTS)
    del body["step4"]
    with TestClient(main.app) as client:
        assert client.put("/api/config/score-weights", json=body).status_code == 422


# --- the compute path ------------------------------------------------------------------------------------------------------


def _patch_steps(monkeypatch, seen):
    def make(name, value):
        async def fn(ticker, cache_only=False, weights=None):
            seen[name] = weights
            return value

        return fn

    monkeypatch.setattr(ticker_score, "get_step1_data", make("step1", _step1()))
    monkeypatch.setattr(ticker_score, "get_step2_data", make("step2", _step2()))
    monkeypatch.setattr(ticker_score, "get_step4_data", make("step4", _step4()))
    monkeypatch.setattr(ticker_score, "get_step5_data", make("step5", _step5()))
    monkeypatch.setattr(ticker_score, "get_summary", make("summary", _summary()))


def test_compute_uses_the_saved_weights_once_and_stamps_the_version(monkeypatch):
    engine = _engine(monkeypatch)
    seen: dict = {}
    _patch_steps(monkeypatch, seen)
    with Session(engine) as session:
        save_score_weights(session, CUSTOM)

    row = asyncio.run(ticker_score.compute_ticker_score("AAPL"))

    assert row.weights_version == 2
    assert seen["step1"] is seen["step2"] is seen["step4"] is seen["step5"]  # one set for the whole compute
    assert seen["step1"] == CUSTOM
    with Session(engine) as session:
        assert session.get(TickerScore, "AAPL").weights_version == 2


def test_the_overall_blend_uses_the_saved_overall_weights(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_steps(monkeypatch, {})
    # steps 90/80/70/60 (see test_ticker_score): defaults give 76; Debt-heavy 15/8/16/30 gives something else.
    default_row = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False))
    assert default_row.overall_score == 76
    debt_heavy = copy.deepcopy(weights_to_dict(DEFAULT_WEIGHTS))
    debt_heavy["overall"] = {"financials": 15, "growth": 8, "profitability": 16, "debt": 30}
    from scoring.weights import weights_from_dict

    with Session(engine) as session:
        save_score_weights(session, weights_from_dict(debt_heavy))
    row = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False))
    assert row.overall_score == round((90 * 15 + 80 * 8 + 70 * 16 + 60 * 30) / 69) == 71


def test_an_explicit_weight_set_is_used_and_not_versioned(monkeypatch):
    _engine(monkeypatch)
    seen: dict = {}
    _patch_steps(monkeypatch, seen)
    row = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False, weights=CUSTOM))
    assert seen["step2"] == CUSTOM and row.weights_version is None


def test_step_functions_read_the_saved_weights_when_none_are_passed(monkeypatch):
    engine = _engine(monkeypatch)
    captured = {}

    async def no_data(*a, **k):
        return {}

    monkeypatch.setattr(step1_data, "safe_fetch", no_data)
    with Session(engine) as session:
        save_score_weights(session, CUSTOM)
    # No profile at all: the function returns early, but it has already resolved its weights from the DB.
    original = step1_data.load_score_weights

    def spy(bind):
        snapshot = original(bind)
        captured["weights"] = snapshot.weights
        return snapshot

    monkeypatch.setattr(step1_data, "load_score_weights", spy)
    try:
        asyncio.run(step1_data.get_step1_data("AAPL", cache_only=True))
    except Exception:
        pass  # the empty cache is not the point
    assert captured["weights"] == CUSTOM


# --- the header's stale check ------------------------------------------------------------------------------------------------


def _store_row(engine, **fields):
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="AAPL",
                company_name="Apple Inc.",
                overall_score=85,
                overall_verdict="Pass",
                computed_at=datetime.now() - timedelta(hours=2),
                **fields,
            )
        )
        session.commit()


def test_a_row_scored_with_older_weights_is_recomputed_cache_only(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []

    def make(name, value):
        async def fn(ticker, cache_only=False, weights=None):
            calls.append((name, cache_only))
            return value

        return fn

    _patch_steps(monkeypatch, {})
    for name, value in (("get_step1_data", _step1()), ("get_step2_data", _step2()), ("get_step4_data", _step4()), ("get_step5_data", _step5())):
        monkeypatch.setattr(ticker_score, name, make(name, value))
    monkeypatch.setattr(ticker_score, "get_summary", make("summary", _summary()))
    _store_row(engine, weights_version=1)
    with Session(engine) as session:
        save_score_weights(session, CUSTOM)  # current version 2

    with TestClient(main.app) as client:
        body = client.get("/api/tickers/AAPL/score").json()

    assert calls and all(cache_only is True for _, cache_only in calls)  # no live FMP fetch
    assert body["weights_version"] == 2


def test_an_unversioned_or_current_row_is_served_as_stored(monkeypatch):
    engine = _engine(monkeypatch)
    calls = []
    _patch_steps(monkeypatch, {})

    async def spy(*a, **k):
        calls.append(1)

    monkeypatch.setattr(main, "compute_ticker_score", spy)
    _store_row(engine, weights_version=None)  # computed before weights were adjustable: scored with the defaults
    with TestClient(main.app) as client:
        assert client.get("/api/tickers/AAPL/score").json()["overall_score"] == 85
    with Session(engine) as session:
        save_score_weights(session, CUSTOM)
        row = session.get(TickerScore, "AAPL")
        row.weights_version = 2
        session.commit()
    with TestClient(main.app) as client:
        assert client.get("/api/tickers/AAPL/score").json()["weights_version"] == 2
    assert calls == []


# --- the column migration --------------------------------------------------------------------------------------------------


def test_the_nullable_column_is_added_to_an_existing_tickerscore_table(monkeypatch):
    import core.db as db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tickerscore (ticker VARCHAR PRIMARY KEY, computed_at DATETIME)"))
    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()
    columns = {c["name"]: c for c in inspect(engine).get_columns("tickerscore")}
    assert "weights_version" in columns and columns["weights_version"]["nullable"]


# --- Moat points -----------------------------------------------------------------------------------------------------------


def _put_moat(client, wide=100.0, narrow=65.0, no_moat=0.0):
    return client.put("/api/config/moat", json={"wide_moat_score": wide, "narrow_moat_score": narrow, "no_moat_score": no_moat})


def test_the_stored_moat_values_pass_the_new_validation(monkeypatch):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        assert _put_moat(client).status_code == 200  # the live row: 100 / 65 / 0


@pytest.mark.parametrize("no_moat", [0.0, 0.5, 1.0])
def test_no_moat_points_up_to_the_cap_are_accepted(monkeypatch, no_moat):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        response = _put_moat(client, no_moat=no_moat)
        assert response.status_code == 200 and response.json()["no_moat_score"] == no_moat


@pytest.mark.parametrize("no_moat", [1.1, 1.7, 5.0, -0.1])
def test_no_moat_points_above_the_cap_or_below_zero_are_rejected(monkeypatch, no_moat):
    engine = _engine(monkeypatch)
    with TestClient(main.app) as client:
        response = _put_moat(client, no_moat=no_moat)
    assert response.status_code == 422
    assert "between 0 and 1" in str(response.json()["detail"]) and "31%" in str(response.json()["detail"])
    with Session(engine) as session:
        assert session.get(MoatScoreConfig, "default") is None  # nothing saved


def test_no_moat_must_be_lower_than_narrow_and_wide(monkeypatch):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        assert _put_moat(client, narrow=1.0, no_moat=1.0).status_code == 422
        assert _put_moat(client, wide=0.5, narrow=65.0, no_moat=1.0).status_code == 422
        assert _put_moat(client, wide=100.0, narrow=0.9, no_moat=0.5).status_code == 200


def test_the_cap_keeps_no_moat_below_70_whatever_the_four_checks_score():
    from scoring.overall import MoatSnapshot, StepSnapshot, compute_overall_assessment

    perfect = [StepSnapshot(k, k, False, 100, "Strong Pass") for k in ("step1", "step2", "step4", "step5")]
    result = compute_overall_assessment(perfect, moat=MoatSnapshot("no_moat", 1.0))
    assert result.score == 69 and result.verdict == "Fail"
    # ... and 1.7 points is where the guarantee ends (why the cap is 1, not 2).
    assert compute_overall_assessment(perfect, moat=MoatSnapshot("no_moat", 1.7)).score == 70
