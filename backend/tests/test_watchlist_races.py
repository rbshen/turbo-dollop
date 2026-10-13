"""Watchlist create / rename / add under a race: the check-then-write gap returns the same clean 409 / 400 the pre-check does (never a 500),
and the 100-ticker cap is re-checked inside the write transaction (cleanup batch 2026-10-13).

A race is simulated two ways: the pre-check is patched to say "free" while the row already exists (the other request won between the check
and the write), and two real threads with their own sessions on a temp file database."""

import threading
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.watchlists as watchlists
from core.models import Watchlist, WatchlistTicker

NOW = datetime(2026, 1, 1)


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(main, "engine", eng)
    return eng


def _watchlist(engine, name="Test", tickers=()):
    with Session(engine) as session:
        row = Watchlist(name=name, created_at=NOW, updated_at=NOW)
        session.add(row)
        session.commit()
        session.refresh(row)
        for t in tickers:
            session.add(WatchlistTicker(watchlist_id=row.id, ticker=t, added_at=NOW))
        session.commit()
        return row.id


def _names(engine):
    with Session(engine) as session:
        return sorted(w.name for w in session.exec(select(Watchlist)).all())


def _members(engine, watchlist_id):
    with Session(engine) as session:
        return sorted(t.ticker for t in session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id)).all())


# ---- create / rename ------------------------------------------------------------------------------------------------------------


def test_create_race_is_a_409_not_a_500(engine, monkeypatch):
    _watchlist(engine, "Dup")
    monkeypatch.setattr(main, "get_watchlist_by_name", lambda session, name: None)  # the check ran before the other request's insert
    with TestClient(main.app) as client:
        response = client.post("/api/watchlists", json={"name": "Dup"})
    assert response.status_code == 409
    assert response.json() == {"detail": "A watchlist named 'Dup' already exists"}
    assert _names(engine) == ["Dup"]


def test_create_race_leaves_the_session_usable(engine, monkeypatch):
    _watchlist(engine, "Dup")
    monkeypatch.setattr(main, "get_watchlist_by_name", lambda session, name: None)
    with TestClient(main.app) as client:
        assert client.post("/api/watchlists", json={"name": "Dup"}).status_code == 409
        assert client.post("/api/watchlists", json={"name": "Fresh"}).status_code == 201


def test_rename_race_is_a_409_not_a_500(engine, monkeypatch):
    _watchlist(engine, "Taken")
    other = _watchlist(engine, "Mine")
    monkeypatch.setattr(main, "get_watchlist_by_name", lambda session, name: None)
    with TestClient(main.app) as client:
        response = client.put(f"/api/watchlists/{other}", json={"name": "Taken"})
    assert response.status_code == 409
    assert response.json() == {"detail": "A watchlist named 'Taken' already exists"}
    assert _names(engine) == ["Mine", "Taken"]  # the rename did not happen


def test_the_pre_check_409_is_unchanged(engine):
    _watchlist(engine, "Taken")
    other = _watchlist(engine, "Mine")
    with TestClient(main.app) as client:
        assert client.post("/api/watchlists", json={"name": "Taken"}).status_code == 409
        assert client.put(f"/api/watchlists/{other}", json={"name": "Taken"}).status_code == 409


# ---- single add -----------------------------------------------------------------------------------------------------------------


def test_add_race_is_a_409_not_a_500(engine, monkeypatch):
    wid = _watchlist(engine, tickers=["AAPL"])
    monkeypatch.setattr(main, "get_watchlist_ticker", lambda session, watchlist_id, ticker: None)
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "AAPL"})
    assert response.status_code == 409
    assert response.json() == {"detail": "AAPL is already in this watchlist"}
    assert _members(engine, wid) == ["AAPL"]


def test_add_cap_is_rechecked_inside_the_write_transaction(engine, monkeypatch):
    wid = _watchlist(engine, tickers=[f"T{i:03d}" for i in range(100)])
    monkeypatch.setattr(main, "count_net_new_tickers", lambda session, watchlist_id, tickers: (99, 1))  # a stale count: the list filled meanwhile
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "AAPL"})
    assert response.status_code == 400
    assert "100/100" in response.json()["detail"] and "over the 100 cap" in response.json()["detail"]
    assert len(_members(engine, wid)) == 100 and "AAPL" not in _members(engine, wid)


def test_add_at_exactly_the_cap_still_succeeds(engine):
    wid = _watchlist(engine, tickers=[f"T{i:03d}" for i in range(99)])
    with TestClient(main.app) as client:
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "AAPL"}).status_code == 201
    assert len(_members(engine, wid)) == 100


# ---- bulk add ---------------------------------------------------------------------------------------------------------------------


