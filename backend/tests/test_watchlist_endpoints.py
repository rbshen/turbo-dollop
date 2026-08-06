from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
from core.models import Watchlist, WatchlistTicker


def _fresh_engine(monkeypatch):
    # StaticPool: TestClient runs each request in a worker thread, and a
    # plain "sqlite://" in-memory DB is otherwise scoped per-connection --
    # without a shared pool, the tables created here wouldn't be visible to
    # the request thread's own connection.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def _make_watchlist(engine, ticker_count: int = 0) -> int:
    with Session(engine) as session:
        watchlist = Watchlist(name="Test", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for i in range(ticker_count):
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=f"TCK{i:04d}", added_at=datetime(2026, 1, 1)))
        session.commit()
        return watchlist.id


def test_watchlist_single_add_succeeds_at_exactly_the_cap(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    watchlist_id = _make_watchlist(engine, ticker_count=99)

    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{watchlist_id}/tickers", json={"ticker": "AAPL"})

    assert response.status_code == 201
    with Session(engine) as session:
        assert session.get(Watchlist, watchlist_id) is not None
        count = len(
            session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id)).all()
        )
    assert count == 100


def test_watchlist_single_add_rejects_ticker_that_would_exceed_the_cap(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    watchlist_id = _make_watchlist(engine, ticker_count=100)

    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{watchlist_id}/tickers", json={"ticker": "AAPL"})

    assert response.status_code == 400
    assert "100/100" in response.json()["detail"]


def test_watchlist_bulk_add_succeeds_up_to_exactly_the_cap(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    watchlist_id = _make_watchlist(engine, ticker_count=0)
    tickers = [f"TCK{i:04d}" for i in range(100)]

    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{watchlist_id}/tickers/bulk", json={"tickers": tickers})

    assert response.status_code == 200
    body = response.json()
    assert body["added"] == 100
    assert body["already_present"] == 0


def test_watchlist_bulk_add_rejects_whole_operation_when_over_the_cap(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    watchlist_id = _make_watchlist(engine, ticker_count=0)
    tickers = [f"TCK{i:04d}" for i in range(101)]

    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{watchlist_id}/tickers/bulk", json={"tickers": tickers})

    assert response.status_code == 400
    with Session(engine) as session:
        count = len(
            session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id)).all()
        )
    # Whole-operation rejection: none of the 101 tickers were inserted.
    assert count == 0
