from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.entry_signal_data as entry_signal_data
from core.models import TechnicalEntrySignal


def _fresh_engine(monkeypatch):
    # StaticPool -- TestClient's request runs the async endpoint on a
    # different thread than this test function, and a plain :memory: sqlite
    # engine gives each new connection its own separate empty database
    # unless pinned to one shared connection (see test_ticker_score_endpoint.py's
    # own comment for the same fix).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(entry_signal_data, "engine", engine)
    return engine


def test_returns_active_true_for_a_recent_fire(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=datetime.now() - timedelta(days=1),
                pct_b=0.02,
                rsi=25.3,
                close=210.5,
                stop_price=205.0,
                source="yahoo",
                as_of=datetime(2026, 9, 8, 15, 30),
                computed_at=datetime(2026, 9, 9, 3, 20),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/entry-signal")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AAPL"
    assert body["active"] is True
    assert body["pct_b"] == 0.02
    assert body["rsi"] == 25.3
    assert body["stop_price"] == 205.0
    assert body["source"] == "yahoo"


def test_returns_active_false_for_a_fire_older_than_seven_days(monkeypatch):
    # The row/fired-bar snapshot is still returned in full -- only `active`
    # itself reads False, per is_entry_signal_active's derived-not-stored
    # contract. The row is never cleaned up by a separate job.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=datetime.now() - timedelta(days=10),
                pct_b=0.02,
                rsi=25.3,
                close=210.5,
                stop_price=205.0,
                source="yahoo",
                as_of=datetime(2026, 9, 8, 15, 30),
                computed_at=datetime(2026, 9, 9, 3, 20),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/entry-signal")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is False
    assert body["fired_at"] is not None
    assert body["pct_b"] == 0.02


def test_returns_active_false_and_null_fired_fields_when_never_fired(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="AAPL",
                signal_type="bb_rsi",
                timeframe="2h",
                source="yahoo",
                as_of=datetime(2026, 9, 8, 15, 30),
                computed_at=datetime(2026, 9, 9, 3, 20),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/entry-signal")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is False
    assert body["fired_at"] is None
    assert body["pct_b"] is None
    assert body["stop_price"] is None


def test_returns_null_for_a_ticker_never_computed(monkeypatch):
    _fresh_engine(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/ZZZZINVALID/entry-signal")

    assert response.status_code == 200
    assert response.json() is None
