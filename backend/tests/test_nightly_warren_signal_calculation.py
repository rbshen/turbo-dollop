import asyncio
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import clients.shared_bars_cache as shared_bars_cache
import data.warren_signal_data as warren_signal_data
import pipeline.nightly_warren_signal_calculation as nightly_warren_signal
from analysis.entry_signal.resample import build_2h_session_candles
from analysis.warren_signal.state_machine import replay
from core.cron_health import CronRunContext
from core.models import SharedBarsCache, TechnicalEntrySignal, Watchlist, WatchlistTicker


def _fake_bars() -> pd.DataFrame:
    # Lowercase columns -- exactly what clients/shared_bars_cache.py's
    # get_or_fetch_bars_batch already returns (no renaming left to do here).
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]})


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly_warren_signal, "engine", engine)
    # sweep_stale_warren_signals/prune_warren_signal_events (called directly
    # by main(), not faked) read data/warren_signal_data.py's OWN `engine`
    # binding, a separate import -- see CLAUDE.md's engine-isolation
    # convention (same pattern test_nightly_entry_signal_calculation.py
    # follows for entry_signal_data.engine).
    monkeypatch.setattr(warren_signal_data, "engine", engine)
    # stale_ticker_count reads clients.shared_bars_cache's OWN engine -- point it at the same in-memory DB (empty
    # unless a test seeds bars) so it never falls through to the real on-disk engine.
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    monkeypatch.setattr(nightly_warren_signal, "LOG_PATH", tmp_path / "test_nightly_warren_signal_calculation.log")
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
    calls: list[tuple[list[str], str, int, bool]] = []

    async def fake_get_or_fetch_bars_batch(tickers, interval, lookback_days, auto_adjust=True, **kwargs):
        calls.append((list(tickers), interval, lookback_days, auto_adjust))
        return bars_by_ticker

    monkeypatch.setattr(nightly_warren_signal, "get_or_fetch_bars_batch", fake_get_or_fetch_bars_batch)
    return calls


def _patch_store(monkeypatch, fail_for: set[str] | None = None):
    fail_for = fail_for or set()
    calls: list[str] = []

    def fake_store(ticker, bars, source):
        calls.append(ticker)
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure computing {ticker}")
        return None

    monkeypatch.setattr(nightly_warren_signal, "compute_and_store_warren_signal", fake_store)
    return calls


def test_main_processes_the_union_of_e1_and_e2_deduped(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "E2", ["MSFT", "GOOG"])  # MSFT overlaps -- must not be double-processed
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])  # never consulted

    batch_calls = _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars(), "GOOG": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_warren_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL", "MSFT", "GOOG"}
    assert batch_calls[0][1] == "60m"  # the raw interval BB+RSI's row shares
    assert batch_calls[0][2] == nightly_warren_signal.LOOKBACK_DAYS == 730
    assert batch_calls[0][3] is False  # auto_adjust=False -- raw, non-dividend-adjusted bars
    assert sorted(store_calls) == ["AAPL", "GOOG", "MSFT"]  # each processed exactly once
    assert summary["processed"] == 3
    assert summary["failed"] == 0


def test_main_also_includes_watchlists_named_e10_and_etf_but_not_the_retired_w1(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])
    _seed_watchlist(engine, "E10", ["GOOG"])  # no upper limit on the number
    _seed_watchlist(engine, "ETF", ["SPY"])
    _seed_watchlist(engine, "W1", ["ZZZZ"])  # the retired name -- no longer monitored

    batch_calls = _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "GOOG": _fake_bars(), "SPY": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_warren_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL", "GOOG", "SPY"}
    assert sorted(store_calls) == ["AAPL", "GOOG", "SPY"]
    assert summary["processed"] == 3


def test_main_returns_empty_summary_when_no_matching_watchlist_exists(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly_warren_signal.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_main_processes_whichever_matching_watchlist_exists_when_the_other_does_not(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])  # "E2" never created

    batch_calls = _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_warren_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL"}
    assert store_calls == ["AAPL"]
    assert summary["processed"] == 1


def test_a_ticker_with_no_bars_is_a_failure_not_a_crash(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL", "NODATA"])

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})  # NODATA absent from the batch result
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_warren_signal.main())

    assert store_calls == ["AAPL"]
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "NODATA"


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL", "BADCO", "MSFT"])

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "BADCO": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_warren_signal.main())

    assert set(store_calls) == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1


