from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import core.main as main


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_get_returns_lazily_seeded_us_default(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    response = client.get("/api/config/discount-rate")

    assert response.status_code == 200
    body = response.json()
    assert body["region"] == "US"
    assert body["risk_free_rate"] == 0.03608
    assert body["market_risk_premium"] == 0.02728
    assert body["updated_at"] is not None


def test_put_requires_region_and_updates_that_regions_row(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    put_response = client.put(
        "/api/config/discount-rate", json={"region": "US", "risk_free_rate": 0.04, "market_risk_premium": 0.03}
    )
    assert put_response.status_code == 200
    assert put_response.json()["risk_free_rate"] == 0.04

    get_response = client.get("/api/config/discount-rate")
    assert get_response.json()["risk_free_rate"] == 0.04


def test_put_without_region_is_rejected(monkeypatch):
    # region has no default on DiscountRateConfigIn as of the HK market
    # support round -- every PUT must say which region it's updating now
    # that this isn't US-only.
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    response = client.put("/api/config/discount-rate", json={"risk_free_rate": 0.04, "market_risk_premium": 0.03})

    assert response.status_code == 422


def test_list_endpoint_eagerly_seeds_us_on_a_brand_new_db(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    response = client.get("/api/config/discount-rates")

    assert response.status_code == 200
    body = response.json()
    assert [row["region"] for row in body] == ["US"]


def test_list_endpoint_includes_a_seeded_hk_row_once_one_exists(monkeypatch):
    _fresh_engine(monkeypatch)
    client = TestClient(main.app)

    # PUT with region="HK" seeds (via get_discount_rate_config's own
    # get-or-create) and then updates the HK row in one call -- same path
    # step3_data.py's lazy seeding would take, just triggered explicitly
    # here rather than by a ticker valuation.
    put_response = client.put(
        "/api/config/discount-rate", json={"region": "HK", "risk_free_rate": 0.05, "market_risk_premium": 0.04}
    )
    assert put_response.status_code == 200

    response = client.get("/api/config/discount-rates")
    body = response.json()
    assert sorted(row["region"] for row in body) == ["HK", "US"]
    hk_row = next(row for row in body if row["region"] == "HK")
    assert hk_row["risk_free_rate"] == 0.05
    assert hk_row["market_risk_premium"] == 0.04
