from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import data.market_breadth_data as market_breadth_data
import pipeline.backfills.backfill_market_breadth as backfill
from core.models import IndexConstituent, MarketBreadthSnapshot, SharedBarsCache


def _seed(monkeypatch, tmp_path, tickers, periods=320):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(market_breadth_data, "engine", engine)
    monkeypatch.setattr(backfill, "engine", engine)
    monkeypatch.setattr(backfill, "init_db", lambda: None)  # would create_all on the REAL db
    monkeypatch.setattr(backfill, "LOG_PATH", tmp_path / "test_backfill_market_breadth.log")
    monkeypatch.setattr(backfill, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))
    index = pd.bdate_range(end="2026-09-18", periods=periods)
    with Session(engine) as session:
        for ticker in tickers:
            session.add(IndexConstituent(index_name="sp500", ticker=ticker, company_name=ticker, last_synced_at=datetime(2026, 9, 20)))
            for day, price in zip(index, np.linspace(100, 150, periods)):
                session.add(SharedBarsCache(ticker=ticker, interval="1d", bar_time=day.to_pydatetime(), open=price, high=price + 1,
                                            low=price - 1, close=price, volume=1, fetched_at=datetime(2026, 9, 19)))
        session.commit()
    return engine, index


def _bar_count(engine) -> int:
    with Session(engine) as session:
        return len(session.exec(select(SharedBarsCache)).all())


def test_backfill_inserts_flagged_rows_from_the_cache_and_never_writes_the_cache(monkeypatch, tmp_path):
    engine, index = _seed(monkeypatch, tmp_path, ["AAA", "BBB", "CCC"])
    bars_before = _bar_count(engine)

    summary = backfill.main()

    assert summary["inserted"] == summary["kept"] == 320 - 251 and summary["already_present"] == 0
    assert summary["first_date"] == index[251].date().isoformat() and summary["last_date"] == "2026-09-18"
    with Session(engine) as session:
        rows = session.exec(select(MarketBreadthSnapshot)).all()
    assert len(rows) == summary["inserted"] and all(r.is_backfilled and r.universe == "sp500" for r in rows)
    assert _bar_count(engine) == bars_before  # read-only against SharedBarsCache


def test_rerun_is_a_no_op_and_dry_run_writes_nothing(monkeypatch, tmp_path):
    engine, _ = _seed(monkeypatch, tmp_path, ["AAA", "BBB"])

    dry = backfill.main(dry_run=True)
    assert dry["dry_run"] and dry["kept"] > 0 and dry["inserted"] == 0
    with Session(engine) as session:
        assert session.exec(select(MarketBreadthSnapshot)).all() == []

    first = backfill.main()
    again = backfill.main()
    assert first["inserted"] == first["kept"] and again["inserted"] == 0 and again["already_present"] == again["kept"]


def test_a_ticker_with_no_cached_bars_is_reported(monkeypatch, tmp_path):
    engine, _ = _seed(monkeypatch, tmp_path, ["AAA", "BBB"])
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="NOBARS", company_name="x", last_synced_at=datetime(2026, 9, 20)))
        session.commit()
    summary = backfill.main(dry_run=True)
    assert summary["tickers_without_cached_bars"] == ["NOBARS"] and summary["constituents"] == 3
    # 2 of 3 constituents = 67% < 97%: no session qualifies rather than a skewed subset.
    assert summary["kept"] == 0
