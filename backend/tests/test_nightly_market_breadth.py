import asyncio
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.market_breadth_data as market_breadth_data
import pipeline.nightly_market_breadth as nightly_market_breadth
from core.models import IndexConstituent, MarketBreadthGateLog, MarketBreadthSnapshot
from data.sector_heatmap_data import SECTOR_ETFS


def _fresh_engine(monkeypatch, tmp_path, constituents: list[tuple[str, str]], sectors: dict[str, str] | None = None):
    """`sectors` optionally maps ticker -> a real IndexConstituent.sector string (e.g. "Technology") so
    load_sector_buckets has something real to bucket; omitted entirely, every row's `sector` stays NULL
    (unmapped, so load_sector_buckets returns 11 empty buckets -- fine for tests that don't care about
    sectors at all)."""
    sectors = sectors or {}
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(market_breadth_data, "engine", engine)
    monkeypatch.setattr(nightly_market_breadth, "engine", engine)
    monkeypatch.setattr(nightly_market_breadth, "init_db", lambda: None)  # would create_all on the REAL db
    monkeypatch.setattr(nightly_market_breadth, "LOG_PATH", tmp_path / "test_nightly_market_breadth.log")
    monkeypatch.setattr(market_breadth_data, "_most_recent_completed_trading_date", lambda: date(2026, 9, 18))
    with Session(engine) as session:
        for index_name, ticker in constituents:
            session.add(
                IndexConstituent(
                    index_name=index_name, ticker=ticker, company_name=ticker, sector=sectors.get(ticker), last_synced_at=datetime(2026, 9, 20)
                )
            )
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


def test_main_also_computes_and_stores_sector_rows(monkeypatch, tmp_path):
    constituents = [("sp500", "AAA"), ("sp500", "BBB"), ("sp500", "CCC")]
    sectors = {"AAA": "Technology", "BBB": "Technology", "CCC": "Energy"}
    engine = _fresh_engine(monkeypatch, tmp_path, constituents, sectors=sectors)
    _patch_bars(monkeypatch, [])

    summary = asyncio.run(nightly_market_breadth.main())

    assert summary["sectors"]["XLK"]["passed"] is True and summary["sectors"]["XLK"]["constituents"] == 2
    assert summary["sectors"]["XLE"]["passed"] is True and summary["sectors"]["XLE"]["constituents"] == 1
    # Every other one of the 11 SPDR ETFs is present too, just empty (0 constituents) -- refused, not crashed.
    assert set(summary["sectors"]) == {etf for etf, _ in SECTOR_ETFS}

    with Session(engine) as session:
        universes = {row.universe for row in session.exec(select(MarketBreadthSnapshot)).all()}
    assert {"sp500", "sector:XLK", "sector:XLE"} <= universes
    assert "sector:XLF" not in universes  # empty bucket -- 0 constituents, refused, no row


def _summary(refused: list[str]) -> dict:
    sectors = {etf: {"passed": etf not in refused} for etf, _ in SECTOR_ETFS}
    return {"with_bar": 501, "constituents": 504, "unserved_count": 1, "sectors": sectors}


def test_run_message_names_no_sector_when_none_were_refused():
    assert "refused" not in nightly_market_breadth.run_message(_summary([]))
    assert "refused" not in nightly_market_breadth.run_message({"with_bar": 3, "constituents": 3, "unserved_count": 0})  # no sector_tickers


def test_run_message_names_one_refused_sector():
    message = nightly_market_breadth.run_message(_summary(["XLC"]))
    assert message.startswith("501/504 constituents, ") and message.endswith(", 1 sector refused: XLC")


def test_run_message_lists_every_refused_sector_in_sector_order():
    # SECTOR_ETFS order (XLB before XLC), not the order they were refused in.
    assert nightly_market_breadth.run_message(_summary(["XLC", "XLB", "XLK"])).endswith(", 3 sectors refused: XLK, XLB, XLC")


def _gate_row(universe: str, checked_at: datetime) -> MarketBreadthGateLog:
    return MarketBreadthGateLog(
        universe=universe, as_of_date=checked_at.date(), checked_at=checked_at, constituents=1, with_bar=1,
        missing_count=0, missing_tickers_json="[]", passed=True, passed_via="percentage",
    )


def test_main_prunes_old_gate_log_rows_and_keeps_recent_ones(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path, [("sp500", "AAA"), ("sp500", "BBB")])
    _patch_bars(monkeypatch, [])
    days = market_breadth_data.GATE_LOG_RETENTION_DAYS
    with Session(engine) as session:
        session.add(_gate_row("old", datetime.now() - timedelta(days=days + 5)))
        session.add(_gate_row("recent", datetime.now() - timedelta(days=days - 5)))
        session.commit()

    summary = asyncio.run(nightly_market_breadth.main())

    assert summary["gate_log_pruned"] == 1
    with Session(engine) as session:
        universes = {log.universe for log in session.exec(select(MarketBreadthGateLog)).all()}
    assert "old" not in universes and {"recent", "sp500"} <= universes  # today's own gate row is kept


def test_a_gate_log_prune_failure_does_not_fail_the_job(monkeypatch, tmp_path):
    engine = _fresh_engine(monkeypatch, tmp_path, [("sp500", "AAA"), ("sp500", "BBB")])
    _patch_bars(monkeypatch, [])

    def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(nightly_market_breadth, "prune_gate_log", boom)

    summary = asyncio.run(nightly_market_breadth.main())

    assert summary["gate_log_pruned"] is None and summary["with_bar"] == 2
    with Session(engine) as session:
        (row,) = session.exec(select(MarketBreadthSnapshot)).all()
    assert row.universe == "sp500"
