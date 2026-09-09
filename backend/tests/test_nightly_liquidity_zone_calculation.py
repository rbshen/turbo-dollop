import asyncio
from datetime import datetime

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import pipeline.nightly_liquidity_zone_calculation as nightly_lz
from core.models import Watchlist, WatchlistTicker


def _fake_bars() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame(
        {"open": [1.0] * 10, "high": [1.0] * 10, "low": [1.0] * 10, "close": [1.0] * 10, "volume": [1] * 10}, index=dates
    )


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly_lz, "engine", engine)
    monkeypatch.setattr(nightly_lz, "LOG_PATH", tmp_path / "test_nightly_liquidity_zone_calculation.log")
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


def _patch_bar_source(monkeypatch, bars_by_ticker: dict):
    calls: list[tuple[list[str], int]] = []

    class FakeSource:
        async def get_daily_bars(self, tickers, lookback_years):
            calls.append((list(tickers), lookback_years))
            return bars_by_ticker

    monkeypatch.setattr(nightly_lz, "get_daily_bar_source", lambda: FakeSource())
    return calls


def _patch_store(monkeypatch, fail_for: set[str] | None = None):
    fail_for = fail_for or set()
    calls: list[str] = []

    def fake_store(ticker, ohlcv, source, config):
        calls.append((ticker, source))
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure computing {ticker}")
        return None

    monkeypatch.setattr(nightly_lz, "compute_and_store_liquidity_zones", fake_store)
    return calls


def test_main_processes_only_the_named_watchlists_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])

    batch_calls = _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0][0]) == {"AAPL", "MSFT"}
    assert batch_calls[0][1] == nightly_lz.LOOKBACK_YEARS
    assert {t for t, _ in store_calls} == {"AAPL", "MSFT"}
    assert summary["processed"] == 2
    assert summary["failed"] == 0


def test_main_returns_empty_summary_when_watchlist_does_not_exist(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly_lz.main())

    assert summary == {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}


def test_main_returns_empty_summary_when_watchlist_has_no_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", [])

    summary = asyncio.run(nightly_lz.main())

    assert summary == {"processed": 0, "failed": 0, "duration_seconds": 0.0, "failures": []}


def test_a_ticker_with_no_bars_is_a_failure_not_a_crash(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL", "NODATA"])

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})  # NODATA absent from the result
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert [t for t, _ in store_calls] == ["AAPL"]
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "NODATA"


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL", "BADCO", "MSFT"])

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "BADCO": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_lz.main())

    assert {t for t, _ in store_calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1


def test_source_is_fmp_when_enabled_and_yahoo_when_disabled(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Watchlist", ["AAPL"])
    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    monkeypatch.setattr(nightly_lz.settings, "fmp_enabled", True)
    asyncio.run(nightly_lz.main())
    assert store_calls[-1] == ("AAPL", "fmp")

    monkeypatch.setattr(nightly_lz.settings, "fmp_enabled", False)
    asyncio.run(nightly_lz.main())
    assert store_calls[-1] == ("AAPL", "yahoo")
