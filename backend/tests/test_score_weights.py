"""Saved score weights: the loader, the settings endpoints and their validation, the compute path that uses them, the stale
check, the Moat multiplier setting, and the one-time migration of the saved weights and the Moat config (data/score_weights.py,
core/main.py, core/db.py, scoring/weights.py)."""

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
    overall=OverallWeights(25, 25, 25, 25),
    step1=Step1Weights(30, 20, 20, 20, 10),
    step2=Step2Weights(60, 40),
    step4=Step4Weights(25, 25, 25, 25),
    step5=Step5Weights(20, 50, 30),
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
    assert BOUNDS["overall"] == {"financials": (10, 50), "growth": (5, 50), "profitability": (5, 50), "debt": (10, 50)}
    assert BOUNDS["step1"] == {"revenue": (20, 50), "net_income": (10, 40), "cfo": (10, 40), "margins": (0, 25), "fcf": (0, 15)}
    assert BOUNDS["step2"] == {"magnitude": (50, 100), "agreement": (0, 50)}
    assert BOUNDS["step4"] == {"roe": (15, 60), "roic": (15, 60), "ar": (0, 30), "ccc": (0, 30)}
    assert BOUNDS["step5"] == {"current_ratio": (15, 30), "debt_to_ebitda": (35, 60), "debt_servicing": (15, 30)}


def test_the_overall_weights_add_up_to_100_and_no_step_can_exceed_half():
    from scoring.weights import SUMS

    assert SUMS["overall"] == 100
    assert max(high for _, high in BOUNDS["overall"].values()) == 50


def test_messages_name_the_set_and_the_rule():
    bad = ScoreWeights(
        overall=OverallWeights(30, 30, 30, 30),
        step1=Step1Weights(35, 20, 30, 10, 5),
        step2=Step2Weights(40, 60),
        step4=Step4Weights(25, 35, 20, 20),
        step5=Step5Weights(33, 33, 31),
    )
    messages = validate_weights(bad)
    assert "Overall weights must add up to 100 (they add up to 120)." in messages
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
        assert row.weights_version == 1 and row.step5_debt_servicing == 30 and row.step5_debt_to_ebitda == 45 and row.overall_debt == 30
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
    assert load_score_weights(engine).weights.overall.debt == 25
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


def test_get_returns_weights_defaults_bounds_sums_and_the_formula_version(monkeypatch):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        body = client.get("/api/config/score-weights").json()
    assert body["weights"] == body["defaults"] == weights_to_dict(DEFAULT_WEIGHTS)
    assert "moat_weight" not in body and body["overall_total"] == 100  # Moat is a multiplier now, not a weight
    assert body["weights"]["overall"] == {"financials": 30, "growth": 20, "profitability": 20, "debt": 30}
    assert body["bounds"]["step5"] == {
        "current_ratio": {"min": 15, "max": 30},
        "debt_to_ebitda": {"min": 35, "max": 60},
        "debt_servicing": {"min": 15, "max": 30},
    }
    assert body["orderings"] == {"step5": ["debt_to_ebitda", "debt_servicing", "current_ratio"]}  # largest weight first
    assert body["bounds"]["overall"]["debt"] == {"min": 10, "max": 50}
    assert body["sums"] == {"overall": 100, "step1": 100, "step2": 100, "step4": 100, "step5": 100}
    assert body["weights_version"] == 1 and body["recompute"] is None
    from scoring.overall import SCORE_FORMULA_VERSION

    assert body["formula_version"] == SCORE_FORMULA_VERSION
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
    body["overall"]["financials"], body["overall"]["debt"] = 9, 51  # still sums to 100
    body["step5"]["current_ratio"], body["step5"]["debt_servicing"] = 10, 45  # still sums to 100 (10 + 45 + 45)
    with TestClient(main.app) as client:
        detail = str(_put_error(client, body))
    assert "Overall: Financials must be between 10 and 50." in detail
    assert "Overall: Debt must be between 10 and 50." in detail
    assert "Debt: Current Ratio must be between 15 and 30." in detail
    assert "Debt: Debt Servicing Ratio must be between 15 and 30." in detail


