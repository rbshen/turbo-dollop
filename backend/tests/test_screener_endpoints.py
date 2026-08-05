from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import core.main as main
from core.models import IndexConstituent, TickerScore


def _fresh_engine(monkeypatch):
    # StaticPool: TestClient runs each request in a worker thread, and a
    # plain "sqlite://" in-memory DB is otherwise scoped per-connection --
    # without a shared pool, the tables created here wouldn't be visible to
    # the request thread's own connection.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def test_screener_list_returns_stored_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 1, 1)))
        session.add(
            TickerScore(
                ticker="AAPL",
                company_name="Apple Inc.",
                sector="Technology",
                company_type="Standard",
                step1_score=90,
                step1_verdict="Strong Pass",
                overall_score=85,
                overall_verdict="Pass",
                market_cap=3_000_000_000_000.0,
                pe_ratio=30.0,
                beta=1.2,
                computed_at=datetime(2026, 1, 1),
            )
        )
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/screener")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"
    assert body[0]["company_name"] == "Apple Inc."
    assert body[0]["overall_score"] == 85
    assert body[0]["market_cap"] == 3_000_000_000_000.0


def test_screener_list_excludes_a_ticker_score_row_outside_the_sp500_list(monkeypatch):
    # A ticker can get a TickerScore row just from being viewed individually
    # (compute_ticker_score's other call sites) without ever being an S&P
    # 500 constituent -- that must not leak into the "S&P 500 tickers" list.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="ARM", company_name="Arm Holdings", computed_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/screener")

    assert response.status_code == 200
    tickers = {row["ticker"] for row in response.json()}
    assert tickers == {"AAPL"}


def test_screener_list_is_empty_when_no_rows_exist(monkeypatch):
    _fresh_engine(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/screener")

    assert response.status_code == 200
    assert response.json() == []


def test_screener_list_filters_by_universe_query_param(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 1, 1)))
        session.add(IndexConstituent(index_name="dow", ticker="MMM", company_name="3M", last_synced_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="MMM", company_name="3M Co.", computed_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        default_response = client.get("/api/screener")
        sp500_response = client.get("/api/screener", params={"universe": "sp500"})
        dow_response = client.get("/api/screener", params={"universe": "dow"})
        invalid_response = client.get("/api/screener", params={"universe": "qqq"})

    assert {row["ticker"] for row in default_response.json()} == {"AAPL"}  # defaults to sp500
    assert {row["ticker"] for row in sp500_response.json()} == {"AAPL"}
    assert {row["ticker"] for row in dow_response.json()} == {"MMM"}
    assert invalid_response.status_code == 422


def test_screener_list_universe_all_returns_every_cached_ticker_regardless_of_index(monkeypatch):
    # universe="all" is the deliberate escape hatch past index membership --
    # a ticker only ever viewed individually (never an S&P 500 or Dow
    # constituent) must still show up here, unlike the sp500/dow filters.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="ARM", company_name="Arm Holdings", computed_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/screener", params={"universe": "all"})

    assert response.status_code == 200
    assert {row["ticker"] for row in response.json()} == {"AAPL", "ARM"}


def test_screener_recompute_calls_recompute_all_and_returns_its_summary(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_recompute_all(tickers=None):
        assert tickers is None  # the endpoint always recomputes the full stored list
        return {"processed": 503, "failed": 2, "duration_seconds": 12.3, "failures": [("BRK.B", "402"), ("BF.B", "402")]}

    monkeypatch.setattr(main, "recompute_all", fake_recompute_all)

    with TestClient(main.app) as client:
        response = client.post("/api/screener/recompute")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 503
    assert body["failed"] == 2
    assert body["failures"] == [["BRK.B", "402"], ["BF.B", "402"]]


def test_screener_meta_returns_the_total_constituent_count_for_the_selected_universe(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 1, 1)))
        session.add(IndexConstituent(index_name="sp500", ticker="MSFT", company_name="Microsoft", last_synced_at=datetime(2026, 1, 1)))
        session.add(IndexConstituent(index_name="dow", ticker="MMM", company_name="3M", last_synced_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        default_response = client.get("/api/screener/meta")
        dow_response = client.get("/api/screener/meta", params={"universe": "dow"})

    assert default_response.status_code == 200
    assert default_response.json() == {"universe": "sp500", "total_constituents": 2}
    assert dow_response.json() == {"universe": "dow", "total_constituents": 1}


def test_screener_meta_universe_all_counts_every_ticker_score_row(monkeypatch):
    # Unlike sp500/dow, "all" has no separate constituent list to compare
    # against -- total_constituents is just how many TickerScore rows exist,
    # index membership aside.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="ARM", company_name="Arm Holdings", computed_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/screener/meta", params={"universe": "all"})

    assert response.json() == {"universe": "all", "total_constituents": 2}


def test_screener_meta_is_zero_when_no_constituents_stored(monkeypatch):
    _fresh_engine(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/screener/meta")

    assert response.json() == {"universe": "sp500", "total_constituents": 0}


def test_screener_recompute_never_calls_the_script_entry_point(monkeypatch):
    """Regression guard: the endpoint must call recompute_all() directly,
    not recompute_ticker_scores.main() (which also reconfigures logging and
    calls init_db() -- see recompute_ticker_scores.py's docstring)."""
    _fresh_engine(monkeypatch)
    calls = []

    async def fake_recompute_all(tickers=None):
        calls.append(tickers)
        return {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("the endpoint must not call recompute_ticker_scores.main()")

    monkeypatch.setattr(main, "recompute_all", fake_recompute_all)
    from pipeline import recompute_ticker_scores

    monkeypatch.setattr(recompute_ticker_scores, "main", fail_if_called)

    with TestClient(main.app) as client:
        response = client.post("/api/screener/recompute")

    assert response.status_code == 200
    assert calls == [None]
