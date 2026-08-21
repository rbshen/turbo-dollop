import asyncio
from datetime import datetime

from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_trend_calculation as nightly_trend
from core.models import FundamentalsCache, TickerScore


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly_trend, "engine", engine)
    monkeypatch.setattr(nightly_trend, "LOG_PATH", tmp_path / "test_nightly_trend_calculation.log")
    return engine


def _patch_batch_fetch(monkeypatch, rows_by_ticker: dict):
    calls: list[list[str]] = []

    async def fake_batch(tickers):
        calls.append(list(tickers))
        return rows_by_ticker

    monkeypatch.setattr(nightly_trend, "get_or_fetch_price_history_batch", fake_batch)
    return calls


def _patch_store(monkeypatch, fail_for: set[str] | None = None):
    fail_for = fail_for or set()
    calls: list[tuple[str, list]] = []

    def fake_store(ticker, rows):
        calls.append((ticker, rows))
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure computing {ticker}")
        return object()

    monkeypatch.setattr(nightly_trend, "compute_and_store_from_rows", fake_store)
    return calls


def test_main_sweeps_the_full_tracked_universe_when_no_tickers_passed(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    with Session(engine) as session:
        session.add(FundamentalsCache(ticker="IREN", statement_type="profile", period="latest", fetched_at=datetime.now(), raw_json="{}"))
        session.add(TickerScore(ticker="SEZL", overall_score=66, overall_verdict="Fail", computed_at=datetime.now()))
        session.commit()

    batch_calls = _patch_batch_fetch(monkeypatch, {"IREN": [1], "SEZL": [1]})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_trend.main(tickers=None))

    assert set(batch_calls[0]) == {"IREN", "SEZL"}
    assert {t for t, _ in store_calls} == {"IREN", "SEZL"}
    assert summary["processed"] == 2
    assert summary["failed"] == 0


def test_main_uses_explicit_ticker_list_when_passed(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    _patch_batch_fetch(monkeypatch, {"AAPL": [1], "MSFT": [1]})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_trend.main(tickers=["AAPL", "MSFT"]))

    assert {t for t, _ in store_calls} == {"AAPL", "MSFT"}
    assert summary["processed"] == 2


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    _patch_batch_fetch(monkeypatch, {"AAPL": [1], "BADCO": [1], "MSFT": [1]})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_trend.main(tickers=["AAPL", "BADCO", "MSFT"]))

    assert {t for t, _ in store_calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1
    assert summary["failures"] == [("BADCO", "simulated failure computing BADCO")]


def test_batch_fetch_is_called_exactly_once_for_the_whole_universe_not_per_ticker(monkeypatch, tmp_path):
    """The spec's explicit requirement: one multi-ticker download, not one
    call per ticker."""
    _fresh_engine(monkeypatch, tmp_path)
    batch_calls = _patch_batch_fetch(monkeypatch, {t: [1] for t in ["AAPL", "MSFT", "GOOG", "AMZN"]})
    _patch_store(monkeypatch)

    asyncio.run(nightly_trend.main(tickers=["AAPL", "MSFT", "GOOG", "AMZN"]))

    assert len(batch_calls) == 1  # exactly one batch call total


def test_ticker_missing_from_batch_result_is_still_attempted_with_empty_rows(monkeypatch, tmp_path):
    """A ticker Yahoo returned nothing for (missing from the batch dict, not
    just an empty list) must still reach compute_and_store_from_rows (with
    empty rows, which raises ValueError there) rather than being silently
    skipped -- so it shows up as a real, visible failure in the run summary."""
    _fresh_engine(monkeypatch, tmp_path)
    _patch_batch_fetch(monkeypatch, {"AAPL": [1]})  # BADCO entirely absent

    def fake_store(ticker, rows):
        if not rows:
            raise ValueError(f"No Yahoo Finance price history available for {ticker}")
        return object()

    monkeypatch.setattr(nightly_trend, "compute_and_store_from_rows", fake_store)

    summary = asyncio.run(nightly_trend.main(tickers=["AAPL", "BADCO"]))

    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "BADCO"


def test_empty_universe_returns_zero_summary_without_calling_batch_fetch(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    batch_calls = _patch_batch_fetch(monkeypatch, {})

    summary = asyncio.run(nightly_trend.main(tickers=[]))

    assert summary == {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}
    assert batch_calls == []
