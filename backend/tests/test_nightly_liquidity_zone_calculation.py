import core.data_groups as _dg
import asyncio
from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import data.liquidity_zone_data as liquidity_zone_data
import pipeline.nightly_liquidity_zone_calculation as nightly_lz
from core.models import LiquidityZoneAnalysis, TickerScore, Watchlist, WatchlistTicker


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


def _patch_bar_source(
    monkeypatch, bars_by_ticker: dict, stale_tickers: list[str] | None = None, unserved_tickers: list[str] | None = None
):
    calls: list[list[str]] = []
    fallback = unserved_tickers or []

    async def fake_get_bars_batch(tickers, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        calls.append(list(tickers))
        if unserved_tickers is not None:
            unserved_tickers.extend(fallback)
        return bars_by_ticker

    monkeypatch.setattr(nightly_lz, "get_or_fetch_bars_batch", fake_get_bars_batch)

    # stale_ticker_count reads clients.shared_bars_cache's OWN engine
    # directly (not nightly_lz's) -- stubbed here too, same reasoning as
    # tests/test_nightly_trend_calculation.py's own _patch_batch_fetch.
    stale = stale_tickers or []
    monkeypatch.setattr(nightly_lz, "stale_ticker_count", lambda tickers, interval, reference=None: (len(stale), stale))
    return calls


def _patch_store(monkeypatch, fail_for: set[str] | None = None):
    fail_for = fail_for or set()
    calls: list[tuple[str, str]] = []

    def fake_store(ticker, ohlcv, source, settings):
        calls.append((ticker, source))
        if ticker in fail_for:
            raise RuntimeError(f"simulated failure computing {ticker}")
        return None

    monkeypatch.setattr(nightly_lz, "compute_and_store_liquidity_zones", fake_store)
    return calls


def test_main_processes_the_union_of_w1_and_w2_deduped(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "MSFT"])
    _seed_watchlist(engine, "W2", ["MSFT", "GOOG"])  # MSFT overlaps -- must not be double-processed
    _seed_watchlist(engine, "Some Other List", ["ZZZZ"])  # never consulted

    batch_calls = _patch_bar_source(
        monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars(), "GOOG": _fake_bars()}
    )
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0]) == {"AAPL", "MSFT", "GOOG"}
    assert sorted(t for t, _ in store_calls) == ["AAPL", "GOOG", "MSFT"]  # each processed exactly once
    assert summary["processed"] == 3
    assert summary["failed"] == 0


def test_main_skips_a_ticker_flagged_as_delisted(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "AVB"])
    with Session(engine) as session:
        session.add(TickerScore(ticker="AVB", overall_score=60, computed_at=datetime.now(), delisted_at=datetime.now()))
        session.commit()

    batch_calls = _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "AVB": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0]) == {"AAPL"}
    assert sorted(t for t, _ in store_calls) == ["AAPL"]
    assert summary["processed"] == 1
    assert summary["skipped_delisted_count"] == 1


def test_main_also_includes_a_third_watchlist_named_w3(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL"])
    _seed_watchlist(engine, "W3", ["GOOG"])  # not just a hardcoded pair -- W3 counts too
    _seed_watchlist(engine, "W6", ["ZZZZ"])  # out of the 1-5 range -- never consulted

    batch_calls = _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "GOOG": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0]) == {"AAPL", "GOOG"}
    assert sorted(t for t, _ in store_calls) == ["AAPL", "GOOG"]
    assert summary["processed"] == 2


def test_summary_reports_the_unserved_count_from_the_batch_fetch(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "MSFT"])
    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars()}, unserved_tickers=["MSFT"])
    _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert summary["unserved_count"] == 1


def test_main_returns_empty_summary_when_no_matching_watchlist_exists(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)

    summary = asyncio.run(nightly_lz.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_main_processes_whichever_matching_watchlist_exists_when_the_other_does_not(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL"])  # "W2" never created

    batch_calls = _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert set(batch_calls[0]) == {"AAPL"}
    assert [t for t, _ in store_calls] == ["AAPL"]
    assert summary["processed"] == 1


def test_main_returns_empty_summary_when_both_watchlists_have_no_tickers(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", [])
    _seed_watchlist(engine, "W2", [])

    summary = asyncio.run(nightly_lz.main())

    assert summary["processed"] == 0
    assert summary["failed"] == 0
    assert summary["duration_seconds"] == 0.0
    assert summary["failures"] == []


def test_a_ticker_with_no_bars_is_a_failure_not_a_crash(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "NODATA"])

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars()})  # NODATA absent from the result
    store_calls = _patch_store(monkeypatch)

    summary = asyncio.run(nightly_lz.main())

    assert [t for t, _ in store_calls] == ["AAPL"]
    assert summary["processed"] == 2
    assert summary["failed"] == 1
    assert summary["failures"][0][0] == "NODATA"


def test_a_failing_ticker_does_not_abort_the_sweep(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "BADCO", "MSFT"])

    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "BADCO": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch, fail_for={"BADCO"})

    summary = asyncio.run(nightly_lz.main())

    assert {t for t, _ in store_calls} == {"AAPL", "BADCO", "MSFT"}
    assert summary["failed"] == 1


def test_rows_are_always_labelled_fmp(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "MSFT"])
    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch)

    asyncio.run(nightly_lz.main())
    assert dict(store_calls) == {"AAPL": "fmp", "MSFT": "fmp"}


def test_a_run_is_skipped_while_daily_prices_is_off_and_computes_nothing(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL", "MSFT"])
    _patch_bar_source(monkeypatch, {"AAPL": _fake_bars(), "MSFT": _fake_bars()})
    store_calls = _patch_store(monkeypatch)
    _dg.set_group_enabled("daily_prices", False)

    summary = asyncio.run(nightly_lz.main())

    assert summary["skipped"] is True and "daily_prices" in summary["skip_reason"]
    assert store_calls == []


def test_main_sweeps_a_row_stale_beyond_the_seven_day_window(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL"])  # DROPPED is on neither list any more

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


def test_reads_daily_bars_through_the_shared_cache_with_the_documented_request_shape(monkeypatch, tmp_path):
    """Interval "1d", ~4yr lookback (Weekly's need -- Daily is sliced from
    it), non-dividend-adjusted -- and no force flag: the shared cache's
    growth+freshness design makes the old per-feature force=True
    unnecessary."""
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_watchlist(engine, "W1", ["AAPL"])
    seen: dict = {}

    async def fake_get_bars_batch(tickers, interval, lookback_days, auto_adjust=True, unserved_tickers=None, **kwargs):
        seen.update(interval=interval, lookback_days=lookback_days, auto_adjust=auto_adjust, kwargs=kwargs)
        return {"AAPL": _fake_bars()}

    monkeypatch.setattr(nightly_lz, "get_or_fetch_bars_batch", fake_get_bars_batch)
    _patch_store(monkeypatch)

    asyncio.run(nightly_lz.main())

    assert seen == {
        "interval": "1d",
        "lookback_days": liquidity_zone_data.LOOKBACK_DAYS,
        "auto_adjust": False,
        "kwargs": {},
    }
    assert liquidity_zone_data.LOOKBACK_DAYS >= 4 * 365
