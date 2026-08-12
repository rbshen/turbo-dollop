import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_score_recompute as nightly_recompute
import pipeline.recompute_ticker_scores as recompute
from core.models import FundamentalsCache, IndexConstituent, TickerScore, Watchlist, WatchlistTicker


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    # Both modules' own `engine` reference need patching: this module's
    # load_full_tracked_universe reads via nightly_recompute.engine, while
    # the actual per-ticker work runs through recompute_all() -- reused
    # as-is from recompute_ticker_scores.py -- which never touches `engine`
    # itself as long as main() always passes it an explicit ticker list
    # (see nightly_score_recompute.main()), so only compute_ticker_score
    # needs patching there, not its engine.
    monkeypatch.setattr(nightly_recompute, "engine", engine)
    monkeypatch.setattr(nightly_recompute, "LOG_PATH", tmp_path / "test_nightly_score_recompute.log")
    return engine


def _patch_compute(monkeypatch, calls, fail_for: set[str] | None = None, skip_for: set[str] | None = None):
    fail_for = fail_for or set()
    skip_for = skip_for or set()

    async def fake_compute(ticker, cache_only=False):
        calls.append((ticker, cache_only))
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure recomputing {ticker}")
        if ticker in skip_for:
            return None
        return TickerScore(ticker=ticker, overall_score=80, overall_verdict="Pass", computed_at=datetime.now())

    monkeypatch.setattr(recompute, "compute_ticker_score", fake_compute)


def test_load_full_tracked_universe_unions_index_cache_and_score_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        # AAPL: index member only.
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        # IREN: cached FMP data but never an index member and no TickerScore
        # row yet -- exactly the IREN/SEZL/POOL shape this job exists for.
        session.add(FundamentalsCache(ticker="IREN", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        # SEZL: has a TickerScore row but (hypothetically) no remaining cache
        # rows -- still must be swept.
        session.add(TickerScore(ticker="SEZL", overall_score=66, overall_verdict="Fail", computed_at=datetime.now()))
        # MSFT: appears in two of the three sources -- must not be double-counted.
        session.add(IndexConstituent(index_name="sp500", ticker="MSFT", company_name="Microsoft", last_synced_at=datetime.now()))
        session.add(FundamentalsCache(ticker="MSFT", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        session.commit()

        # ASML: watchlisted only -- not indexed, not cached, not scored. This
        # module reuses nightly_fundamentals_fetch.py::load_full_tracked_universe
        # rather than keeping its own copy; this proves that reuse actually
        # picks up the Watchlist union, not just index/cache/score.
        watchlist = Watchlist(name="Semis", created_at=datetime.now(), updated_at=datetime.now())
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker="ASML", added_at=datetime.now()))
        session.commit()

    with Session(engine) as session:
        tickers = nightly_recompute.load_full_tracked_universe(session)

    assert tickers == ["AAPL", "ASML", "IREN", "MSFT", "SEZL"]


def test_main_sweeps_the_full_tracked_universe_when_no_tickers_passed(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="IREN", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        session.add(TickerScore(ticker="SEZL", overall_score=66, overall_verdict="Fail", computed_at=datetime.now()))
        session.commit()
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls)

    summary = asyncio.run(nightly_recompute.main(tickers=None))

    assert {c[0] for c in calls} == {"IREN", "SEZL"}
    assert all(cache_only is True for _, cache_only in calls)
    assert summary["processed"] == 2
    assert summary["failed"] == 0


def test_main_uses_explicit_ticker_list_when_passed(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls)

    summary = asyncio.run(nightly_recompute.main(tickers=["AAPL", "MSFT"]))

    assert {c[0] for c in calls} == {"AAPL", "MSFT"}
    assert summary["processed"] == 2


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls, fail_for={"BADCO"})

    summary = asyncio.run(nightly_recompute.main(tickers=["AAPL", "BADCO", "MSFT"]))

    assert {c[0] for c in calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure recomputing BADCO")]