def test_main_sweeps_a_row_stale_beyond_the_seven_day_window(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])  # DROPPED is on neither list any more

    stale_computed_at = datetime.now() - timedelta(days=8)
    with Session(engine) as session:
        session.add(
            TechnicalEntrySignal(
                ticker="DROPPED",
                signal_type="warren",
                timeframe="2h",
                fired_at=stale_computed_at,
                rsi=20.0,
                close=50.0,
                stop_price=45.0,
                signal_kind="yellow_up",
                gray_suppressed=False,
                stop_count=0,
                source="fmp",
                as_of=stale_computed_at,
                computed_at=stale_computed_at,
            )
        )
        session.commit()

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})
    _patch_store(monkeypatch)

    summary = asyncio.run(nightly_warren_signal.main())

    assert summary["swept"] == 1
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("DROPPED", "warren", "2h"))
    assert row.fired_at is None
    assert row.signal_kind is None
    assert row.gray_suppressed is None
    assert row.stop_count is None
    assert row.computed_at == stale_computed_at  # last-known marker untouched


def _seed_cached_bar(engine, ticker: str, bar_time: datetime) -> None:
    with Session(engine) as session:
        session.add(
            SharedBarsCache(
                ticker=ticker, interval="60m", bar_time=bar_time, open=1.0, high=1.0, low=1.0, close=1.0, volume=1,
                fetched_at=datetime.now(), source="fmp",
            )
        )
        session.commit()


def _synthetic_60m_bars(days: int = 60) -> pd.DataFrame:
    """Weekday 09:30..15:30 hourly bars (tz-aware America/New_York), a deterministic random walk."""
    rng = np.random.default_rng(7)
    stamps = [
        pd.Timestamp(day.date()).tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=30) + pd.Timedelta(hours=h)
        for day in pd.bdate_range(end="2026-09-30", periods=days)
        for h in range(7)
    ]
    close = 100 + np.cumsum(rng.normal(0, 0.6, len(stamps)))
    return pd.DataFrame(
        {"open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "volume": 1000}, index=pd.DatetimeIndex(stamps)
    )


def test_stale_cached_bars_are_counted_and_reported_but_a_fresh_ticker_is_not(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["FRESH", "STALE"])
    latest = shared_bars_cache._most_recent_completed_intraday_bar_start()
    _seed_cached_bar(engine, "FRESH", latest)  # reflects the most recently completed 60m bar
    _seed_cached_bar(engine, "STALE", latest - timedelta(days=3))  # a fetch that never landed
    _patch_batch_fetch(monkeypatch, {"FRESH": _fake_bars(), "STALE": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_warren_signal.main())

    assert summary["stale_count"] == 1
    assert sorted(store_calls) == ["FRESH", "STALE"]  # a stale ticker is still computed, only surfaced
    assert summary["failed"] == 0
    assert "Stale: 1." in (tmp_path / "test_nightly_warren_signal_calculation.log").read_text()

    run = CronRunContext()
    nightly_warren_signal.record_outcome(summary, run)  # the stale count never feeds the failure threshold
    assert run.message == "2 computed, 0 failed, 0 swept, 0 pruned, 1 still stale after fetch"


def test_a_ticker_with_no_cached_bars_at_all_counts_as_stale(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])
    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})
    _patch_store(monkeypatch)

    assert asyncio.run(nightly_warren_signal.main())["stale_count"] == 1


def test_signal_output_is_identical_for_a_stale_and_a_fresh_ticker(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["FRESH", "STALE"])
    latest = shared_bars_cache._most_recent_completed_intraday_bar_start()
    _seed_cached_bar(engine, "FRESH", latest)
    _seed_cached_bar(engine, "STALE", latest - timedelta(days=3))
    bars = _synthetic_60m_bars()
    _patch_batch_fetch(monkeypatch, {"FRESH": bars, "STALE": bars})  # real compute_and_store_warren_signal

    summary = asyncio.run(nightly_warren_signal.main())

    expected = replay(build_2h_session_candles(bars))
    columns = [c.name for c in TechnicalEntrySignal.__table__.columns if c.name not in ("ticker", "computed_at")]
    with Session(engine) as session:
        rows = {t: session.get(TechnicalEntrySignal, (t, "warren", "2h")) for t in ("FRESH", "STALE")}
    assert summary["stale_count"] == 1 and summary["failed"] == 0
    for t, row in rows.items():
        assert row is not None, t
        assert row.as_of == expected.as_of.replace(tzinfo=None)
    assert {c: getattr(rows["FRESH"], c) for c in columns} == {c: getattr(rows["STALE"], c) for c in columns}
