"""GET /api/watchlists/export-data: the multi-list export's payload (per list, its tickers with the cached profile's
exchange and sector), from STORED data only. Every test builds its own in-memory engine and patches it onto every module
that reads."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
import data.watchlist_data as watchlist_data
from clients.fmp_client import fmp_client
from core.models import FundamentalsCache, Watchlist, WatchlistTicker

NOW = datetime(2026, 1, 1)


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(main, "engine", eng)
    monkeypatch.setattr(watchlist_data, "engine", eng)

    def _no_network(*args, **kwargs):
        raise AssertionError("the export data must never reach FMP")

    monkeypatch.setattr(fmp_client, "get", _no_network)
    return eng


def _list(engine, name, tickers=()):
    with Session(engine) as session:
        watchlist = Watchlist(name=name, created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for i, ticker in enumerate(tickers):
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=ticker, added_at=datetime(2026, 1, 1, 0, i)))
        session.commit()
        return watchlist.id


def _profile(engine, ticker, **fields):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(),
                raw_json=json.dumps([{"symbol": ticker, **fields}]),
            )
        )
        session.commit()


def _get(*ids):
    with TestClient(main.app) as client:
        return client.get("/api/watchlists/export-data", params=[("ids", i) for i in ids])


def test_returns_each_list_with_exchange_and_sector_in_added_order(engine):
    a = _list(engine, "Growth", ["NVDA", "AAPL"])
    _profile(engine, "NVDA", exchangeShortName="NASDAQ", sector="Technology")
    _profile(engine, "AAPL", exchangeShortName="NASDAQ", sector="Technology")

    response = _get(a)

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": a,
            "name": "Growth",
            "tickers": [
                {"ticker": "NVDA", "exchange": "NASDAQ", "sector": "Technology"},
                {"ticker": "AAPL", "exchange": "NASDAQ", "sector": "Technology"},
            ],
        }
    ]


def test_lists_come_back_in_the_requested_order(engine):
    a = _list(engine, "A", ["AAPL"])
    b = _list(engine, "B", ["MSFT"])

    assert [w["id"] for w in _get(b, a).json()] == [b, a]


def test_an_empty_list_is_returned_with_no_tickers(engine):
    a = _list(engine, "Empty")

    assert _get(a).json() == [{"id": a, "name": "Empty", "tickers": []}]


def test_a_ticker_with_no_cached_profile_has_no_exchange_and_no_sector(engine):
    a = _list(engine, "A", ["NEWCO"])

    assert _get(a).json()[0]["tickers"] == [{"ticker": "NEWCO", "exchange": None, "sector": None}]


def test_a_fund_has_no_sector_even_when_its_profile_carries_one(engine):
    a = _list(engine, "ETF", ["SPY", "XLK"])
    _profile(engine, "SPY", exchangeShortName="AMEX", sector="State Street", isEtf=True)
    _profile(engine, "XLK", exchangeShortName="AMEX", sector="Technology", isFund=True)

    tickers = _get(a).json()[0]["tickers"]

    assert tickers == [
        {"ticker": "SPY", "exchange": "AMEX", "sector": None},
        {"ticker": "XLK", "exchange": "AMEX", "sector": None},
    ]


def test_exchange_falls_back_to_the_profile_exchange_field(engine):
    a = _list(engine, "A", ["CNSWF"])
    _profile(engine, "CNSWF", exchange="OTC", sector="Technology")

    assert _get(a).json()[0]["tickers"][0]["exchange"] == "OTC"


def test_an_unknown_id_is_a_404_naming_it_and_returns_nothing_partial(engine):
    a = _list(engine, "A", ["AAPL"])

    response = _get(a, 999)

    assert response.status_code == 404
    assert "999" in response.json()["detail"]


def test_no_ids_is_a_validation_error(engine):
    with TestClient(main.app) as client:
        assert client.get("/api/watchlists/export-data").status_code == 422


def test_a_repeated_id_is_returned_once(engine):
    a = _list(engine, "A", ["AAPL"])

    assert [w["id"] for w in _get(a, a).json()] == [a]
