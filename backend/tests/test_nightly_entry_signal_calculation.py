import asyncio
from datetime import datetime

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_entry_signal_calculation as nightly_entry_signal
from core.models import Watchlist, WatchlistTicker


def _fake_bars() -> pd.DataFrame:
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]})


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly_entry_signal, "engine", engine)
    monkeypatch.setattr(nightly_entry_signal, "LOG_PATH", tmp_path / "test_nightly_entry_signal_calculation.log")
    return engine


def _seed_watchlist(engine, name: str, tickers: list[str]) -> None:
    now = datetime.now()
    with Session(engine) as session:
        watchlist = Watchlist(name=name, created_at=now, updated_at=now)
        session.add(watchlist)
        session.commit()
        session.refresh(watchlist)
        for t in tickers:
            session.add(WatchlistTicker(watchlist_id=watchlist.id, ticker=t, added_at=now))
        session.commit()


def _patch_batch_fetch(monkeypatch, bars_by_ticker: dict):
    calls: list[tuple[list[str], int]] = []

    class FakeSource:
        async def get_intraday_bars(self, tickers, lookback_days):
            calls.append((list(tickers), lookback_days))
            return bars_by_ticker

    monkeypatch.setattr(nightly_entry_signal, "get_technical_source", lambda: FakeSource())
    return calls


def _patch_store(monkeypatch, fail_for: set[str] | None = None):
    fail_for = fail_for or set()
    calls: list[str] = []

    def fake_store(ticker, bars, source):
        calls.append(ticker)
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure computing {ticker}")
        return None

    monkeypatch.setattr(nightly_entry_signal, "compute_and_store_entry_signal", fake_store)
    return calls


def test_main_processes_only_the_named_watchlists_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])

    batch_calls = _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL", "MSFT"}
    assert batch_calls[0][1] == nightly_entry_signal.LOOKBACK_DAYS
    assert set(store_calls) == {"AAPL", "MSFT"}
    assert summary["processed"] == 2
    assert summary["failed"] == 0


def test_main_returns_empty_summary_when_watchlist_does_not_exist(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly_entry_signal.main())

    assert summary == {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}


def test_main_returns_empty_summary_when_watchlist_has_no_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", [])

    summary = asyncio.run(nightly_entry_signal.main())

    assert summary == {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}


def test_a_ticker_with_no_bars_is_a_failure_not_a_crash(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL", "NODATA"])

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})  # NODATA absent from the batch result
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert store_calls == ["AAPL"]
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "NODATA"


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL", "BADCO", "MSFT"])

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "BADCO": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_entry_signal.main())

    assert set(store_calls) == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1
