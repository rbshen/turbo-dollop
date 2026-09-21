import asyncio
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.market_breadth_data as market_breadth_data
import pipeline.nightly_market_breadth as nightly_market_breadth
from core.models import IndexConstituent, MarketBreadthSnapshot


def _fresh_engine(monkeypatch, tmp_path, constituents: list[tuple[str, str]]):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(market_breadth_data, "engine", engine)
    monkeypatch.setattr(nightly_market_breadth, "engine", engine)
    monkeypatch.setattr(nightly_market_breadth, "init_db", lambda: None)  # would create_all on the REAL db
    monkeypatch.setattr(nightly_market_breadth, "LOG_PATH", tmp_path / "test_nightly_market_breadth.log")
    monkeypatch.setattr(market_breadth_data, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))
    with Session(engine) as session:
        for index_name, ticker in constituents:
            session.add(IndexConstituent(index_name=index_name, ticker=ticker, company_name=ticker, last_synced_at=datetime(2026, 9, 20)))
        session.commit()
    return engine


def _frame() -> pd.DataFrame:
    index = pd.bdate_range(end="2026-09-18", periods=300)
    close = pd.Series(np.linspace(100, 150, 300), index=index)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1000})


def _patch_bars(monkeypatch, requested: list):
    async def fake(tickers, interval, lookback_days, auto_adjust=False, **_):
        requested.extend(tickers)
        return {t: _frame() for t in tickers}

    monkeypatch.setattr(market_breadth_data, "get_or_fetch_bars_batch", fake)


def test_main_uses_the_sp500_constituents_only_and_returns_a_summary(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path, [("sp500", "AAA"), ("sp500", "BBB"), ("dow", "DOWONLY")])
    requested: list = []
    _patch_bars(monkeypatch, requested)

    summary = asyncio.run(nightly_market_breadth.main())

    # Strictly S&P 500 -- not load_universe_tickers' sp500 + dow union.
    assert sorted(requested) == ["AAA", "BBB"]
    assert summary["as_of_date"] == "2026-09-18" and summary["constituents"] == 2 and summary["with_bar"] == 2
    assert summary["duration_seconds"] >= 0
    with Session(engine) as session:
        (row,) = session.exec(select(MarketBreadthSnapshot)).all()
    assert row.universe == "sp500" and row.constituents == 2 and row.is_backfilled is False


def test_main_propagates_a_coverage_failure_so_the_heartbeat_sees_it(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path, [("sp500", "AAA"), ("sp500", "BBB")])

    async def only_one(tickers, interval, lookback_days, auto_adjust=False, **_):
        return {"AAA": _frame()}

    monkeypatch.setattr(market_breadth_data, "get_or_fetch_bars_batch", only_one)

    with pytest.raises(market_breadth_data.InsufficientCoverageError):
        asyncio.run(nightly_market_breadth.main())
    with Session(engine) as session:
        assert session.exec(select(MarketBreadthSnapshot)).all() == []
