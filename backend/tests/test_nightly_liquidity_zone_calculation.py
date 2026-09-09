import asyncio
from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import data.liquidity_zone_data as liquidity_zone_data
import pipeline.nightly_liquidity_zone_calculation as nightly_lz
from core.models import LiquidityZoneAnalysis, Watchlist, WatchlistTicker


def _fake_bars() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.DataFrame(
        {"open": [1.0] * 10, "high": [1.0] * 10, "low": [1.0] * 10, "close": [1.0] * 10, "volume": [1] * 10}, index=dates
    )


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly_lz, "engine", engine)
    # sweep_stale_liquidity_zones (called directly by main(), not faked via
    # _patch_store) reads liquidity_zone_data's OWN `engine` binding -- a
    # separate import from nightly_lz's, per CLAUDE.md's engine-isolation
    # convention. Missing this leaves it pointed at the real
    # core.db.engine, which the session-scoped write-guard in conftest.py
    # catches immediately.
    monkeypatch.setattr(liquidity_zone_data, "engine", engine)
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
    calls: list[tuple[str, str]] = []

    def fake_store(ticker, ohlcv, source, config):
        calls.append((ticker, source))
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure computing {ticker}")
        return None

    monkeypatch.setattr(nightly_lz, "compute_and_store_liquidity_zones", fake_store)
    return calls


def test_main_processes_the_union_of_main_and_secondary_deduped(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "Secondary", ["MSFT", "GOOG"])  # MSFT overlaps -- must not be double-processed
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])  # never consulted

    batch_calls = _patch_bar_source(
        monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars(), "GOOG": _fake_bars()}
    )
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0][0]) == {"AAPL", "MSFT", "GOOG"}
    assert batch_calls[0][1] == nightly_lz.LOOKBACK_YEARS
    assert sorted(t for t, _ in store_calls) == ["AAPL", "GOOG", "MSFT"]  # each processed exactly once
    assert summary["processed"] == 3
    assert summary["failed"] == 0


def test_main_returns_empty_summary_when_neither_watchlist_exists(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly_lz.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_main_continues_with_whichever_list_exists_when_one_is_missing(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", ["AAPL"])  # "Secondary" never created

    batch_calls = _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0][0]) == {"AAPL"}
    assert [t for t, _ in store_calls] == ["AAPL"]
    assert summary["processed"] == 1


def test_main_returns_empty_summary_when_both_watchlists_have_no_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", [])
    _seed_watchlist(engine, "Secondary", [])

    summary = asyncio.run(nightly_lz.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_a_ticker_with_no_bars_is_a_failure_not_a_crash(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", ["AAPL", "NODATA"])

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})  # NODATA absent from the result
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert [t for t, _ in store_calls] == ["AAPL"]
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "NODATA"


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", ["AAPL", "BADCO", "MSFT"])

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "BADCO": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_lz.main())

    assert {t for t, _ in store_calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1


def test_source_is_fmp_when_enabled_and_yahoo_when_disabled(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", ["AAPL"])
    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    monkeypatch.setattr(nightly_lz.settings, "fmp_enabled", True)
    asyncio.run(nightly_lz.main())
    assert store_calls[-1] == ("AAPL", "fmp")

    monkeypatch.setattr(nightly_lz.settings, "fmp_enabled", False)
    asyncio.run(nightly_lz.main())
    assert store_calls[-1] == ("AAPL", "yahoo")


def test_main_sweeps_a_row_stale_beyond_the_seven_day_window(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "Main", ["AAPL"])  # DROPPED is on neither list any more

    stale_computed_at = datetime.now() - timedelta(days=8)
    with Session(engine) as session:
        session.add(
            LiquidityZoneAnalysis(
                ticker="DROPPED",
                timeframe="daily",
                last_price=100.0,
                as_of=stale_computed_at.date(),
                support_zones_json='[{"price": 90.0, "cluster_size": 1, "formed_at": "2026-01-01"}]',
                resistance_zones_json='[{"price": 130.0, "cluster_size": 1, "formed_at": "2026-01-01"}]',
                source="fmp",
                computed_at=stale_computed_at,
            )
        )
        session.commit()

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})
    _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert summary["swept"] == 1
    with Session(engine) as session:
        row = session.get(LiquidityZoneAnalysis, ("DROPPED", "daily"))
    assert row.support_zones_json == "[]"
    assert row.resistance_zones_json == "[]"
    assert row.computed_at == stale_computed_at  # last-known marker untouched
