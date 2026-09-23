import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.sector_heatmap_data as sector_heatmap_data
from core.models import SectorEtfReturn
from data.sector_heatmap_data import (
    RETENTION_DAYS,
    SECTOR_ETFS,
    _close,
    compute_and_store_sector_returns,
    get_sector_heatmap,
    prune_sector_etf_returns,
)
from scoring.etf_returns import WINDOWS

TICKERS = [t for t, _ in SECTOR_ETFS]
COMPLETED = date(2026, 9, 18)  # a Friday


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sector_heatmap_data, "engine", engine)
    return engine


def _frame(end: str = "2026-09-18", *, close: float = 100.0, anchor_close: float = 110.0,
           start: str = "2024-01-01") -> pd.DataFrame:
    """Flat history at `close`, then the last bar at `anchor_close` -- so
    1w..1y all measure (anchor / flat) - 1. Lowercase columns, matching what
    clients/shared_bars_cache.py::get_or_fetch_bars_batch returns."""
    index = pd.bdate_range(start=start, end=end)
    frame = pd.DataFrame({"close": [close] * len(index)}, index=index)
    frame.iloc[-1] = [anchor_close]
    return frame


def _patch_history(monkeypatch, histories: dict[str, pd.DataFrame]):
    calls = []

    async def fake_get_bars_batch(tickers, interval, lookback_days, auto_adjust=True, **kwargs):
        calls.append({"tickers": list(tickers), "interval": interval, "lookback_days": lookback_days, "auto_adjust": auto_adjust})
        return {t: histories[t] for t in tickers if t in histories}

    monkeypatch.setattr(sector_heatmap_data, "get_or_fetch_bars_batch", fake_get_bars_batch)
    return calls


def _all_histories(**kwargs) -> dict[str, pd.DataFrame]:
    return {t: _frame(**kwargs) for t in TICKERS}


def _stored(engine) -> list[SectorEtfReturn]:
    with Session(engine) as session:
        return list(session.exec(select(SectorEtfReturn)).all())


def test_close_raises_on_a_frame_with_no_close_column():
    with pytest.raises(ValueError, match="close"):
        _close(pd.DataFrame({"open": [1.0]}))


def test_universe_is_the_eleven_spdr_sectors_in_fixed_order():
    assert TICKERS == ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]


def test_stores_every_window_for_every_ticker_via_one_unadjusted_batch_fetch(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    calls = _patch_history(monkeypatch, _all_histories())

    summary = asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    assert summary["processed"] == 11 and summary["failed"] == 0
    assert summary["as_of_date"] == "2026-09-18"
    rows = _stored(engine)
    assert len(rows) == 11 * len(WINDOWS)
    assert {r.as_of_date for r in rows} == {COMPLETED}
    assert len(calls) == 1
    assert calls[0]["tickers"] == TICKERS
    assert calls[0]["auto_adjust"] is False and calls[0]["interval"] == "1d"


def test_return_is_plain_price_return_off_close_not_dividend_adjusted(monkeypatch):
    """2026-09-23 Massive migration decision: plain split-adjusted Close,
    no dividend/total-return reconstruction."""
    engine = _fresh_engine(monkeypatch)
    _patch_history(monkeypatch, _all_histories(anchor_close=104.0))

    asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    one_year = next(r for r in _stored(engine) if r.ticker == "XLK" and r.return_window == "1y")
    assert one_year.return_pct == pytest.approx(4.0)
    assert one_year.base_date == date(2025, 9, 18)


def test_frame_without_close_column_is_a_failure_not_a_crash(monkeypatch):
    # _close()'s defensive column check (dropping the only column makes the
    # frame itself register as .empty, so this actually exercises the
    # earlier "no bars returned" branch -- both paths land in `failures`
    # rather than raising, which is the behavior under test here).
    engine = _fresh_engine(monkeypatch)
    histories = _all_histories()
    histories["XLE"] = histories["XLE"].drop(columns=["close"])
    _patch_history(monkeypatch, histories)

    summary = asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    assert summary["processed"] == 10 and summary["failed"] == 1
    assert summary["failures"][0][0] == "XLE"
    assert not [r for r in _stored(engine) if r.ticker == "XLE"]


def test_rerun_on_the_same_anchor_overwrites_instead_of_duplicating(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_history(monkeypatch, _all_histories(anchor_close=110.0))
    asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))
    _patch_history(monkeypatch, _all_histories(anchor_close=120.0))
    asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    rows = _stored(engine)
    assert len(rows) == 11 * len(WINDOWS)
    assert {round(r.return_pct, 6) for r in rows} == {20.0}


