import asyncio
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_bar_sources as daily_bar_sources
import clients.shared_bars_cache as shared_bars_cache
import data.entry_signal_data as entry_signal_data
import pipeline.nightly_entry_signal_calculation as nightly_entry_signal
from analysis.entry_signal.engine import compute_entry_signal
from core.cron_health import CronRunContext
from core.models import SharedBarsCache, TechnicalEntrySignal, Watchlist, WatchlistTicker


def _fake_bars() -> pd.DataFrame:
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]})


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(nightly_entry_signal, "engine", engine)
    # sweep_stale_entry_signals (called directly by main(), not faked via
    # _patch_store) reads entry_signal_data's OWN `engine` binding -- a
    # separate import from nightly_entry_signal's, per CLAUDE.md's
    # engine-isolation convention. Missing this leaves it pointed at the
    # real core.db.engine, which the session-scoped write-guard in
    # conftest.py catches immediately.
    monkeypatch.setattr(entry_signal_data, "engine", engine)
    # stale_ticker_count reads clients.shared_bars_cache's OWN engine -- point it at the same in-memory DB (empty
    # unless a test seeds bars) so it never falls through to the real on-disk engine.
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    monkeypatch.setattr(daily_bar_sources, "engine", engine)  # route_by_source reads cached profiles through this one
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


def test_main_processes_the_union_of_e1_and_e2_deduped(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "E2", ["MSFT", "GOOG"])  # MSFT overlaps -- must not be double-processed
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])  # never consulted

    batch_calls = _patch_batch_fetch(
        monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars(), "GOOG": _fake_bars()}
    )
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL", "MSFT", "GOOG"}
    assert batch_calls[0][1] == nightly_entry_signal.LOOKBACK_DAYS
    assert sorted(store_calls) == ["AAPL", "GOOG", "MSFT"]  # each processed exactly once
    assert summary["processed"] == 3
    assert summary["failed"] == 0


def test_main_also_includes_a_watchlists_named_e10_and_etf(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])
    _seed_watchlist(engine, "E10", ["GOOG"])  # not just a hardcoded pair -- E10 (no upper limit) counts too
    _seed_watchlist(engine, "ETF", ["SPY"])  # the one non-numbered monitored list
    _seed_watchlist(engine, "W1", ["ZZZZ"])  # the retired name -- no longer monitored, never consulted

    batch_calls = _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "GOOG": _fake_bars(), "SPY": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL", "GOOG", "SPY"}
    assert sorted(store_calls) == ["AAPL", "GOOG", "SPY"]
    assert summary["processed"] == 3


def test_main_returns_empty_summary_when_no_matching_watchlist_exists(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly_entry_signal.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_main_processes_whichever_matching_watchlist_exists_when_the_other_does_not(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])  # "E2" never created

    batch_calls = _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert set(batch_calls[0][0]) == {"AAPL"}
    assert store_calls == ["AAPL"]
    assert summary["processed"] == 1


def test_main_returns_empty_summary_when_both_watchlists_have_no_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", [])
    _seed_watchlist(engine, "E2", [])

    summary = asyncio.run(nightly_entry_signal.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_a_ticker_with_no_bars_is_a_failure_not_a_crash(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL", "NODATA"])

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})  # NODATA absent from the batch result
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert store_calls == ["AAPL"]
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "NODATA"


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL", "BADCO", "MSFT"])

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars(), "BADCO": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_entry_signal.main())

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
                signal_type="bb_rsi",
                timeframe="2h",
                fired_at=stale_computed_at,
                pct_b=0.01,
                rsi=20.0,
                close=50.0,
                stop_price=45.0,
                source="fmp",
                as_of=stale_computed_at,
                computed_at=stale_computed_at,
            )
        )
        session.commit()

    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})
    _patch_store(monkeypatch)

    summary = asyncio.run(nightly_entry_signal.main())

    assert summary["swept"] == 1
    with Session(engine) as session:
        row = session.get(TechnicalEntrySignal, ("DROPPED", "bb_rsi", "2h"))
    assert row.fired_at is None
    assert row.pct_b is None
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


def _synthetic_60m_bars(days: int = 40) -> pd.DataFrame:
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

    summary = asyncio.run(nightly_entry_signal.main())

    assert summary["stale_count"] == 1
    assert sorted(store_calls) == ["FRESH", "STALE"]  # a stale ticker is still computed, only surfaced
    assert summary["failed"] == 0
    assert "Stale: 1." in (tmp_path / "test_nightly_entry_signal_calculation.log").read_text()

    run = CronRunContext()
    nightly_entry_signal.record_outcome(summary, run)  # the stale count never feeds the failure threshold
    assert run.message == "2 computed, 0 failed, 0 swept, 0 pruned, 1 still stale after fetch"


def test_a_ticker_with_no_cached_bars_at_all_counts_as_stale(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["AAPL"])
    _patch_batch_fetch(monkeypatch, {"AAPL": _fake_bars()})
    _patch_store(monkeypatch)

    assert asyncio.run(nightly_entry_signal.main())["stale_count"] == 1


def test_signal_output_is_identical_for_a_stale_and_a_fresh_ticker(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "E1", ["FRESH", "STALE"])
    latest = shared_bars_cache._most_recent_completed_intraday_bar_start()
    _seed_cached_bar(engine, "FRESH", latest)
    _seed_cached_bar(engine, "STALE", latest - timedelta(days=3))
    bars = _synthetic_60m_bars()
    _patch_batch_fetch(monkeypatch, {"FRESH": bars, "STALE": bars})  # real compute_and_store_entry_signal

    summary = asyncio.run(nightly_entry_signal.main())

    expected = compute_entry_signal(bars)
    fields = ("as_of", "fired_at", "pct_b", "rsi", "close", "stop_price")
    with Session(engine) as session:
        rows = {t: session.get(TechnicalEntrySignal, (t, "bb_rsi", "2h")) for t in ("FRESH", "STALE")}
    assert summary["stale_count"] == 1 and summary["failed"] == 0
    for t, row in rows.items():
        assert row is not None, t
        assert row.as_of == expected.as_of
        assert row.fired_at == expected.fired_at
    assert [getattr(rows["FRESH"], f) for f in fields] == [getattr(rows["STALE"], f) for f in fields]
