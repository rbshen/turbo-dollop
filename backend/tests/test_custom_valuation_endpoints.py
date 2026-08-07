from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
from core.models import TickerCustomValuation
from core.schemas import Step3Inputs, Step3Out

# These endpoint tests fake main's own get_step3_data/get_active_valuation/
# compute_ticker_score bindings wholesale -- same philosophy as
# test_ticker_score_endpoint.py's _patch_score_steps: get_active_valuation's
# own real choke-point logic (auto vs. active custom valuation) already has
# dedicated coverage in test_step3_data.py, so this file's job is purely
# endpoint-level concerns (CRUD persistence, response shape, the
# compute_ticker_score recompute trigger, validation, 404/400 handling).
FAKE_AUTO = Step3Out(
    ticker="AAPL",
    company_type="Standard",
    selected_method="DCF",
    inputs=Step3Inputs(current_value=1.0, growth_yr_11_20=0.04, last_close=100.0),
    intrinsic_value_per_share=120.0,
    discount_premium_pct=-0.1667,
    verdict="undervalued",
    valuation_source="auto",
)

VALID_PSG_BODY = {
    "method": "PSG",
    "sales_per_share": 10.0,
    "projected_growth_rate": 0.10,
    "fair_psg_ratio": 0.2,
}

INVALID_PSG_BODY = {"method": "PSG"}  # missing sales_per_share/projected_growth_rate/fair_psg_ratio


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def _patch_valuation_and_score(monkeypatch, calls=None):
    calls = calls if calls is not None else []

    async def fake_get_step3_data(ticker, cache_only=False, step2_out=None):
        return FAKE_AUTO

    async def fake_get_active_valuation(ticker, cache_only=False, step2_out=None):
        return FAKE_AUTO

    async def fake_compute_ticker_score(ticker, cache_only=False):
        calls.append((ticker, cache_only))
        return None

    monkeypatch.setattr(main, "get_step3_data", fake_get_step3_data)
    monkeypatch.setattr(main, "get_active_valuation", fake_get_active_valuation)
    monkeypatch.setattr(main, "compute_ticker_score", fake_compute_ticker_score)
    return calls


def test_get_returns_absent_shape_when_nothing_saved(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/custom-valuation")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["saved"] is False
    assert body["method"] is None
    assert body["is_active"] is False
    assert body["active_verdict"]["verdict"] == "undervalued"


def test_put_saves_without_activating(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        response = client.put("/api/tickers/AAPL/custom-valuation", json=VALID_PSG_BODY)

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["method"] == "PSG"
    assert body["sales_per_share"] == 10.0
    assert body["is_active"] is False
    # A brand-new, inactive save has no live effect -- no recompute needed.
    assert calls == []

    with Session(engine) as session:
        row = session.get(TickerCustomValuation, "AAPL")
    assert row is not None
    assert row.method == "PSG"
    assert row.is_active is False


def test_put_rejects_a_method_missing_required_inputs(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        response = client.put("/api/tickers/AAPL/custom-valuation", json=INVALID_PSG_BODY)

    assert response.status_code == 400
    assert "PSG" in response.json()["detail"]


def test_activate_returns_404_when_nothing_saved(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        response = client.post("/api/tickers/AAPL/custom-valuation/activate")

    assert response.status_code == 404


def test_activate_flips_is_active_and_triggers_recompute(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        client.put("/api/tickers/AAPL/custom-valuation", json=VALID_PSG_BODY)
        response = client.post("/api/tickers/AAPL/custom-valuation/activate")

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    assert calls == [("AAPL", True)]


def test_put_while_active_stays_active_and_triggers_recompute(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        client.put("/api/tickers/AAPL/custom-valuation", json=VALID_PSG_BODY)
        client.post("/api/tickers/AAPL/custom-valuation/activate")
        calls.clear()  # only care about the PUT-while-active call below
        response = client.put(
            "/api/tickers/AAPL/custom-valuation",
            json={"method": "PSG", "sales_per_share": 20.0, "projected_growth_rate": 0.15, "fair_psg_ratio": 0.25},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is True  # PUT never touches is_active
    assert body["sales_per_share"] == 20.0
    # Already-active row's values changed -- Screener/Watchlist's cached
    # TickerScore must be refreshed, same as activate/deactivate/delete.
    assert calls == [("AAPL", True)]

    with Session(engine) as session:
        row = session.get(TickerCustomValuation, "AAPL")
    assert row.is_active is True


def test_put_while_inactive_does_not_trigger_recompute(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        client.put("/api/tickers/AAPL/custom-valuation", json=VALID_PSG_BODY)
        calls.clear()
        client.put(
            "/api/tickers/AAPL/custom-valuation",
            json={"method": "PSG", "sales_per_share": 20.0, "projected_growth_rate": 0.15, "fair_psg_ratio": 0.25},
        )

    assert calls == []


def test_deactivate_keeps_row_and_triggers_recompute(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        client.put("/api/tickers/AAPL/custom-valuation", json=VALID_PSG_BODY)
        client.post("/api/tickers/AAPL/custom-valuation/activate")
        calls.clear()
        response = client.post("/api/tickers/AAPL/custom-valuation/deactivate")

    assert response.status_code == 200
    body = response.json()
    assert body["saved"] is True
    assert body["is_active"] is False
    assert calls == [("AAPL", True)]

    with Session(engine) as session:
        row = session.get(TickerCustomValuation, "AAPL")
    assert row is not None  # deactivate keeps the saved inputs


def test_deactivate_is_a_no_op_when_nothing_saved(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        response = client.post("/api/tickers/AAPL/custom-valuation/deactivate")

    assert response.status_code == 200
    assert response.json()["saved"] is False
    assert calls == []


def test_delete_removes_active_row_and_triggers_recompute(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        client.put("/api/tickers/AAPL/custom-valuation", json=VALID_PSG_BODY)
        client.post("/api/tickers/AAPL/custom-valuation/activate")
        calls.clear()
        response = client.delete("/api/tickers/AAPL/custom-valuation")

    assert response.status_code == 204
    assert calls == [("AAPL", True)]

    with Session(engine) as session:
        row = session.get(TickerCustomValuation, "AAPL")
    assert row is None  # reverted to Auto as a side effect of this request


def test_delete_is_a_no_op_when_nothing_saved(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_valuation_and_score(monkeypatch)

    with TestClient(main.app) as client:
        response = client.delete("/api/tickers/AAPL/custom-valuation")

    assert response.status_code == 204
    assert calls == []