def test_in_progress_bar_after_the_last_completed_session_is_dropped(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    histories = {}
    for ticker in TICKERS:
        frame = _frame(end="2026-09-18")
        # A live Monday bar yfinance returned mid-session; completed session is Friday.
        frame.loc[pd.Timestamp("2026-09-21")] = [5000.0]
        histories[ticker] = frame
    _patch_history(monkeypatch, histories)

    summary = asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    assert summary["as_of_date"] == "2026-09-18"
    assert {r.as_of_date for r in _stored(engine)} == {COMPLETED}
    assert {round(r.return_pct, 6) for r in _stored(engine)} == {10.0}


def test_market_holiday_anchors_to_the_last_real_trading_day(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    # The weekday-aware "completed" date is Mon 2026-09-07 (Labor Day), which
    # has no bar -- the anchor must be Fri 09-04, the last bar on/before it.
    _patch_history(monkeypatch, _all_histories(end="2026-09-04"))

    summary = asyncio.run(compute_and_store_sector_returns(completed_date=date(2026, 9, 7)))

    assert summary["as_of_date"] == "2026-09-04"
    assert {r.as_of_date for r in _stored(engine)} == {date(2026, 9, 4)}


def test_a_missing_ticker_is_reported_and_others_still_store(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    histories = _all_histories()
    del histories["XLC"]
    _patch_history(monkeypatch, histories)

    summary = asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    assert summary["processed"] == 10
    assert summary["failures"] == [("XLC", "no bars returned")]
    assert {r.ticker for r in _stored(engine)} == set(TICKERS) - {"XLC"}


def test_nothing_computable_raises_so_the_heartbeat_records_a_failed_run(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_history(monkeypatch, {})

    with pytest.raises(RuntimeError, match="no usable bars"):
        asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))
    assert _stored(engine) == []


def test_young_fund_stores_null_windows_it_cannot_cover(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    histories = _all_histories()
    histories["XLC"] = _frame(start="2026-06-01")
    _patch_history(monkeypatch, histories)

    asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    by_window = {r.return_window: r for r in _stored(engine) if r.ticker == "XLC"}
    assert by_window["3m"].return_pct == pytest.approx(10.0)
    assert by_window["1y"].return_pct is None and by_window["1y"].base_date is None
    assert by_window["ytd"].return_pct is None


def test_get_sector_heatmap_is_empty_before_any_run(monkeypatch):
    _fresh_engine(monkeypatch)
    result = get_sector_heatmap()
    assert result.as_of_date is None and result.computed_at is None
    assert result.rows == []
    assert result.windows == list(WINDOWS)


def test_get_sector_heatmap_reads_only_the_latest_as_of_date_in_universe_order(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _patch_history(monkeypatch, _all_histories(end="2026-09-17", anchor_close=101.0))
    asyncio.run(compute_and_store_sector_returns(completed_date=date(2026, 9, 17)))
    _patch_history(monkeypatch, _all_histories(anchor_close=110.0))
    asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    result = get_sector_heatmap()

    assert result.as_of_date == COMPLETED
    assert isinstance(result.computed_at, datetime)
    assert [r.ticker for r in result.rows] == TICKERS
    assert result.rows[0].name == "Technology"
    for row in result.rows:
        assert list(row.cells) == list(WINDOWS)
        assert row.cells["1y"].return_pct == pytest.approx(10.0)
        assert row.cells["ytd"].base_date == date(2025, 12, 31)
    # History is kept, only the read is latest-only.
    assert len({r.as_of_date for r in _stored(engine)}) == 2


def test_a_ticker_missing_from_the_latest_run_reads_blank_not_stale(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_history(monkeypatch, _all_histories(end="2026-09-17", anchor_close=150.0))
    asyncio.run(compute_and_store_sector_returns(completed_date=date(2026, 9, 17)))
    histories = _all_histories()
    del histories["XLU"]
    _patch_history(monkeypatch, histories)
    asyncio.run(compute_and_store_sector_returns(completed_date=COMPLETED))

    result = get_sector_heatmap()

    xlu = next(r for r in result.rows if r.ticker == "XLU")
    assert all(cell.return_pct is None and cell.base_date is None for cell in xlu.cells.values())
    xlk = next(r for r in result.rows if r.ticker == "XLK")
    assert xlk.cells["1m"].return_pct == pytest.approx(10.0)


def _seed_snapshot(engine, as_of: date, tickers=("XLK", "XLE"), windows=("1m", "1y")) -> int:
    with Session(engine) as session:
        for ticker in tickers:
            for window in windows:
                session.add(SectorEtfReturn(ticker=ticker, return_window=window, as_of_date=as_of, base_date=as_of - timedelta(days=30),
                                            return_pct=1.0, computed_at=datetime(2026, 1, 1)))
        session.commit()
    return len(tickers) * len(windows)


def test_retention_is_a_rolling_370_days():
    assert RETENTION_DAYS == 370


def test_prune_keeps_a_row_exactly_370_days_old_and_deletes_371(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    newest = date(2026, 9, 18)
    per_snapshot = _seed_snapshot(engine, newest - timedelta(days=370))  # exactly at the limit -> kept
    _seed_snapshot(engine, newest - timedelta(days=371))  # one day past -> pruned
    _seed_snapshot(engine, newest)

    deleted = prune_sector_etf_returns(newest)

    assert deleted == per_snapshot
    remaining = {r.as_of_date for r in _stored(engine)}
    assert remaining == {newest - timedelta(days=370), newest}


def test_prune_is_measured_from_the_newest_snapshot_not_the_wall_clock(monkeypatch):
    # Every seeded date is years before "today"; a wall-clock cutoff would
    # delete all of it. Measured from `as_of`, nothing here is old.
    engine = _fresh_engine(monkeypatch)
    as_of = date(2020, 6, 30)
    _seed_snapshot(engine, as_of)
    _seed_snapshot(engine, as_of - timedelta(days=200))

    assert prune_sector_etf_returns(as_of) == 0
    assert len({r.as_of_date for r in _stored(engine)}) == 2


def test_prune_is_idempotent_and_safe_on_an_empty_table(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    assert prune_sector_etf_returns(COMPLETED) == 0
    _seed_snapshot(engine, COMPLETED - timedelta(days=400))
    assert prune_sector_etf_returns(COMPLETED) > 0
    assert prune_sector_etf_returns(COMPLETED) == 0


def test_prune_removes_every_ticker_and_window_of_an_expired_snapshot(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    expired = COMPLETED - timedelta(days=500)
    n = _seed_snapshot(engine, expired, tickers=TICKERS, windows=WINDOWS)
    assert n == 88

    assert prune_sector_etf_returns(COMPLETED) == 88
    assert _stored(engine) == []
