from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import core.main as main
from helpers.liquidity_zone_config import DEFAULT_CLUSTER_PCT, DEFAULT_NUM_ZONES, DEFAULT_SWING_BARS


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_get_returns_lazily_seeded_defaults(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    response = client.get("/api/config/liquidity-zones")

    assert response.status_code == 200
    body = response.json()
    assert body["daily_swing_bars"] == DEFAULT_SWING_BARS
    assert body["daily_cluster_pct"] == DEFAULT_CLUSTER_PCT
    assert body["daily_num_zones"] == DEFAULT_NUM_ZONES
    assert body["weekly_swing_bars"] == DEFAULT_SWING_BARS
    assert body["weekly_cluster_pct"] == DEFAULT_CLUSTER_PCT
    assert body["weekly_num_zones"] == DEFAULT_NUM_ZONES


def test_put_updates_both_timeframes_independently_and_subsequent_get_reflects_it(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    put_response = client.put(
        "/api/config/liquidity-zones",
        json={
            "daily_swing_bars": 3,
            "daily_cluster_pct": 1.5,
            "daily_num_zones": 4,
            "weekly_swing_bars": 2,
            "weekly_cluster_pct": 3.0,
            "weekly_num_zones": 5,
        },
    )
    assert put_response.status_code == 200
    body = put_response.json()
    assert body["daily_swing_bars"] == 3
    assert body["weekly_num_zones"] == 5

    get_response = client.get("/api/config/liquidity-zones")
    assert get_response.status_code == 200
    got = get_response.json()
    assert got["daily_cluster_pct"] == 1.5
    assert got["weekly_cluster_pct"] == 3.0
