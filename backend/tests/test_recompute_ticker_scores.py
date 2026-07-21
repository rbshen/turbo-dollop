import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

import recompute_ticker_scores as recompute
from models import IndexConstituent, TickerScore


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(recompute, "engine", engine)
    # Same reasoning as test_nightly_fundamentals_fetch.py: configure_logging's
    # force=True reconfigures the ROOT logger for the rest of the pytest
    # process -- point it at a tmp_path file so tests don't pollute the real
    # backend/logs/recompute_ticker_scores.log.
    monkeypatch.setattr(recompute, "LOG_PATH", tmp_path / "test_recompute.log")
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


def test_load_sp500_tickers_reused_from_nightly_script(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="other-index", ticker="XYZ", company_name="Not S&P", last_synced_at=datetime.now()))
        session.commit()
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls)

    asyncio.run(recompute.main(tickers=None))

    assert {c[0] for c in calls} == {"AAPL"}


def test_every_call_uses_cache_only_true(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls)

    asyncio.run(recompute.main(tickers=["AAPL", "MSFT"]))

    assert len(calls) == 2
    assert all(cache_only is True for _, cache_only in calls)


def test_a_failing_ticker_does_not_abort_the_run(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls, fail_for={"BADCO"})

    summary = asyncio.run(recompute.main(tickers=["AAPL", "BADCO", "MSFT"]))

    assert {c[0] for c in calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["processed"] == 3
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure recomputing BADCO")]


def test_a_ticker_with_no_cached_data_is_skipped_not_a_failure(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls, skip_for={"NEWCO"})

    summary = asyncio.run(recompute.main(tickers=["AAPL", "NEWCO"]))

    assert summary["failed"] == 0  # a None result (no cached profile) isn't a failure
    assert summary["failures"] == []


def test_summary_reports_the_expected_fields(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls)

    summary = asyncio.run(recompute.main(tickers=["AAPL"]))

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["failures"] == []
    assert "duration_seconds" in summary
    # No FMP calls are made by this script at all -- there's deliberately no
    # calls_made field to track, unlike the nightly fetch's summary.
    assert "calls_made" not in summary


def test_empty_ticker_list_is_handled_without_crashing(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(recompute.main(tickers=[]))

    assert summary == {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}


def test_recompute_all_never_touches_logging_config_or_init_db(monkeypatch, tmp_path):
    """recompute_all() (used directly by the API endpoint) must never call
    configure_logging() or init_db() -- doing so from inside the already-
    running FastAPI app would hijack its root-logger configuration on every
    request. Only main() (the standalone-script entry point) does that."""
    _fresh_engine(monkeypatch, tmp_path)
    calls: list[tuple[str, bool]] = []
    _patch_compute(monkeypatch, calls)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("recompute_all() must not call this")

    monkeypatch.setattr(recompute, "configure_logging", fail_if_called)
    monkeypatch.setattr(recompute, "init_db", fail_if_called)

    summary = asyncio.run(recompute.recompute_all(tickers=["AAPL"]))

    assert summary["processed"] == 1
