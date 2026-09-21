import asyncio
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.market_breadth_data as mbd
from core.models import MarketBreadthSnapshot

COMPLETED = date(2026, 9, 18)


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(mbd, "engine", engine)
    return engine


def _frame(end="2026-09-18", periods=300, start_price=100.0, end_price=150.0) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=periods)
    close = pd.Series(np.linspace(start_price, end_price, periods), index=index)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})


def _patch_bars(monkeypatch, bars: dict):
    async def fake(tickers, interval, lookback_days, auto_adjust=False, **_):
        assert interval == "1d" and lookback_days == mbd.FETCH_LOOKBACK_DAYS and auto_adjust is False
        return {t: bars[t] for t in tickers if t in bars}

    monkeypatch.setattr(mbd, "get_or_fetch_bars_batch", fake)


def _tickers(n):
    return [f"T{i:03d}" for i in range(n)]


def _run(tickers, completed=COMPLETED):
    return asyncio.run(mbd.compute_and_store_market_breadth(tickers, completed_date=completed))


def _rows(engine):
    with Session(engine) as session:
        return session.exec(select(MarketBreadthSnapshot)).all()


def test_stores_one_row_for_the_anchor_session(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(10)
    bars = {t: _frame(start_price=100, end_price=150 if i < 6 else 60) for i, t in enumerate(tickers)}
    _patch_bars(monkeypatch, bars)

    summary = _run(tickers)

    (row,) = _rows(engine)
    assert row.universe == "sp500" and row.as_of_date == COMPLETED and row.is_backfilled is False
    assert row.constituents == 10 and row.stale_excluded == 0
    assert row.sma50_eligible == 10 and row.sma50_above == 6 and row.pct_above_sma50 == 60.0
    assert row.sma200_eligible == 10 and row.pct_above_sma200 == 60.0
    # Six rising tickers close on their 52-week high, four falling ones on their low.
    assert row.hl_eligible == 10 and row.new_highs == 6 and row.new_lows == 4 and row.net_new_highs == 2
    assert summary["as_of_date"] == "2026-09-18" and summary["with_bar"] == 10 and summary["net_new_highs"] == 2


def test_a_bar_after_the_last_completed_session_is_ignored(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(5)
    # yfinance's in-progress same-day bar (Mon 9/21) must not become the anchor.
    _patch_bars(monkeypatch, {t: _frame(end="2026-09-21") for t in tickers})
    _run(tickers)
    assert [r.as_of_date for r in _rows(engine)] == [COMPLETED]


@pytest.mark.parametrize("missing, ok", [(15, True), (16, False)])
def test_coverage_gate_boundary_at_503_constituents(monkeypatch, missing, ok):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(503)
    frame = _frame()
    # Missing tickers are stale (last bar a session behind), not absent.
    stale = _frame(end="2026-09-17")
    _patch_bars(monkeypatch, {t: (stale if i < missing else frame) for i, t in enumerate(tickers)})

    if ok:
        summary = _run(tickers)
        (row,) = _rows(engine)
        assert row.stale_excluded == missing and summary["stale_excluded"] == missing
        assert row.sma50_eligible == 503 - missing  # excluded from every count, not counted as "below"
    else:
        with pytest.raises(mbd.InsufficientCoverageError, match="coverage gate"):
            _run(tickers)
        assert _rows(engine) == []  # nothing written below the gate


def test_gate_failure_names_the_missing_tickers(monkeypatch):
    _fresh_engine(monkeypatch)
    tickers = _tickers(10)
    _patch_bars(monkeypatch, {t: _frame() for t in tickers[:5]})  # half never fetched
    with pytest.raises(mbd.InsufficientCoverageError, match="T005"):
        _run(tickers)


def test_no_tickers_or_no_bars_raises(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with pytest.raises(RuntimeError, match="empty universe"):
        _run([])
    _patch_bars(monkeypatch, {})
    with pytest.raises(RuntimeError, match="no usable bars"):
        _run(_tickers(3))
    assert _rows(engine) == []


def test_nightly_overwrites_a_backfilled_row_but_a_backfill_never_overwrites(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(4)
    _patch_bars(monkeypatch, {t: _frame() for t in tickers})
    now = datetime(2026, 9, 21, 3, 35)
    backfilled = dict(
        universe="sp500", as_of_date=COMPLETED, computed_at=now, constituents=4, stale_excluded=0, sma50_eligible=4, sma50_above=0,
        pct_above_sma50=0.0, sma200_eligible=4, sma200_above=0, pct_above_sma200=0.0, hl_eligible=4, new_highs=0, new_lows=0,
        net_new_highs=0, is_backfilled=True,
    )
    assert mbd.store_snapshots([backfilled], overwrite=False) == 1

    _run(tickers)
    (row,) = _rows(engine)
    assert row.is_backfilled is False and row.pct_above_sma50 == 100.0

    # Re-running the backfill leaves the live row alone.
    mbd.store_snapshots([backfilled], overwrite=False)
    (row,) = _rows(engine)
    assert row.is_backfilled is False and row.pct_above_sma50 == 100.0
    # And a weekend/holiday re-run of the same anchor is idempotent.
    _run(tickers)
    assert len(_rows(engine)) == 1


def test_backfill_rows_only_span_sessions_with_full_universe_coverage():
    tickers = _tickers(10)
    # One of 10 constituents is young (120 bars), so at most 9/10 = 90% are ever
    # eligible for the 52-week window -- under the 97% gate on every session.
    bars = {t: _frame(periods=500) for t in tickers[:9]}
    bars[tickers[9]] = _frame(periods=120)
    values, summary = mbd.build_backfill_rows(bars, constituents=10, completed_date=COMPLETED)
    assert values == [] and summary["kept"] == 0

    # With all 10 fully seeded, the first kept session is the one whose
    # 252-bar window first fills (the 252nd bar).
    values, summary = mbd.build_backfill_rows({t: _frame(periods=500) for t in tickers}, constituents=10, completed_date=COMPLETED)
    index = pd.bdate_range(end="2026-09-18", periods=500)
    assert summary["first_date"] == index[251].date().isoformat() and summary["last_date"] == "2026-09-18"
    assert summary["kept"] == 500 - 251 and summary["sessions_seen"] == 500
    assert all(v["is_backfilled"] is True and v["universe"] == "sp500" for v in values)
    assert all(v["constituents"] == 10 and v["stale_excluded"] == 0 for v in values)


def test_backfill_rows_drop_sessions_after_the_completed_date():
    tickers = _tickers(4)
    values, summary = mbd.build_backfill_rows(
        {t: _frame(end="2026-09-21", periods=300) for t in tickers}, constituents=4, completed_date=COMPLETED
    )
    assert summary["last_date"] == "2026-09-18"
    assert max(v["as_of_date"] for v in values) == COMPLETED


def test_backfill_rows_are_plain_python_values_sqlite_can_bind(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    tickers = _tickers(4)
    values, _ = mbd.build_backfill_rows({t: _frame(periods=300) for t in tickers}, constituents=4, completed_date=COMPLETED)
    assert mbd.store_snapshots(values, overwrite=False) == len(values)
    assert len(_rows(engine)) == len(values)


def test_load_cached_daily_bars_is_a_read_only_view_of_shared_bars_cache(monkeypatch):
    from core.models import SharedBarsCache

    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        for day in pd.bdate_range(end="2026-09-18", periods=5):
            session.add(SharedBarsCache(ticker="AAA", interval="1d", bar_time=day.to_pydatetime(), open=1, high=2, low=0.5, close=1.5,
                                        volume=10, fetched_at=datetime(2026, 9, 19)))
        session.add(SharedBarsCache(ticker="AAA", interval="60m", bar_time=datetime(2026, 9, 18, 9, 30), open=1, high=2, low=0.5,
                                    close=1.5, volume=10, fetched_at=datetime(2026, 9, 19)))
        session.commit()
    frames = mbd.load_cached_daily_bars(["AAA", "MISSING"])
    assert set(frames) == {"AAA"} and len(frames["AAA"]) == 5
