"""GET /api/watchlists/{id}/etf-rows: the ETF table of the list named "ETF", from STORED data only (EtfScreenerRow plus the
cached profile's exchange). Every test builds its own in-memory engine and patches it onto every module that reads."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
import data.watchlist_data as watchlist_data
from clients.fmp_client import fmp_client
from core.models import EtfScreenerRow, FundamentalsCache, TickerScore, TickerView, Watchlist, WatchlistTicker

NOW = datetime(2026, 1, 1)

ROW_FIELDS = {
    "ticker", "name", "exchange", "last_price", "pct_change_1d", "asset_class", "expense_ratio", "aum", "holdings_count",
    "avg_volume_30d", "dividend_yield", "beta", "return_ytd", "return_1y",
}


@pytest.fixture
def engine(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(main, "engine", eng)
    monkeypatch.setattr(watchlist_data, "engine", eng)
    return eng


def _list(engine, name, tickers=(), added_at=None):
    with Session(engine) as session:
        watchlist = Watchlist(name=name, created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for i, ticker in enumerate(tickers):
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=ticker, added_at=datetime(2026, 1, 1, 0, i)))
        session.commit()
        return watchlist.id


def _etf_row(engine, ticker, **fields):
    with Session(engine) as session:
        session.add(EtfScreenerRow(ticker=ticker, **fields))
        session.commit()


def _profile(engine, ticker, exchange):
    with Session(engine) as session:
        session.add(
            FundamentalsCache(
                ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime.now(),
                raw_json=json.dumps([{"symbol": ticker, "exchangeShortName": exchange, "isEtf": True}]),
            )
        )
        session.commit()


def _get(wid):
    with TestClient(main.app) as client:
        return client.get(f"/api/watchlists/{wid}/etf-rows")


def test_the_etf_list_returns_every_member_in_added_order_with_the_stored_figures(engine):
    wid = _list(engine, "ETF", ["SPY", "QQQ", "IWM"])
    _etf_row(engine, "SPY", name="SPDR S&P 500", asset_class="Equity", expense_ratio=0.09, aum=8.1e11, holdings_count=505,
             last_price=769.64, pct_change_1d=0.74, avg_volume_30d=4.5e7, dividend_yield=0.99, beta=1.01, return_ytd=12.86,
             return_1y=15.01)
    _etf_row(engine, "QQQ", name="Invesco QQQ", asset_class="Equity", last_price=749.58)
    _etf_row(engine, "IWM", name="iShares Russell 2000", asset_class="Equity")
    _profile(engine, "SPY", "AMEX")

    response = _get(wid)

    assert response.status_code == 200
    rows = response.json()
    assert [r["ticker"] for r in rows] == ["SPY", "QQQ", "IWM"]
    assert set(rows[0]) == ROW_FIELDS
    assert rows[0] == {
        "ticker": "SPY", "name": "SPDR S&P 500", "exchange": "AMEX", "last_price": 769.64, "pct_change_1d": 0.74,
        "asset_class": "Equity", "expense_ratio": 0.09, "aum": 8.1e11, "holdings_count": 505, "avg_volume_30d": 4.5e7,
        "dividend_yield": 0.99, "beta": 1.01, "return_ytd": 12.86, "return_1y": 15.01,
    }
    assert rows[1]["exchange"] is None and rows[1]["last_price"] == 749.58  # no cached profile: a null exchange


def test_the_order_is_the_lists_added_order_not_alphabetical_or_insertion_order_of_the_rows(engine):
    wid = _list(engine, "ETF", ["ZZZ", "AAA", "MMM"])
    for ticker in ("MMM", "AAA", "ZZZ"):
        _etf_row(engine, ticker)
    assert [r["ticker"] for r in _get(wid).json()] == ["ZZZ", "AAA", "MMM"]
    with Session(engine) as session:  # the stock endpoint's order: list_watchlist_tickers (added_at)
        from data.watchlists import list_watchlist_tickers

        assert [t.ticker for t in list_watchlist_tickers(session, wid)] == ["ZZZ", "AAA", "MMM"]


def test_a_member_without_a_row_is_returned_with_nulls(engine):
    wid = _list(engine, "ETF", ["NEWETF"])
    rows = _get(wid).json()
    assert rows == [{field: (None if field != "ticker" else "NEWETF") for field in ROW_FIELDS}]


def test_an_empty_etf_list_returns_an_empty_list(engine):
    assert _get(_list(engine, "ETF")).json() == []


def test_a_non_etf_list_is_refused_with_a_400(engine):
    wid = _list(engine, "E1", ["AAPL"])
    response = _get(wid)
    assert response.status_code == 400
    assert response.json()["detail"] == 'Only the "ETF" watchlist has an ETF table.'


def test_a_look_alike_name_is_not_the_etf_list(engine):
    assert _get(_list(engine, "etf")).status_code == 400


def test_an_unknown_list_id_is_a_404_like_the_stock_endpoint(engine):
    response = _get(9999)
    with TestClient(main.app) as client:
        stock = client.get("/api/watchlists/9999/rows")
    assert response.status_code == stock.status_code == 404
    assert response.json()["detail"] == stock.json()["detail"] == "No watchlist with id 9999"


def test_beta_follows_the_contains_equity_rule(engine):
    wid = _list(engine, "ETF", ["CIBR", "SPY", "TLT", "GLD", "UNK"])
    _etf_row(engine, "CIBR", asset_class="Sector Equity", beta=1.04)
    _etf_row(engine, "SPY", asset_class="Equity", beta=1.01)
    _etf_row(engine, "TLT", asset_class="Fixed Income", beta=2.4)
    _etf_row(engine, "GLD", asset_class="Commodities", beta=0.45)
    _etf_row(engine, "UNK", asset_class=None, beta=1.0)
    assert {r["ticker"]: r["beta"] for r in _get(wid).json()} == {"CIBR": 1.04, "SPY": 1.01, "TLT": None, "GLD": None, "UNK": None}
    with Session(engine) as session:
        assert session.get(EtfScreenerRow, "TLT").beta == 2.4  # the stored value is untouched


def test_the_endpoint_makes_no_network_call_computes_no_score_and_writes_nothing(engine, monkeypatch):
    wid = _list(engine, "ETF", ["SPY", "NEWETF"])
    _etf_row(engine, "SPY", asset_class="Equity", beta=1.0)
    _profile(engine, "SPY", "AMEX")

    def refuse(*args, **kwargs):
        raise AssertionError("must not be called on the ETF rows path")

    async def refuse_async(*args, **kwargs):
        raise AssertionError("must not be called on the ETF rows path")

    monkeypatch.setattr(watchlist_data, "compute_ticker_score", refuse_async)
    monkeypatch.setattr(watchlist_data, "get_step1_data", refuse_async)
    monkeypatch.setattr(watchlist_data, "_consensus_rating", refuse_async)
    for name in ("get_profile", "get_quote", "get_etf_info", "get_grades_consensus", "get_historical_price_eod"):
        monkeypatch.setattr(fmp_client, name, refuse_async)
    monkeypatch.setattr(fmp_client, "get", refuse_async)

    tables = (EtfScreenerRow, TickerScore, TickerView, FundamentalsCache, WatchlistTicker, Watchlist)

    def snapshot():
        with Session(engine) as session:
            return {t.__name__: [r.model_dump() for r in session.exec(select(t)).all()] for t in tables}

    before = snapshot()
    response = _get(wid)

    assert response.status_code == 200 and [r["ticker"] for r in response.json()] == ["SPY", "NEWETF"]
    assert snapshot() == before  # not a single row added, changed or touched (no TickerScore, no view record, no cache row)


def test_the_stock_rows_endpoint_still_serves_the_etf_list_as_before(engine, monkeypatch):
    # GET /rows is untouched: it still returns the stock-shaped rows (here faked) for any list, ETF list included.
    wid = _list(engine, "ETF", ["SPY"])

    async def fake_rows(tickers):
        return []

    monkeypatch.setattr(main, "get_watchlist_rows", fake_rows)
    with TestClient(main.app) as client:
        assert client.get(f"/api/watchlists/{wid}/rows").status_code == 200