def test_put_rejects_a_step5_set_that_breaks_the_strict_order(monkeypatch):
    _engine(monkeypatch)
    body = _body(DEFAULT_WEIGHTS)
    body["step5"] = {"current_ratio": 30, "debt_to_ebitda": 40, "debt_servicing": 30}  # inside every bound, sums to 100, tied
    with TestClient(main.app) as client:
        detail = str(_put_error(client, body))
    assert "Debt weights must keep this order, each strictly larger than the next: Debt/EBITDA > Debt Servicing Ratio > Current Ratio." in detail
    body["step5"] = {"current_ratio": 20, "debt_to_ebitda": 40, "debt_servicing": 40}  # Debt/EBITDA tied with Debt Servicing
    with TestClient(main.app) as client:
        assert "must keep this order" in str(_put_error(client, body))


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
    # steps 90/80/70/60 (see test_ticker_score): the defaults give a Steps score of 75.0 (x 0.70, unrated = 52); a Debt-heavy
    # 15/8/27/50 set gives something else.
    default_row = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False))
    assert default_row.overall_score == 52 and default_row.steps_score == pytest.approx(75.0)
    debt_heavy = copy.deepcopy(weights_to_dict(DEFAULT_WEIGHTS))
    debt_heavy["overall"] = {"financials": 15, "growth": 8, "profitability": 27, "debt": 50}
    from scoring.weights import weights_from_dict

    with Session(engine) as session:
        save_score_weights(session, weights_from_dict(debt_heavy))
    row = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False))
    assert row.steps_score == pytest.approx((90 * 15 + 80 * 8 + 70 * 27 + 60 * 50) / 100) == pytest.approx(68.8)
    assert row.overall_score == round(68.8 * 0.70) == 48


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
    from scoring.overall import SCORE_FORMULA_VERSION

    fields.setdefault("formula_version", SCORE_FORMULA_VERSION)  # a row scored under the current formula, unless a test says otherwise
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


@pytest.mark.parametrize("formula_version", [None, 1])
def test_a_row_scored_under_another_formula_is_recomputed_even_at_the_current_weights_version(monkeypatch, formula_version):
    # weights_version cannot see a change of formula: a row with the current weights version but no (or an older) formula version is
    # stale, whatever its weights_version (even an unversioned one).
    for weights_version in (1, None):
        engine = _engine(monkeypatch)
        calls = []
        _patch_steps(monkeypatch, {})

        async def recompute(ticker, cache_only=False, persist_etf=True, **kwargs):
            calls.append(cache_only)
            return TickerScore(ticker="AAPL", company_name="Apple Inc.", overall_score=52, computed_at=datetime.now())

        monkeypatch.setattr(main, "compute_ticker_score", recompute)
        _store_row(engine, weights_version=weights_version, formula_version=formula_version)
        with TestClient(main.app) as client:
            assert client.get("/api/tickers/AAPL/score").json()["overall_score"] == 52
        assert calls == [True]  # recomputed once, cache only (no FMP call)


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


# --- Moat multiplier ----------------------------------------------------------------------------------------------------------


def _put_moat(client, narrow=0.85):
    return client.put("/api/config/moat", json={"narrow_moat_multiplier": narrow})


def test_get_moat_returns_the_three_multipliers_the_options_and_the_default(monkeypatch):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        body = client.get("/api/config/moat").json()
    assert (body["wide_moat_multiplier"], body["narrow_moat_multiplier"], body["no_moat_multiplier"]) == (1.0, 0.85, 0.70)
    assert body["narrow_moat_multiplier_options"] == [0.80, 0.82, 0.85, 0.87, 0.90]
    assert "wide_moat_score" not in body and "no_moat_score" not in body  # the points are gone


@pytest.mark.parametrize("narrow", [0.80, 0.82, 0.85, 0.87, 0.90])
def test_every_allowed_narrow_multiplier_is_saved(monkeypatch, narrow):
    engine = _engine(monkeypatch)
    with TestClient(main.app) as client:
        response = _put_moat(client, narrow)
        assert response.status_code == 200 and response.json()["narrow_moat_multiplier"] == narrow
        assert client.get("/api/config/moat").json()["narrow_moat_multiplier"] == narrow
    with Session(engine) as session:
        assert session.get(MoatScoreConfig, "default").narrow_moat_multiplier == narrow


