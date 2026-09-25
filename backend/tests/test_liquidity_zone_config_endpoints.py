from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import core.main as main
from helpers.liquidity_zone_config import (
    DEFAULT_BREACH_RECENCY_BARS,
    DEFAULT_CLUSTER_PCT,
    DEFAULT_MAX_LPS_PER_SIDE,
    DEFAULT_OVER_CAP_PRIORITY,
    DEFAULT_SWING_BARS,
)

_VALID_BODY = {
    "swing_bars_each_side": 3,
    "cluster_pct": 1.5,
    "max_lps_per_side": 4,
    "over_cap_priority": "most_recent",
    "keep_last_breached_support": False,
    "keep_last_breached_resistance": True,
    "only_keep_if_breached_recently": False,
    "breach_recency_bars": 8,
}


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_get_returns_lazily_seeded_defaults(monkeypatch):
    _fresh_engine(monkeypatch)
    body = TestClient(main.app).get("/api/config/liquidity-zones").json()

    assert body["swing_bars_each_side"] == DEFAULT_SWING_BARS
    assert body["cluster_pct"] == DEFAULT_CLUSTER_PCT
    assert body["max_lps_per_side"] == DEFAULT_MAX_LPS_PER_SIDE
    assert body["over_cap_priority"] == DEFAULT_OVER_CAP_PRIORITY
    assert body["keep_last_breached_support"] is True
    assert body["keep_last_breached_resistance"] is True
    assert body["only_keep_if_breached_recently"] is True
    assert body["breach_recency_bars"] == DEFAULT_BREACH_RECENCY_BARS
    assert not any(k.startswith(("daily_", "weekly_")) for k in body)


def test_put_updates_the_single_shared_block(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    put = client.put("/api/config/liquidity-zones", json=_VALID_BODY)
    assert put.status_code == 200

    got = client.get("/api/config/liquidity-zones").json()
    for key, value in _VALID_BODY.items():
        assert got[key] == value


def test_put_rejects_invalid_values(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    assert client.put("/api/config/liquidity-zones", json={**_VALID_BODY, "over_cap_priority": "bogus"}).status_code == 422
    assert client.put("/api/config/liquidity-zones", json={**_VALID_BODY, "max_lps_per_side": 0}).status_code == 422
    assert client.put("/api/config/liquidity-zones", json={**_VALID_BODY, "swing_bars_each_side": 0}).status_code == 422
    assert client.put("/api/config/liquidity-zones", json={**_VALID_BODY, "cluster_pct": -1}).status_code == 422
