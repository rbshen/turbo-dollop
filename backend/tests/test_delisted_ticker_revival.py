"""End-to-end regression test for the delisted-ticker revival loop: a
flagged ticker is skipped by the nightly Trend job every night (see
CLAUDE.md's "Delisted-ticker handling" section) -- which means the
cache-based half of sync_delisted_flags' auto-clear can never fire for it
on its own, since nothing ever refreshes its SharedBarsCache row anymore.
The weekly stale_data_health_check job's live-probe revival check
(pipeline/stale_data_health_check.py::_probe_and_revive) is what actually
closes the loop. This test proves the whole cycle end to end, crossing
both pipeline modules, rather than each module's own unit tests only
proving their own half in isolation."""

import asyncio
from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

import clients.shared_bars_cache as shared_bars_cache
import pipeline.nightly_trend_calculation as nightly_trend
import pipeline.stale_data_health_check as health_check
from core.models import SharedBarsCache, TickerScore


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(health_check, "engine", engine)
    monkeypatch.setattr(nightly_trend, "engine", engine)
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    monkeypatch.setattr(health_check, "LOG_PATH", tmp_path / "test_stale.log")
    monkeypatch.setattr(nightly_trend, "LOG_PATH", tmp_path / "test_trend.log")
    return engine


def _patch_trend_job(monkeypatch, rows_by_ticker: dict):
    """Same shape as tests/test_nightly_trend_calculation.py's own
    _patch_batch_fetch/_patch_store -- records exactly which tickers the
    job actually fetched/processed, without any live Yahoo/Massive call."""
    fetch_calls: list[list[str]] = []

    async def fake_batch(tickers, interval, lookback_days, auto_adjust=True, fallback_tickers=None, **kwargs):
        fetch_calls.append(list(tickers))
        return rows_by_ticker

    monkeypatch.setattr(nightly_trend, "get_or_fetch_bars_batch", fake_batch)
    monkeypatch.setattr(nightly_trend, "stale_ticker_count", lambda tickers, interval, reference=None: (0, []))

    store_calls: list[str] = []

    def fake_store(ticker, ohlcv, benchmark_ohlcv=None):
        store_calls.append(ticker)
        return object()

    monkeypatch.setattr(nightly_trend, "compute_and_store_from_frames", fake_store)
    return fetch_calls, store_calls


def test_flagged_ticker_is_skipped_then_revived_then_included_again(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)

    with Session(engine) as session:
        session.add(TickerScore(ticker="AAPL", overall_score=90, computed_at=datetime.now()))
        session.add(
            TickerScore(
                ticker="TWTR", overall_score=50, computed_at=datetime.now(), delisted_at=datetime.now() - timedelta(days=3)
            )
        )
        session.add(
            SharedBarsCache(
                ticker="TWTR", interval="1d", bar_time=datetime.now() - timedelta(days=45),
                open=1.0, high=1.0, low=1.0, close=1.0, volume=100, fetched_at=datetime.now(),
            )
        )
        session.commit()

    # --- 1. TWTR is already flagged; the nightly Trend job must skip it entirely. ---
    fetch_calls, store_calls = _patch_trend_job(monkeypatch, {"AAPL": [1]})
    summary = asyncio.run(nightly_trend.main(tickers=None))

    assert "TWTR" not in fetch_calls[0]
    assert store_calls == ["AAPL"]
    assert summary["skipped_delisted_count"] == 1

    # --- 2. TWTR's SharedBarsCache row is still frozen at 45 days old --
    #     the cache-based half of sync_delisted_flags' auto-clear cannot
    #     see a fresh bar, proving the deadlock the live probe exists to
    #     break. ---
    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert row.delisted_at is not None

    # --- 3. The weekly health-check job's live probe finds TWTR trading
    #     again (stubbed -- the probe's own Massive/Yahoo mechanics are
    #     covered by tests/test_stale_data_health_check.py directly) and
    #     clears the flag. ---
    async def fake_probe_and_revive(flagged_tickers, threshold_days):
        assert flagged_tickers == ["TWTR"]
        return ["TWTR"]

    monkeypatch.setattr(health_check, "_probe_and_revive", fake_probe_and_revive)

    result = health_check.sync_delisted_flags(["AAPL", "TWTR"])

    assert result == {"newly_flagged": [], "newly_cleared": ["TWTR"]}
    with Session(engine) as session:
        row = session.get(TickerScore, "TWTR")
    assert row.delisted_at is None

    # --- 4. The next nightly Trend run picks TWTR back up. ---
    fetch_calls, store_calls = _patch_trend_job(monkeypatch, {"AAPL": [1], "TWTR": [1]})
    summary = asyncio.run(nightly_trend.main(tickers=None))

    assert "TWTR" in fetch_calls[0]
    assert sorted(store_calls) == ["AAPL", "TWTR"]
    assert summary["skipped_delisted_count"] == 0
