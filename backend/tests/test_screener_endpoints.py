from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import core.main as main
from core.models import IndexConstituent, TickerScore, TickerView


def _fresh_engine(monkeypatch):
    # StaticPool: TestClient runs each request in a worker thread, and a
    # plain "sqlite://" in-memory DB is otherwise scoped per-connection --
    # without a shared pool, the tables created here wouldn't be visible to
    # the request thread's own connection.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def _file_engine(monkeypatch, tmp_path):
    """Like _fresh_engine, but a file database with a real pool, for the tests that run a worker on another thread beside the
    request (one shared in-memory connection is not safe to use from two threads at once)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'screener.db'}", connect_args={"check_same_thread": False, "timeout": 15})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(main, "engine", engine)
    return engine


def _mark_viewed(engine):
    """Marks every scored ticker added (and viewed): the way a ticker is in the Screener's `all` universe since the
    opt-in flip (a bare view only makes it browsed)."""
    with Session(engine) as session:
        for ticker in session.exec(select(TickerScore.ticker)).all():
            session.add(TickerView(ticker=ticker, last_viewed_at=datetime.now(), added_at=datetime.now(), added_source="user"))
        session.commit()


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
        session.add(IndexConstituent(index_name="nasdaq", ticker="ADBE", company_name="Adobe", last_synced_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="AAPL", company_name="Apple Inc.", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="MMM", company_name="3M Co.", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="ADBE", company_name="Adobe Inc.", computed_at=datetime(2026, 1, 1)))
        session.commit()

    with TestClient(main.app) as client:
        default_response = client.get("/api/screener")
        sp500_response = client.get("/api/screener", params={"universe": "sp500"})
        dow_response = client.get("/api/screener", params={"universe": "dow"})
        nasdaq_response = client.get("/api/screener", params={"universe": "nasdaq"})
        invalid_response = client.get("/api/screener", params={"universe": "qqq"})

    assert {row["ticker"] for row in default_response.json()} == {"AAPL"}  # defaults to sp500
    assert {row["ticker"] for row in sp500_response.json()} == {"AAPL"}
    assert {row["ticker"] for row in dow_response.json()} == {"MMM"}
    assert {row["ticker"] for row in nasdaq_response.json()} == {"ADBE"}
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

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        response = client.get("/api/screener", params={"universe": "all"})

    assert response.status_code == 200
    assert {row["ticker"] for row in response.json()} == {"AAPL", "ARM"}


def _run_worker_in_a_thread(monkeypatch, engine, compute, tickers):
    """Stands in for the worker subprocess: runs the real job body (pipeline.score_recompute_job.run_job) on a thread, against the
    test database, the way the subprocess would run it against the real one."""
    import asyncio
    import threading

    import data.score_recompute as score_recompute
    import pipeline.score_recompute_job as job

    for module in (score_recompute, job):
        monkeypatch.setattr(module, "engine", engine)

    def launch(run_id, requested):
        threading.Thread(target=lambda: asyncio.run(job.run_job(run_id, tickers, compute=compute)), daemon=True).start()

    monkeypatch.setattr(score_recompute, "launcher", launch)


def test_screener_recompute_runs_the_background_job_and_returns_its_summary(monkeypatch, tmp_path):
    engine = _file_engine(monkeypatch, tmp_path)

    async def compute(ticker, cache_only=False, **kwargs):
        assert cache_only is True  # never a live FMP fetch
        if ticker in ("BRK.B", "BF.B"):
            raise RuntimeError("402")
        return object()

    _run_worker_in_a_thread(monkeypatch, engine, compute, ["AAPL", "BRK.B", "BF.B"])

    with TestClient(main.app) as client:
        response = client.post("/api/screener/recompute")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 3  # the same shape as before: processed, failed, duration_seconds, failures
    assert body["failed"] == 2
    assert body["failures"] == [["BRK.B", "402"], ["BF.B", "402"]]
    assert set(body) == {"processed", "failed", "duration_seconds", "failures"}


def test_screener_recompute_is_a_409_while_another_run_is_in_progress(monkeypatch, recompute_launches, tmp_path):
    _file_engine(monkeypatch, tmp_path)
    import data.score_recompute as score_recompute

    score_recompute.claim_run("weights", main.engine)  # a run is in progress (its worker never reports back here)

    with TestClient(main.app) as client:
        response = client.post("/api/screener/recompute")

    assert response.status_code == 409
    assert "already running" in response.json()["detail"]
    assert recompute_launches == []  # not queued, not started


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

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        response = client.get("/api/screener/meta", params={"universe": "all"})

    assert response.json() == {"universe": "all", "total_constituents": 2}


def test_screener_meta_universe_all_excludes_etfs_to_match_the_pages_client_side_drop(monkeypatch):
    # The Screener page drops ETFs client-side (screenerFilters.ts::
    # excludeEtfs), so its "X of Y" total must not count them either --
    # otherwise an ETF reads as a permanently unscored ticker. Same rule as
    # the frontend's: is_etf wins when set; a row with no is_etf yet
    # (pre-recompute) falls back to company_type == "ETF".
    engine = _fresh_engine(monkeypatch)
    at = datetime(2026, 1, 1)
    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", is_etf=False, company_type="Standard", computed_at=at))
        session.add(TickerScore(ticker="QQQ", is_etf=True, company_type="ETF", computed_at=at))
        session.add(TickerScore(ticker="SPY", is_etf=None, company_type="ETF", computed_at=at))  # legacy ETF row
        session.add(TickerScore(ticker="MSFT", is_etf=None, company_type="Standard", computed_at=at))  # legacy stock row
        session.add(TickerScore(ticker="NOTYPE", is_etf=None, company_type=None, computed_at=at))  # legacy, unclassified
        session.commit()

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        response = client.get("/api/screener/meta", params={"universe": "all"})

    assert response.json() == {"universe": "all", "total_constituents": 3}


def test_screener_all_universe_no_longer_returns_etf_rows_after_the_cutover(monkeypatch):
    # ETF cutover 2026-10-03: the ETFs have their own universe and page (/api/etf-screener), so the stock universe the
    # `all` Screener reads holds none; an ETF's old TickerScore row stays in the table, frozen, and is simply not served.
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(TickerScore(ticker="SPY", is_etf=True, company_type="ETF", computed_at=datetime(2026, 1, 1)))
        session.add(TickerScore(ticker="AAPL", is_etf=False, computed_at=datetime(2026, 1, 1)))
        session.commit()

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        response = client.get("/api/screener", params={"universe": "all"})
        meta = client.get("/api/screener/meta", params={"universe": "all"})

    assert [(row["ticker"], row["is_etf"]) for row in response.json()] == [("AAPL", False)]
    assert meta.json()["total_constituents"] == 1
    with Session(engine) as session:
        assert session.get(TickerScore, "SPY") is not None  # not deleted


def test_browsed_and_expired_stocks_are_not_in_the_all_universe_and_there_is_no_hidden_count(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    old = datetime.now() - timedelta(days=90)
    with Session(engine) as session:
        for ticker in ("BROWSED", "OLDSTOCK", "ADDEDOLD", "NEWSTOCK"):
            session.add(TickerScore(ticker=ticker, is_etf=False, computed_at=old))
        session.add(TickerScore(ticker="OLDETF", is_etf=True, company_type="ETF", computed_at=old))
        session.add(TickerView(ticker="BROWSED", last_viewed_at=datetime.now()))  # opened, not added
        session.add(TickerView(ticker="OLDSTOCK", last_viewed_at=old))  # expired
        session.add(TickerView(ticker="OLDETF", last_viewed_at=old))
        session.add(TickerView(ticker="ADDEDOLD", last_viewed_at=old, added_at=old, added_source="user"))  # added: never expires
        session.add(TickerView(ticker="NEWSTOCK", last_viewed_at=datetime.now(), added_at=datetime.now(), added_source="user"))
        session.commit()

    with TestClient(main.app) as client:
        meta = client.get("/api/screener/meta", params={"universe": "all"}).json()
        listed = sorted(row["ticker"] for row in client.get("/api/screener", params={"universe": "all"}).json())
    assert listed == ["ADDEDOLD", "NEWSTOCK"]
    assert meta == {"universe": "all", "total_constituents": 2}  # no hidden_inactive since the opt-in flip


def test_screener_meta_is_zero_when_no_constituents_stored(monkeypatch):
    _fresh_engine(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/screener/meta")

    assert response.json() == {"universe": "sp500", "total_constituents": 0}


def test_screener_recompute_never_runs_scoring_in_the_request(monkeypatch, recompute_launches, tmp_path):
    """Regression guard for the old freeze: the request only claims the run and starts the worker; no step or score function
    runs in the API process (the old endpoint ran ~40 s of scoring inline on the event loop)."""
    import asyncio

    import data.score_recompute as score_recompute

    _file_engine(monkeypatch, tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("scoring must not run inside the request")

    import data.ticker_score as ticker_score
    from pipeline import recompute_ticker_scores

    monkeypatch.setattr(ticker_score, "compute_ticker_score", fail_if_called)
    monkeypatch.setattr(recompute_ticker_scores, "recompute_all", fail_if_called)
    monkeypatch.setattr(recompute_ticker_scores, "main", fail_if_called)

    async def finish_the_run_when_started():
        # The worker would end the run; here the status row is closed after the launch so the awaiting request can return.
        while not recompute_launches:
            await asyncio.sleep(0.01)
        score_recompute.fail_run(recompute_launches[0][0], "test: ended", main.engine)

    with TestClient(main.app) as client:
        import threading

        threading.Thread(target=lambda: asyncio.run(finish_the_run_when_started()), daemon=True).start()
        response = client.post("/api/screener/recompute")

    assert len(recompute_launches) == 1
    assert response.status_code == 500 and "test: ended" in response.json()["detail"]  # a failed run is reported, not hidden


# --- delisted exclusion: every universe and the meta count -------------------------------------
# All timestamps are relative to now, never hard-coded.

_UNIVERSES = ("sp500", "dow", "nasdaq")


def _seed_delisted_and_live(engine, *, index_names=_UNIVERSES):
    """One live and one delisted-flagged ticker per index universe, plus a live and a delisted
    ticker that are in no index (only visible under universe=all)."""
    now = datetime.now()
    with Session(engine) as session:
        for index_name in index_names:
            for ticker, flagged in ((f"LIVE_{index_name}", False), (f"GONE_{index_name}", True)):
                session.add(IndexConstituent(index_name=index_name, ticker=ticker, company_name=ticker, last_synced_at=now))
                session.add(
                    TickerScore(
                        ticker=ticker,
                        company_name=ticker,
                        is_etf=False,
                        computed_at=now,
                        delisted_at=now - timedelta(days=5) if flagged else None,
                    )
                )
        session.add(TickerScore(ticker="LIVE_OFFINDEX", company_name="x", is_etf=False, computed_at=now))
        session.add(
            TickerScore(ticker="GONE_OFFINDEX", company_name="x", is_etf=False, computed_at=now, delisted_at=now - timedelta(days=5))
        )
        session.commit()


def test_screener_list_excludes_a_delisted_ticker_from_every_universe(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_delisted_and_live(engine)

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        for universe in _UNIVERSES:
            tickers = {row["ticker"] for row in client.get("/api/screener", params={"universe": universe}).json()}
            assert tickers == {f"LIVE_{universe}"}, universe
        all_tickers = {row["ticker"] for row in client.get("/api/screener", params={"universe": "all"}).json()}

    assert all_tickers == {"LIVE_sp500", "LIVE_dow", "LIVE_nasdaq", "LIVE_OFFINDEX"}
    assert not any(t.startswith("GONE_") for t in all_tickers)


def test_screener_list_does_not_expose_the_delisted_flag(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_delisted_and_live(engine)

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        rows = client.get("/api/screener", params={"universe": "all"}).json()

    assert rows and all("delisted_at" not in row for row in rows)


def test_screener_meta_excludes_a_delisted_ticker_from_every_universe_count(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_delisted_and_live(engine)

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        for universe in _UNIVERSES:
            assert client.get("/api/screener/meta", params={"universe": universe}).json() == {
                "universe": universe,
                "total_constituents": 1,
            }
        all_response = client.get("/api/screener/meta", params={"universe": "all"})

    assert all_response.json() == {"universe": "all", "total_constituents": 4}


def test_screener_meta_index_count_still_counts_a_constituent_with_no_ticker_score_row(monkeypatch):
    # The "X of Y" gap for an unscored constituent must survive the delisted exclusion: only a
    # constituent whose TickerScore row is FLAGGED drops out of Y.
    engine = _fresh_engine(monkeypatch)
    now = datetime.now()
    with Session(engine) as session:
        for ticker in ("SCORED", "UNSCORED", "FLAGGED"):
            session.add(IndexConstituent(index_name="sp500", ticker=ticker, company_name=ticker, last_synced_at=now))
        session.add(TickerScore(ticker="SCORED", company_name="s", computed_at=now))
        session.add(TickerScore(ticker="FLAGGED", company_name="f", computed_at=now, delisted_at=now))
        session.commit()

    with TestClient(main.app) as client:
        response = client.get("/api/screener/meta", params={"universe": "sp500"})

    assert response.json() == {"universe": "sp500", "total_constituents": 2}


def test_screener_list_returns_a_null_pe_ratio_as_null(monkeypatch):
    # A NULL trailing P/E (EPS <= 0, or an ADR with no usable FMP ratio) must reach the client as
    # null, not 0 -- the page's range filter excludes null when a P/E range is active.
    engine = _fresh_engine(monkeypatch)
    now = datetime.now()
    with Session(engine) as session:
        session.add(TickerScore(ticker="PROFIT", company_name="p", is_etf=False, pe_ratio=18.5, computed_at=now))
        session.add(TickerScore(ticker="LOSS", company_name="l", is_etf=False, pe_ratio=None, computed_at=now))
        session.commit()

    _mark_viewed(engine)
    with TestClient(main.app) as client:
        rows = {row["ticker"]: row for row in client.get("/api/screener", params={"universe": "all"}).json()}

    assert rows["PROFIT"]["pe_ratio"] == 18.5
    assert rows["LOSS"]["pe_ratio"] is None
