from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import data.momentum_data as momentum_data
from core.main import app
from core.models import MomentumSnapshot, TickerScore


def _fresh_engine(monkeypatch):
    # StaticPool, matching test_cron_health_endpoint.py's convention -- the
    # TestClient runs the sync endpoint function in a worker thread, and a
    # bare `sqlite://` engine would hand that thread its own empty in-memory
    # DB otherwise.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(momentum_data, "engine", engine)
    return engine


def test_empty_before_any_snapshot(monkeypatch):
    _fresh_engine(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/api/momentum")
    assert response.status_code == 200
    body = response.json()
    assert body == {"as_of_date": None, "computed_at": None, "rows": []}


def test_current_and_previous_return_the_right_months(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAA", moat="wide_moat", company_name="AAA Inc", overall_score=70, computed_at=datetime.now()))
        session.add(
            MomentumSnapshot(
                ticker="AAA",
                as_of_date=date(2026, 7, 31),
                computed_at=datetime.now(),
                moat="wide_moat",
                return_3mo=0.1,
                return_6mo=0.2,
                return_12mo=0.3,
                composite_score=0.2,
                rank=1,
            )
        )
        session.add(
            MomentumSnapshot(
                ticker="AAA",
                as_of_date=date(2026, 8, 31),
                computed_at=datetime.now(),
                moat="wide_moat",
                return_3mo=0.15,
                return_6mo=0.25,
                return_12mo=0.35,
                composite_score=0.25,
                rank=1,
            )
        )
        session.commit()

    with TestClient(app) as client:
        current = client.get("/api/momentum?period=current").json()
        previous = client.get("/api/momentum?period=previous").json()

    assert current["as_of_date"] == "2026-08-31"
    assert current["rows"][0]["overall_score"] == 70
    assert current["rows"][0]["company_name"] == "AAA Inc"
    assert previous["as_of_date"] == "2026-07-31"


def test_previous_is_empty_when_only_one_month_exists(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            MomentumSnapshot(
                ticker="AAA",
                as_of_date=date(2026, 8, 31),
                computed_at=datetime.now(),
                moat="wide_moat",
                return_3mo=0.1,
                return_6mo=0.2,
                return_12mo=0.3,
                composite_score=0.2,
                rank=1,
            )
        )
        session.commit()

    with TestClient(app) as client:
        response = client.get("/api/momentum?period=previous")
    body = response.json()
    assert body["as_of_date"] is None
    assert body["rows"] == []