@pytest.mark.parametrize("narrow", [0.0, 0.7, 0.75, 0.84, 0.86, 0.95, 1.0, 1.5, -0.85])
def test_any_other_narrow_multiplier_is_rejected_and_nothing_is_saved(monkeypatch, narrow):
    engine = _engine(monkeypatch)
    with TestClient(main.app) as client:
        response = _put_moat(client, narrow)
    assert response.status_code == 422 and "0.80, 0.82, 0.85, 0.87, 0.90" in str(response.json()["detail"])
    with Session(engine) as session:
        assert session.get(MoatScoreConfig, "default") is None  # nothing saved, no job claimed


def test_wide_and_no_moat_multipliers_cannot_be_sent(monkeypatch):
    _engine(monkeypatch)
    with TestClient(main.app) as client:
        # Only the Narrow value is an input; extra fields are ignored, the fixed ones never change.
        response = client.put("/api/config/moat", json={"narrow_moat_multiplier": 0.9, "no_moat_multiplier": 0.95, "wide_moat_multiplier": 1.1})
        assert response.status_code == 200
        body = response.json()
    assert (body["wide_moat_multiplier"], body["no_moat_multiplier"]) == (1.0, 0.70)


def test_saving_the_narrow_multiplier_advances_weights_version_so_stored_rows_read_as_stale(monkeypatch):
    engine = _engine(monkeypatch)
    with TestClient(main.app) as client:
        assert _put_moat(client, 0.9).status_code == 200
    assert load_score_weights(engine).version == 2  # 1 (seed) + 1 (the multiplier change)


def test_the_compute_path_reads_the_saved_narrow_multiplier(monkeypatch):
    engine = _engine(monkeypatch)
    _patch_steps(monkeypatch, {})
    from data.moat import set_ticker_moat, update_moat_score_config

    with Session(engine) as session:
        set_ticker_moat(session, "AAPL", "narrow_moat")
        update_moat_score_config(session, 0.9)
    row = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False))
    assert row.moat == "narrow_moat" and row.moat_multiplier == 0.9
    assert row.overall_score == round(75.0 * 0.9) == 68  # 67.5 rounds half to even, to 68
    # An absent config row reads as the default 0.85 (a read never creates it).
    with Session(engine) as session:
        session.delete(session.get(MoatScoreConfig, "default"))
        session.commit()
    again = asyncio.run(ticker_score.compute_ticker_score("AAPL", persist=False))
    assert again.moat_multiplier == 0.85
    with Session(engine) as session:
        assert session.get(MoatScoreConfig, "default") is None


def test_update_refuses_an_unsupported_value_directly_too(monkeypatch):
    engine = _engine(monkeypatch)
    from data.moat import update_moat_score_config

    with Session(engine) as session, pytest.raises(ValueError):
        update_moat_score_config(session, 0.86)


# --- the one-time migration of the saved weights and the Moat config -----------------------------------------------------------


def _migration_engine(monkeypatch):
    import core.db as db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    return db, engine


def _seed_weights(engine, financials, growth, profitability, debt, version=1):
    with Session(engine) as session:
        columns = {f"{g}_{f}": v for g, fields in weights_to_dict(DEFAULT_WEIGHTS).items() for f, v in fields.items()}
        columns.update(overall_financials=financials, overall_growth=growth, overall_profitability=profitability, overall_debt=debt)
        session.add(ScoreWeightSettings(key="default", weights_version=version, updated_at=datetime.now(), **columns))
        session.commit()


def _overall(engine):
    with Session(engine) as session:
        row = session.get(ScoreWeightSettings, "default")
        return (row.overall_financials, row.overall_growth, row.overall_profitability, row.overall_debt), row.weights_version


