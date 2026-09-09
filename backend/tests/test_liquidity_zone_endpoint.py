from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.liquidity_zone_data as liquidity_zone_data
from core.models import LiquidityZoneAnalysis


def _fresh_engine(monkeypatch):
    # StaticPool -- TestClient's request runs the endpoint on a different
    # thread than this test function, matching test_entry_signal_endpoint.py's
    # own comment for the identical fix.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(liquidity_zone_data, "engine", engine)
    return engine


def test_returns_both_timeframes_for_a_computed_ticker(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        for timeframe in ("daily", "weekly"):
            session.add(
                LiquidityZoneAnalysis(
                    ticker="AAPL",
                    timeframe=timeframe,
                    last_price=200.0,
                    as_of=datetime(2026, 9, 8).date(),
                    support_zones_json='[{"price": 190.0, "cluster_size": 1, "formed_at": "2026-06-01"}]',
                    resistance_zones_json="[]",
                    source="fmp",
                    computed_at=datetime(2026, 9, 9, 3, 25),
                )
            )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/liquidity-zones")

    assert response.status_code == 200
    body = response.json()
    assert body["daily"]["support_zones"][0]["price"] == 190.0
    assert body["daily"]["support_zones"][0]["distance_pct"] == (190.0 - 200.0) / 200.0 * 100.0
    assert body["daily"]["resistance_zones"] == []
    assert body["weekly"]["support_zones"][0]["price"] == 190.0


def test_returns_null_for_a_ticker_never_computed(monkeypatch):
    _fresh_engine(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/ZZZZINVALID/liquidity-zones")

    assert response.status_code == 200
    assert response.json() is None
