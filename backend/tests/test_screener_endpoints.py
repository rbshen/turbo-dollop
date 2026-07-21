from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import main
from models import TickerScore


def _fresh_engine(monkeypatch):
    # StaticPool: TestClient runs each request in a worker thread, and a
    # plain "sqlite://" in-memory DB is otherwise scoped per-connection --
    # without a shared pool, the tables created here wouldn't be visible to
    # the request thread's own connection.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_screener_list_returns_stored_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TickerScore(
                ticker="AAPL",
                company_name="Apple Inc.",
                sector="Technology",
                company_type="Standard",
                step1_score=90,
                step1_verdict="Strong Pass",
                overall_score=85,
                overall_verdict="Pass",
                market_cap=3_000_000_000_000.0,
                pe_ratio=30.0,
                beta=1.2,
                computed_at=datetime(2026, 1, 1),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/screener")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"
    assert body[0]["company_name"] == "Apple Inc."
    assert body[0]["overall_score"] == 85
    assert body[0]["market_cap"] == 3_000_000_000_000.0


def test_screener_list_is_empty_when_no_rows_exist(monkeypatch):
    _fresh_engine(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/screener")

    assert response.status_code == 200
    assert response.json() == []


def test_screener_recompute_calls_recompute_all_and_returns_its_summary(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_recompute_all(tickers=None):
        assert tickers is None  # the endpoint always recomputes the full stored list
        return {"processed": 503, "failed": 2, "duration_seconds": 12.3, "failures": [("BRK.B", "402"), ("BF.B", "402")]}

    monkeypatch.setattr(main, "recompute_all", fake_recompute_all)

    with TestClient(main.app) as client:
        response = client.post("/api/screener/recompute")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 503
    assert body["failed"] == 2
    assert body["failures"] == [["BRK.B", "402"], ["BF.B", "402"]]


def test_screener_recompute_never_calls_the_script_entry_point(monkeypatch):
    """Regression guard: the endpoint must call recompute_all() directly,
    not recompute_ticker_scores.main() (which also reconfigures logging and
    calls init_db() -- see recompute_ticker_scores.py's docstring)."""
    _fresh_engine(monkeypatch)
    calls = []

    async def fake_recompute_all(tickers=None):
        calls.append(tickers)
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("the endpoint must not call recompute_ticker_scores.main()")

    monkeypatch.setattr(main, "recompute_all", fake_recompute_all)
    import recompute_ticker_scores

    monkeypatch.setattr(recompute_ticker_scores, "main", fail_if_called)

    with TestClient(main.app) as client:
        response = client.post("/api/screener/recompute")

    assert response.status_code == 200
    assert calls == [None]