def test_the_old_default_overall_weights_are_replaced_with_the_new_defaults(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    _seed_weights(engine, 24, 10, 20, 15)
    result = db._migrate_moat_and_overall_weights()
    assert result["weights"] == "defaults"
    assert _overall(engine) == ((30, 20, 20, 30), 2)  # Financials, Growth, Profitability, Debt; version bumped


def test_a_custom_overall_set_is_rescaled_proportionally_to_100_and_warned_about(monkeypatch, caplog):
    db, engine = _migration_engine(monkeypatch)
    _seed_weights(engine, 17, 30, 11, 11, version=4)
    with caplog.at_level("WARNING"):
        result = db._migrate_moat_and_overall_weights()
    assert result["weights"] == "rescaled" and result["old"] == {"financials": 17, "growth": 30, "profitability": 11, "debt": 11}
    (financials, growth, profitability, debt), version = _overall(engine)
    assert sum((financials, growth, profitability, debt)) == 100 and version == 5
    assert (financials, growth, profitability, debt) == (25, 43, 16, 16)  # 24.6 / 43.5 / 15.9 / 15.9, largest remainder
    assert "CUSTOM" in caplog.text  # flagged, not silent


def test_an_already_migrated_set_is_left_alone_and_the_migration_is_idempotent(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    _seed_weights(engine, 24, 10, 20, 15)
    db._migrate_moat_and_overall_weights()
    after_first = _overall(engine)
    assert db._migrate_moat_and_overall_weights()["weights"] is None
    assert _overall(engine) == after_first  # no second bump
    _seed_weights_again = None  # a fresh seed of the new defaults is also untouched
    with Session(engine) as session:
        row = session.get(ScoreWeightSettings, "default")
        row.overall_financials, row.overall_growth, row.overall_profitability, row.overall_debt = 40, 10, 20, 30
        session.commit()
    assert db._migrate_moat_and_overall_weights()["weights"] is None and _overall(engine)[0] == (40, 10, 20, 30)


def test_an_unseeded_database_migrates_nothing(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    assert db._migrate_moat_and_overall_weights() == {"moat_default_set": False, "weights": None}


def test_a_migrated_database_issues_no_write_at_all(monkeypatch):
    # The app's lifespan runs init_db on every start (and every test that boots the app against the real engine): once migrated, it
    # must not write, or the real-database write guard in conftest would fail those tests.
    db, engine = _migration_engine(monkeypatch)
    with Session(engine) as session:
        session.add(MoatScoreConfig(key="default", narrow_moat_multiplier=0.85, updated_at=datetime.now()))
        session.commit()
    _seed_weights(engine, 30, 20, 20, 30)
    from sqlalchemy import event

    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))
    db._migrate_moat_and_overall_weights()
    assert not [x for x in statements if x.strip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]


def test_an_old_moat_config_table_gets_the_multiplier_and_loses_the_points_columns(monkeypatch):
    import core.db as db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE moatscoreconfig (key VARCHAR PRIMARY KEY, wide_moat_score FLOAT NOT NULL, narrow_moat_score FLOAT NOT NULL, "
                "no_moat_score FLOAT NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        conn.execute(text("INSERT INTO moatscoreconfig VALUES ('default', 100.0, 65.0, 0.0, '2026-07-23 13:15:43')"))
    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()
    assert db._migrate_moat_and_overall_weights()["moat_default_set"] is True
    db._drop_obsolete_columns()
    inspector = inspect(engine)
    assert {c["name"] for c in inspector.get_columns("moatscoreconfig")} == {"key", "updated_at", "narrow_moat_multiplier"}
    with Session(engine) as session:
        row = session.get(MoatScoreConfig, "default")
        assert row.narrow_moat_multiplier == 0.85  # the row survived; the old points are gone with their columns


def test_the_new_tickerscore_columns_are_added_nullable(monkeypatch):
    import core.db as db

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE tickerscore (ticker VARCHAR PRIMARY KEY, computed_at DATETIME, moat_score FLOAT)"))
    monkeypatch.setattr(db, "engine", engine)
    db._add_missing_columns()
    db._drop_obsolete_columns()
    columns = {c["name"]: c for c in inspect(engine).get_columns("tickerscore")}
    for name in ("steps_score", "moat_multiplier", "formula_version"):
        assert name in columns and columns[name]["nullable"]
    assert "moat_score" not in columns


# --- the Step 5 weights migration (2026-10-07, no hard fail) ---------------------------------------------------------------


def _seed_step5(engine, current_ratio, debt_to_ebitda, debt_servicing, version=5):
    with Session(engine) as session:
        columns = {f"{g}_{f}": v for g, fields in weights_to_dict(DEFAULT_WEIGHTS).items() for f, v in fields.items()}
        columns.update(step5_current_ratio=current_ratio, step5_debt_to_ebitda=debt_to_ebitda, step5_debt_servicing=debt_servicing)
        session.add(ScoreWeightSettings(key="default", weights_version=version, updated_at=datetime.now(), **columns))
        session.commit()


def _step5_row(engine):
    with Session(engine) as session:
        row = session.get(ScoreWeightSettings, "default")
        return (row.step5_current_ratio, row.step5_debt_to_ebitda, row.step5_debt_servicing), row.weights_version


def test_the_old_33_33_34_step5_row_is_reset_to_the_new_defaults_and_the_version_goes_up(monkeypatch, caplog):
    db, engine = _migration_engine(monkeypatch)
    _seed_step5(engine, 33, 33, 34, version=5)
    with caplog.at_level("WARNING"):
        result = db._migrate_step5_weights()
    assert result["weights"] == "defaults" and result["old"] == {"current_ratio": 33, "debt_to_ebitda": 33, "debt_servicing": 34}
    assert _step5_row(engine) == ((25, 45, 30), 6)  # Current Ratio, Debt/EBITDA, Debt Servicing; weights_version bumped
    assert "33" in caplog.text  # logged, not silent


def test_a_customised_step5_row_that_breaks_the_new_rules_is_also_reset(monkeypatch):
    for old in ((20, 20, 60), (30, 40, 30), (10, 50, 40)):  # bound broken, tie, bound broken
        db, engine = _migration_engine(monkeypatch)
        _seed_step5(engine, *old)
        assert db._migrate_step5_weights()["weights"] == "defaults"
        assert _step5_row(engine) == ((25, 45, 30), 6)


def test_a_valid_customised_step5_row_is_left_alone_and_the_migration_is_idempotent(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    _seed_step5(engine, 20, 50, 30, version=7)
    assert db._migrate_step5_weights()["weights"] is None
    assert _step5_row(engine) == ((20, 50, 30), 7)  # no bump
    with Session(engine) as session:
        row = session.get(ScoreWeightSettings, "default")
        row.step5_current_ratio, row.step5_debt_to_ebitda, row.step5_debt_servicing = 33, 33, 34
        session.commit()
    assert db._migrate_step5_weights()["weights"] == "defaults"
    assert db._migrate_step5_weights()["weights"] is None and _step5_row(engine) == ((25, 45, 30), 8)


def test_an_unseeded_database_has_no_step5_row_to_migrate(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    assert db._migrate_step5_weights() == {"weights": None}


def test_a_valid_step5_row_issues_no_write_at_all(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    _seed_step5(engine, 25, 45, 30)
    from sqlalchemy import event

    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *a: statements.append(stmt))
    db._migrate_step5_weights()
    assert not [x for x in statements if x.strip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]


def test_init_db_runs_the_step5_migration_after_the_overall_one(monkeypatch):
    db, engine = _migration_engine(monkeypatch)
    _seed_step5(engine, 33, 33, 34)
    with Session(engine) as session:  # the pre-2026-10-07 Overall set too: both migrations bump the version once each
        row = session.get(ScoreWeightSettings, "default")
        row.overall_financials, row.overall_growth, row.overall_profitability, row.overall_debt = 24, 10, 20, 15
        session.commit()
    db._migrate_moat_and_overall_weights()
    db._migrate_step5_weights()
    assert _step5_row(engine) == ((25, 45, 30), 7)
    assert _overall(engine) == ((30, 20, 20, 30), 7)


def test_a_stale_step5_row_never_scores_even_before_it_is_migrated(monkeypatch, caplog):
    # A cron job or the recompute subprocess can read the row before the app's init_db has migrated it: the snapshot serves the
    # defaults for the Step 5 group (and leaves every other group as saved) rather than weights that would let a breach pass.
    db, engine = _migration_engine(monkeypatch)
    _seed_step5(engine, 33, 33, 34)
    from data.score_weights import invalidate_cache, load_score_weights

    invalidate_cache()
    with caplog.at_level("WARNING"):
        snapshot = load_score_weights(engine)
    assert snapshot.weights == DEFAULT_WEIGHTS and snapshot.version == 5
    assert "break the current bounds" in caplog.text
    invalidate_cache()
