import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.sector_heatmap_data as sector_heatmap_data
import pipeline.nightly_sector_heatmap as nightly_sector_heatmap
from core.models import SectorEtfReturn


def _fresh_engine(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(sector_heatmap_data, "engine", engine)
    monkeypatch.setattr(nightly_sector_heatmap, "LOG_PATH", tmp_path / "test_nightly_sector_heatmap.log")
    return engine


def _frame() -> pd.DataFrame:
    index = pd.bdate_range(start="2024-01-01", end="2026-09-18")
    frame = pd.DataFrame({"Close": [100.0] * len(index), "Adj Close": [100.0] * len(index)}, index=index)
    frame.iloc[-1] = [110.0, 110.0]
    return frame


def test_main_computes_persists_and_returns_a_summary(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(sector_heatmap_data, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))

    async def fake_get_history(tickers, period, interval, auto_adjust):
        return {t: _frame() for t in tickers}

    monkeypatch.setattr(sector_heatmap_data.yahoo_client, "get_history", fake_get_history)

    summary = asyncio.run(nightly_sector_heatmap.main())

    assert summary["as_of_date"] == "2026-09-18"
    assert summary["processed"] == 11 and summary["failed"] == 0
    assert summary["duration_seconds"] >= 0
    with Session(engine) as session:
        assert len(session.exec(select(SectorEtfReturn)).all()) == 88


def test_main_propagates_a_total_failure_so_the_heartbeat_sees_it(monkeypatch, tmp_path):
    _fresh_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(sector_heatmap_data, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))

    async def fake_get_history(tickers, period, interval, auto_adjust):
        return {}

    monkeypatch.setattr(sector_heatmap_data.yahoo_client, "get_history", fake_get_history)

    with pytest.raises(RuntimeError):
        asyncio.run(nightly_sector_heatmap.main())


def _seed_snapshot(engine, as_of: date, per_snapshot_rows: int = 77) -> None:
    with Session(engine) as session:
        for i in range(per_snapshot_rows):
            session.add(SectorEtfReturn(ticker=f"T{i:02d}", return_window="1m", as_of_date=as_of, base_date=None, return_pct=1.0,
                                        computed_at=datetime(2026, 1, 1)))
        session.commit()


def _patch_fetch(monkeypatch, frames_available: bool):
    monkeypatch.setattr(sector_heatmap_data, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))

    async def fake_get_history(tickers, period, interval, auto_adjust):
        return {t: _frame() for t in tickers} if frames_available else {}

    monkeypatch.setattr(sector_heatmap_data.yahoo_client, "get_history", fake_get_history)


def test_main_prunes_snapshots_older_than_the_rolling_window_after_storing(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    anchor = date(2026, 9, 18)
    _seed_snapshot(engine, anchor - timedelta(days=371))  # expired
    _seed_snapshot(engine, anchor - timedelta(days=370))  # exactly at the limit: kept
    _seed_snapshot(engine, anchor - timedelta(days=30))
    _patch_fetch(monkeypatch, frames_available=True)

    summary = asyncio.run(nightly_sector_heatmap.main())

    assert summary["pruned"] == 77
    with Session(engine) as session:
        dates = {r.as_of_date for r in session.exec(select(SectorEtfReturn)).all()}
    assert dates == {anchor - timedelta(days=370), anchor - timedelta(days=30), anchor}


def test_main_keeps_a_one_year_back_snapshot_queryable(monkeypatch, tmp_path):
    # The point of a rolling year over latest-only: the snapshot from the same
    # calendar date last year is still on file after tonight's run.
    engine = _fresh_engine(monkeypatch, tmp_path)
    year_ago = date(2025, 9, 18)
    _seed_snapshot(engine, year_ago, per_snapshot_rows=1)
    _patch_fetch(monkeypatch, frames_available=True)

    asyncio.run(nightly_sector_heatmap.main())

    with Session(engine) as session:
        assert session.exec(select(SectorEtfReturn).where(SectorEtfReturn.as_of_date == year_ago)).first() is not None


def test_a_failed_run_never_prunes(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path)
    _seed_snapshot(engine, date(2024, 1, 2))  # long expired, but nothing new was written
    _patch_fetch(monkeypatch, frames_available=False)

    with pytest.raises(RuntimeError):
        asyncio.run(nightly_sector_heatmap.main())

    with Session(engine) as session:
        assert len(session.exec(select(SectorEtfReturn)).all()) == 77
