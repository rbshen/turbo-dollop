"""The "ETF" watchlist is ETF-only and permanent (docs/decisions.md, 2026-10-04): a ticker may join it only if it is a
KNOWN ETF (cached profile / score row says ETF, or an EtfScreenerRow exists), the list can't be renamed or deleted, and
no other list can take its name. Every test builds its own in-memory engine and patches it onto the module under test."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
from core.models import EtfScreenerRow, FundamentalsCache, TickerScore, Watchlist, WatchlistTicker
from data.watchlists import (
    ETF_WATCHLIST_NAME,
    etf_only_message,
    is_reserved_etf_list_name,
    tickers_not_allowed_on_watchlist,
)

NOW = datetime(2026, 1, 1)


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def _profile(session, ticker, **flags):
    session.add(
        FundamentalsCache(
            ticker=ticker, statement_type="profile", period="latest", fetched_at=NOW,
            raw_json=json.dumps([{"symbol": ticker, **flags}]),
        )
    )


@pytest.fixture
def engine(monkeypatch):
    """Patched onto main. Known ETFs: QQQ and SMH (cached profile), SPY (score row), IWM (EtfScreenerRow only).
    Known stock: AAPL. NEVERSEEN is in no table. The immediate EtfScreenerRow write after an ETF add would call
    FMP, so it is stubbed (test_universe_api covers it)."""
    eng = _engine()
    monkeypatch.setattr(main, "engine", eng)

    async def no_row_write(tickers, max_rows=5):
        return []

    monkeypatch.setattr(main, "ensure_etf_screener_rows", no_row_write)
    with Session(eng) as session:
        _profile(session, "QQQ", isEtf=True, isFund=False)
        _profile(session, "SMH", isEtf=True, isFund=False)
        _profile(session, "AAPL", isEtf=False, isFund=False)
        session.add(TickerScore(ticker="SPY", is_etf=True, computed_at=NOW))
        session.add(EtfScreenerRow(ticker="IWM"))
        session.commit()
    return eng


def _make_list(engine, name, tickers=()):
    with Session(engine) as session:
        watchlist = Watchlist(name=name, created_at=NOW, updated_at=NOW)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for ticker in tickers:
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=ticker, added_at=NOW))
        session.commit()
        return watchlist.id


def _members(engine, watchlist_id):
    with Session(engine) as session:
        return sorted(t.ticker for t in session.exec(select(WatchlistTicker).where(WatchlistTicker.watchlist_id == watchlist_id)).all())


def _names(engine):
    with Session(engine) as session:
        return sorted(w.name for w in session.exec(select(Watchlist)).all())


STOCK_MSG = 'AAPL is not an ETF. The "ETF" watchlist holds ETFs only.'


# --- the helper ----------------------------------------------------------------------------------------------------


def test_helper_allows_everything_on_any_list_but_the_etf_list(engine):
    with Session(engine) as session:
        assert tickers_not_allowed_on_watchlist(session, "E1", ["AAPL", "NEVERSEEN"]) == []
        assert tickers_not_allowed_on_watchlist(session, "etf", ["AAPL"]) == []  # only the exact name is the ETF list


def test_helper_accepts_every_kind_of_known_etf_and_refuses_the_rest_in_first_seen_order(engine):
    with Session(engine) as session:
        assert tickers_not_allowed_on_watchlist(session, ETF_WATCHLIST_NAME, ["qqq", "SPY", "IWM", "smh"]) == []
        assert tickers_not_allowed_on_watchlist(session, ETF_WATCHLIST_NAME, ["NEVERSEEN", "qqq", "aapl", "NEVERSEEN"]) == [
            "NEVERSEEN",
            "AAPL",
        ]
        assert tickers_not_allowed_on_watchlist(session, ETF_WATCHLIST_NAME, []) == []


def test_helper_normalizes_dot_notation(engine):
    with Session(engine) as session:
        assert tickers_not_allowed_on_watchlist(session, ETF_WATCHLIST_NAME, ["brk.b"]) == ["BRK-B"]


def test_the_message_names_one_or_all_offenders():
    assert etf_only_message(["XYZ"]) == 'XYZ is not an ETF. The "ETF" watchlist holds ETFs only.'
    assert etf_only_message(["XYZ", "ABC"]) == 'XYZ, ABC are not ETFs. The "ETF" watchlist holds ETFs only.'


@pytest.mark.parametrize("name", ["etf", "Etf", " ETF ", "eTf"])
def test_reserved_variants(name):
    assert is_reserved_etf_list_name(name)


@pytest.mark.parametrize("name", ["ETF", "ETFs", "E1", "My ETF", "ET"])
def test_not_reserved_variants(name):
    assert not is_reserved_etf_list_name(name)


# --- POST /api/watchlists/{id}/tickers -------------------------------------------------------------------------------


def test_single_add_of_a_known_etf_to_the_etf_list_succeeds(engine):
    wid = _make_list(engine, "ETF")
    with TestClient(main.app) as client:
        for ticker in ("QQQ", "spy", "IWM"):
            assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": ticker}).status_code == 201
    assert _members(engine, wid) == ["IWM", "QQQ", "SPY"]


def test_single_add_of_a_stock_to_the_etf_list_is_rejected(engine):
    wid = _make_list(engine, "ETF")
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "aapl"})
    assert response.status_code == 400 and response.json()["detail"] == STOCK_MSG
    assert _members(engine, wid) == []


def test_single_add_of_a_never_seen_ticker_to_the_etf_list_is_rejected(engine):
    wid = _make_list(engine, "ETF")
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "NEVERSEEN"})
    assert response.status_code == 400
    assert response.json()["detail"] == 'NEVERSEEN is not an ETF. The "ETF" watchlist holds ETFs only.'
    assert _members(engine, wid) == []


def test_single_add_to_any_other_list_still_takes_stocks_and_unknown_tickers(engine):
    wid = _make_list(engine, "E1")
    with TestClient(main.app) as client:
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "AAPL"}).status_code == 201
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "NEVERSEEN"}).status_code == 201
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "QQQ"}).status_code == 201  # an ETF too
    assert _members(engine, wid) == ["AAPL", "NEVERSEEN", "QQQ"]


# --- POST /api/watchlists/{id}/tickers/bulk -------------------------------------------------------------------------


def test_bulk_add_of_only_etfs_to_the_etf_list_succeeds(engine):
    wid = _make_list(engine, "ETF")
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": ["QQQ", "SPY", "IWM"]})
    assert response.status_code == 200 and response.json() == {"added": 3, "already_present": 0}
    assert _members(engine, wid) == ["IWM", "QQQ", "SPY"]


def test_bulk_add_with_any_non_etf_is_rejected_whole_and_names_every_offender(engine):
    wid = _make_list(engine, "ETF", tickers=["SMH"])
    with TestClient(main.app) as client:
        response = client.post(
            f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": ["QQQ", "AAPL", "SPY", "NEVERSEEN", "aapl"]}
        )
    assert response.status_code == 400
    assert response.json()["detail"] == 'AAPL, NEVERSEEN are not ETFs. The "ETF" watchlist holds ETFs only.'
    assert _members(engine, wid) == ["SMH"]  # all or nothing: not even QQQ / SPY went in


def test_bulk_add_to_any_other_list_is_unchanged(engine):
    wid = _make_list(engine, "Growth")
    with TestClient(main.app) as client:
        response = client.post(f"/api/watchlists/{wid}/tickers/bulk", json={"tickers": ["AAPL", "QQQ", "NEVERSEEN"]})
    assert response.status_code == 200 and response.json()["added"] == 3


# --- POST /api/tickers/{t}/etf-watchlist ---------------------------------------------------------------------------


def test_etf_page_endpoint_creates_the_list_when_missing_for_a_known_etf(engine):
    assert _names(engine) == []
    with TestClient(main.app) as client:
        response = client.post("/api/tickers/iwm/etf-watchlist")  # known only through its EtfScreenerRow
    assert response.status_code == 200 and response.json()["added"] is True and response.json()["watchlist_name"] == "ETF"
    assert _names(engine) == ["ETF"]


def test_etf_page_endpoint_refuses_a_stock_and_does_not_create_an_empty_list(engine):
    with TestClient(main.app) as client:
        stock = client.post("/api/tickers/AAPL/etf-watchlist")
        unknown = client.post("/api/tickers/NEVERSEEN/etf-watchlist")
    assert stock.status_code == 400 and stock.json()["detail"] == STOCK_MSG
    assert unknown.status_code == 400
    assert _names(engine) == []


def test_etf_page_endpoint_refuses_a_stock_on_an_existing_list_too(engine):
    wid = _make_list(engine, "ETF", tickers=["QQQ"])
    with TestClient(main.app) as client:
        assert client.post("/api/tickers/AAPL/etf-watchlist").status_code == 400
    assert _members(engine, wid) == ["QQQ"]


def test_etf_page_endpoint_stays_idempotent_for_a_member(engine):
    wid = _make_list(engine, "ETF", tickers=["LEGACY"])  # a member that is no longer recognised stays a no-op
    with TestClient(main.app) as client:
        response = client.post("/api/tickers/LEGACY/etf-watchlist")
    assert response.status_code == 200 and response.json()["added"] is False
    assert _members(engine, wid) == ["LEGACY"]


# --- rename ---------------------------------------------------------------------------------------------------------


def test_the_etf_list_cannot_be_renamed(engine):
    wid = _make_list(engine, "ETF", tickers=["QQQ"])
    with TestClient(main.app) as client:
        response = client.put(f"/api/watchlists/{wid}", json={"name": "Funds"})
    assert response.status_code == 400 and response.json()["detail"] == 'The "ETF" watchlist can\'t be renamed.'
    assert _names(engine) == ["ETF"]


def test_the_etf_list_still_accepts_an_unchanged_name_and_sort_preferences(engine):
    wid = _make_list(engine, "ETF")
    with TestClient(main.app) as client:
        assert client.put(f"/api/watchlists/{wid}", json={"name": "ETF"}).status_code == 200
        assert client.put(f"/api/watchlists/{wid}", json={"sort_field": "ticker", "sort_direction": "asc"}).status_code == 200


@pytest.mark.parametrize("name", ["ETF", "etf", "Etf", "  etf  "])
def test_no_other_list_can_be_renamed_to_etf_in_any_spelling(engine, name):
    wid = _make_list(engine, "Growth")
    with TestClient(main.app) as client:
        response = client.put(f"/api/watchlists/{wid}", json={"name": name})
    assert response.status_code == 400
    assert "reserved for the ETF-only" in response.json()["detail"]
    assert _names(engine) == ["Growth"]


def test_renaming_to_etf_is_refused_even_when_the_etf_list_exists(engine):
    _make_list(engine, "ETF")
    wid = _make_list(engine, "Growth")
    with TestClient(main.app) as client:
        assert client.put(f"/api/watchlists/{wid}", json={"name": "ETF"}).status_code == 400  # was 409 before


def test_an_ordinary_rename_and_a_rename_away_from_a_variant_still_work(engine):
    plain = _make_list(engine, "Old")
    variant = _make_list(engine, "etf")  # a pre-existing list with a variant spelling can leave it
    with TestClient(main.app) as client:
        assert client.put(f"/api/watchlists/{plain}", json={"name": "New"}).status_code == 200
        assert client.put(f"/api/watchlists/{variant}", json={"name": "Funds"}).status_code == 200


# --- create ---------------------------------------------------------------------------------------------------------


def test_creating_a_second_etf_list_is_still_a_409_duplicate(engine):
    _make_list(engine, "ETF")
    with TestClient(main.app) as client:
        response = client.post("/api/watchlists", json={"name": "ETF"})
    assert response.status_code == 409
    assert _names(engine) == ["ETF"]


def test_creating_a_variant_of_the_etf_name_is_refused(engine):
    with TestClient(main.app) as client:
        for name in ("etf", "Etf"):
            response = client.post("/api/watchlists", json={"name": name})
            assert response.status_code == 400 and "reserved for the ETF-only" in response.json()["detail"]
    assert _names(engine) == []


def test_creating_the_etf_list_when_it_does_not_exist_is_allowed_and_is_guarded_like_any_etf_list(engine):
    with TestClient(main.app) as client:
        created = client.post("/api/watchlists", json={"name": "ETF"})
        assert created.status_code == 201
        wid = created.json()["id"]
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "AAPL"}).status_code == 400
        assert client.post(f"/api/watchlists/{wid}/tickers", json={"ticker": "QQQ"}).status_code == 201


# --- delete ---------------------------------------------------------------------------------------------------------


def test_the_etf_list_cannot_be_deleted(engine):
    wid = _make_list(engine, "ETF", tickers=["QQQ", "SPY"])
    with TestClient(main.app) as client:
        response = client.delete(f"/api/watchlists/{wid}")
    assert response.status_code == 400 and response.json()["detail"] == 'The "ETF" watchlist can\'t be deleted.'
    assert _names(engine) == ["ETF"] and _members(engine, wid) == ["QQQ", "SPY"]


def test_other_lists_can_still_be_deleted_and_a_missing_one_is_a_404(engine):
    wid = _make_list(engine, "Growth", tickers=["AAPL"])
    with TestClient(main.app) as client:
        assert client.delete(f"/api/watchlists/{wid}").status_code == 204
        assert client.delete("/api/watchlists/9999").status_code == 404
    assert _names(engine) == []