def test_bulk_cap_is_rechecked_inside_the_write_transaction(engine, monkeypatch):
    wid = _watchlist(engine, tickers=[f"T{i:03d}" for i in range(98)])
    monkeypatch.setattr(main, "count_net_new_tickers", lambda session, watchlist_id, tickers: (90, 3))  # stale: really 98 + 3
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": ["AAA", "BBB", "CCC"]})
    assert response.status_code == 400
    assert "98/100" in response.json()["detail"] and "Adding 3 new tickers" in response.json()["detail"]
    assert len(_members(engine, wid)) == 98  # nothing was inserted


def test_bulk_add_retries_once_when_another_request_added_one_of_the_tickers(engine, monkeypatch):
    wid = _watchlist(engine, tickers=["AAPL"])
    real = watchlists.list_watchlist_tickers
    calls = {"n": 0}

    def stale_first(session, watchlist_id):
        calls["n"] += 1
        return [] if calls["n"] == 1 else real(session, watchlist_id)  # the first membership read predates AAPL's insert

    monkeypatch.setattr(watchlists, "list_watchlist_tickers", stale_first)
    with Session(engine) as session:
        added, already = watchlists.bulk_add_watchlist_tickers(session, wid, ["AAPL", "MSFT"], capacity=100)
    assert (added, already) == (1, 1)
    assert _members(engine, wid) == ["AAPL", "MSFT"]


def test_bulk_add_under_the_cap_is_unchanged(engine):
    wid = _watchlist(engine, tickers=["AAPL"])
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": ["AAPL", "MSFT", "NVDA"]})
    assert response.status_code == 200 and response.json() == {"added": 2, "already_present": 1}


# ---- ETF list ---------------------------------------------------------------------------------------------------------------------


def test_etf_add_race_is_the_idempotent_no_op(engine, monkeypatch):
    wid = _watchlist(engine, "ETF", tickers=["SPY"])
    monkeypatch.setattr(main, "get_watchlist_ticker", lambda session, watchlist_id, ticker: None)
    monkeypatch.setattr(main, "tickers_not_allowed_on_watchlist", lambda session, name, tickers: [])
    with TestClient(main.app) as client:
        response = client.post("/api/tickers/SPY/etf-watchlist")
    assert response.status_code == 200
    assert response.json()["added"] is False and response.json()["watchlist_id"] == wid
    assert _members(engine, wid) == ["SPY"]


# ---- two real writers ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def file_engine(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False, "timeout": 20})

    @event.listens_for(eng, "connect")
    def _wal(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")

    SQLModel.metadata.create_all(eng)
    return eng


def _race(engine, wid, tickers, add):
    barrier = threading.Barrier(len(tickers))
    results: dict[int, str] = {}

    def worker(index, ticker):
        with Session(engine) as session:
            barrier.wait()
            try:
                add(session, wid, ticker)
                results[index] = "ok"
            except watchlists.WatchlistCapacityExceeded:
                results[index] = "full"
            except Exception as exc:  # noqa: BLE001 -- the assertion below names it
                results[index] = type(exc).__name__

    threads = [threading.Thread(target=worker, args=(i, t)) for i, t in enumerate(tickers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    return results


@pytest.mark.parametrize("attempt", range(5))
def test_two_concurrent_adds_cannot_reach_101(file_engine, attempt):
    wid = _watchlist(file_engine, tickers=[f"T{i:03d}" for i in range(99)])
    results = _race(file_engine, wid, ["AAA", "BBB"], lambda s, w, t: watchlists.add_watchlist_ticker(s, w, t, capacity=100))
    assert sorted(results.values()) == ["full", "ok"], results
    assert len(_members(file_engine, wid)) == 100


@pytest.mark.parametrize("attempt", range(5))
def test_two_concurrent_bulk_adds_cannot_exceed_the_cap(file_engine, attempt):
    wid = _watchlist(file_engine, tickers=[f"T{i:03d}" for i in range(96)])
    results = _race(file_engine, wid, ["x", "y"], lambda s, w, t: watchlists.bulk_add_watchlist_tickers(s, w, [f"{t}{i}" for i in range(3)], capacity=100))
    assert sorted(results.values()) == ["full", "ok"], results
    assert len(_members(file_engine, wid)) == 99


def test_two_concurrent_adds_of_the_same_ticker_leave_one_row(file_engine):
    wid = _watchlist(file_engine)
    results = _race(file_engine, wid, ["AAPL", "AAPL"], lambda s, w, t: watchlists.add_watchlist_ticker(s, w, t, capacity=100))
    assert sorted(results.values()) == ["IntegrityError", "ok"], results
    assert _members(file_engine, wid) == ["AAPL"]
