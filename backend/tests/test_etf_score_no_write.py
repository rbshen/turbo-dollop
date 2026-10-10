"""GET /api/tickers/{t}/score computes an ETF's response but writes no TickerScore row (compute_ticker_score(persist_etf=False)):
an ETF's score row is frozen since the 2026-10-03 cutover, and the ETF header calls /score on every page load, so a write
there was one avoidable write per load. Stocks are upserted exactly as before. Everything that used to find an ETF through
its TickerScore row (known_etf_tickers, the universe partition, the Watchlist row, the wipe candidates) must still work
from the cached profile alone."""

import asyncio
import sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.db as core_db
from conftest import real_engine as _real_core_engine  # core.db.engine itself is isolated per test (conftest._isolate_core_db_engine)
import core.main as main
import data.tracked_universe as tu
import data.watchlist_data as watchlist_data
from clients.fmp_client import FMPClient, fmp_client
from core.models import TickerScore, TickerView, WatchlistTicker
from data.etf_data import known_etf_tickers

ETF_PROFILE = [{"companyName": "ProShares Ultra Semis", "exchange": "AMEX", "isEtf": True, "isFund": False}]
STOCK_PROFILE = [{"companyName": "Apple Inc.", "exchange": "NASDAQ", "isEtf": False, "isFund": False, "sector": "Technology"}]
QUOTE = [{"price": 50.0, "change": 1.0, "changePercentage": 2.0, "marketCap": 1e9}]
FROZEN_AT = datetime(2026, 10, 3, 3, 25)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    real = _real_core_engine
    for module in list(sys.modules.values()):
        if module is not core_db and getattr(module, "engine", None) is real:
            monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(core_db, "engine", engine)

    state = {"profile": ETF_PROFILE}
    answers = {"get_quote": QUOTE}

    def fake(name):
        async def _call(*_a, **_k):
            return state["profile"] if name == "get_profile" else answers.get(name, [])

        return _call

    for name in dir(FMPClient):
        if name.startswith("get_") and callable(getattr(FMPClient, name)):
            monkeypatch.setattr(fmp_client, name, fake(name))

    writes: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE")):
            writes.append(statement.lstrip())

    event.listen(engine, "before_cursor_execute", record)
    return engine, state, writes


def _score_writes(writes):
    return [w for w in writes if "tickerscore" in w.lower()]


def _warm_profile(client, ticker):
    # /summary caches the profile (what a real page view does first); the score then reads it from the cache.
    assert client.get(f"/api/tickers/{ticker}/summary").status_code == 200


def test_an_etf_score_request_writes_no_tickerscore_row_and_keeps_its_shape(env):
    engine, _state, writes = env
    with TestClient(main.app) as client:
        _warm_profile(client, "SOXL")
        writes.clear()
        bodies = [client.get("/api/tickers/SOXL/score") for _ in range(2)]
    assert [r.status_code for r in bodies] == [200, 200]
    assert _score_writes(writes) == []
    body = bodies[0].json()
    assert body["ticker"] == "SOXL" and body["is_etf"] is True and body["overall_score"] is None
    assert set(body) == set(main.TickerScoreOut.model_fields)  # the same shape every stock row has
    with Session(engine) as session:
        assert session.get(TickerScore, "SOXL") is None


def test_a_frozen_etf_row_is_left_untouched_and_the_response_is_still_served(env):
    engine, _state, writes = env
    with Session(engine) as session:
        session.add(TickerScore(ticker="SOXL", company_name="old", is_etf=True, computed_at=FROZEN_AT))
        session.commit()
    with TestClient(main.app) as client:
        _warm_profile(client, "SOXL")
        writes.clear()
        response = client.get("/api/tickers/SOXL/score")
    assert response.status_code == 200 and response.json()["is_etf"] is True
    assert _score_writes(writes) == []
    with Session(engine) as session:
        row = session.get(TickerScore, "SOXL")
        assert (row.company_name, row.computed_at) == ("old", FROZEN_AT)


def test_a_stock_score_request_still_upserts_its_row_as_before(env):
    engine, state, writes = env
    state["profile"] = STOCK_PROFILE
    with TestClient(main.app) as client:
        _warm_profile(client, "AAPL")
        writes.clear()
        assert client.get("/api/tickers/AAPL/score").status_code == 200
    assert len(_score_writes(writes)) == 1 and _score_writes(writes)[0].upper().startswith("INSERT")
    with Session(engine) as session:
        row = session.get(TickerScore, "AAPL")
        assert row is not None and row.is_etf is False


def test_a_browsed_etf_without_a_score_row_is_still_an_etf_everywhere(env):
    engine, _state, _writes = env
    with TestClient(main.app) as client:
        _warm_profile(client, "SOXL")
        client.get("/api/tickers/SOXL/score")
    with Session(engine) as session:
        assert session.get(TickerScore, "SOXL") is None
        assert known_etf_tickers(session, ["SOXL"]) == {"SOXL"}  # from the cached profile alone
        stocks, etfs = tu.partition_known_tickers(session)
        assert "SOXL" in etfs and "SOXL" not in stocks
        assert tu.classify_one(session, "SOXL") is not None  # known, so it gets a classification (browsed: not added)


def test_the_watchlist_etf_row_works_without_a_score_row(env):
    engine, _state, _writes = env
    with TestClient(main.app) as client:
        _warm_profile(client, "SOXL")

    async def consensus(ticker):
        return "N/A"

    rows = asyncio.run(watchlist_data.get_watchlist_rows([WatchlistTicker(watchlist_id=1, ticker="SOXL", added_at=FROZEN_AT)]))
    assert [(r.ticker, r.is_etf) for r in rows] == [("SOXL", True)]


def test_the_wipe_candidate_logic_handles_an_etf_with_no_score_row(env):
    engine, _state, _writes = env
    now = datetime(2026, 12, 1, 12)
    with TestClient(main.app) as client:
        _warm_profile(client, "SOXL")
    with Session(engine) as session:
        assert session.get(TickerScore, "SOXL") is None
        session.merge(TickerView(ticker="SOXL", last_viewed_at=now - timedelta(days=45)))
        session.commit()
        decision = tu.classify_wipe_candidates(session, now, tickers=["SOXL"])["SOXL"]
        assert decision.decision == "wipe" and decision.has_data and decision.protections == ()
        added = tu.classify_wipe_candidates(session, now, added={"SOXL"}, tickers=["SOXL"])["SOXL"]
        assert added.decision == "protected"
