from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import core.main as main


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_get_returns_lazily_seeded_default(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    response = client.get("/api/config/reit-dividend-yield")

    assert response.status_code == 200
    body = response.json()
    assert body["threshold_pct"] == 5.0
    assert body["updated_at"] is not None


def test_put_updates_value_and_subsequent_get_reflects_it(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    put_response = client.put("/api/config/reit-dividend-yield", json={"threshold_pct": 6.5})
    assert put_response.status_code == 200
    assert put_response.json()["threshold_pct"] == 6.5

    get_response = client.get("/api/config/reit-dividend-yield")
    assert get_response.status_code == 200
    assert get_response.json()["threshold_pct"] == 6.5
