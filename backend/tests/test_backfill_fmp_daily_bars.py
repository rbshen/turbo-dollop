import asyncio
from datetime import date, datetime, timedelta

import httpx
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.daily_bar_sources as daily_bar_sources
import clients.shared_bars_cache as shared_bars_cache
import pipeline.backfills.backfill_fmp_daily_bars as backfill
from clients.daily_bar_sources import FMPDailySource
from core.models import SharedBarsCache, TickerScore

TODAY = date(2026, 9, 23)


class FakeFMP:
    def __init__(self, series, failing=()):
        self.series, self.failing = series, set(failing)

    async def get_historical_price_eod(self, ticker, from_date, to_date, group="daily_prices"):
        if ticker in self.failing:
            raise httpx.ConnectError("boom")
        return [
            {"date": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 10}
            for d, c in sorted(self.series.get(ticker, {}).items(), reverse=True)
        ]


def _series(start, n, base=100.0, scale=1.0):
    return {start + timedelta(days=i): (base + i) * scale for i in range(n)}


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    for module in (backfill, shared_bars_cache, daily_bar_sources):
        monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(backfill, "init_db", lambda: None)
    monkeypatch.setattr(backfill, "LOG_PATH", tmp_path / "bf.log")
    monkeypatch.setattr(backfill, "_eastern_today", lambda: TODAY)
    monkeypatch.setattr(daily_bar_sources, "_completed_session", lambda: TODAY)
    return engine


def _seed(engine, ticker, series, fetched=datetime(2026, 9, 1)):
    with Session(engine) as session:
        for d, c in series.items():
            session.add(SharedBarsCache(ticker=ticker, interval="1d", bar_time=datetime.combine(d, datetime.min.time()),
                                        open=c, high=c, low=c, close=c, volume=1, fetched_at=fetched))
        session.commit()


def _rows(engine, ticker):
    with Session(engine) as session:
        return {r.bar_time.date(): r.close for r in session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == ticker)).all()}


def _run(monkeypatch, fmp, tickers, **kwargs):
    monkeypatch.setattr(backfill, "FMPDailySource", lambda: FMPDailySource(client=fmp))
    return asyncio.run(backfill.main(tickers, **kwargs))


def test_dry_run_writes_nothing_but_reports_the_comparison(env, monkeypatch):
    old = _series(TODAY - timedelta(days=99), 100)
    _seed(env, "AAPL", old)
    summary = _run(monkeypatch, FakeFMP({"AAPL": _series(TODAY - timedelta(days=99), 100, scale=0.9)}), ["AAPL"], dry_run=True)
    assert summary["served_by_fmp"] == 1 and summary["rows_written"] == 0
    assert summary["tickers_with_days_off_gt_1pct"] == ["AAPL"]  # a 10% restatement (spin-off shaped)
    assert _rows(env, "AAPL") == old


def test_real_run_replaces_a_stitched_history_and_reports_shrink(env, monkeypatch):
    stitched = _series(TODAY - timedelta(days=499), 500, base=10.0)  # an old ticker's rows under a reused symbol
    _seed(env, "SPCX", stitched)
    fresh = _series(TODAY - timedelta(days=70), 71, base=160.0)
    summary = _run(monkeypatch, FakeFMP({"SPCX": fresh}), ["SPCX"])
    assert summary["shrunk"] == ["SPCX"] and summary["rows_written"] == 71
    assert set(_rows(env, "SPCX")) == set(fresh)  # every old date gone, not upserted over


def test_a_ticker_fmp_cannot_serve_keeps_its_rows_and_delisted_is_skipped(env, monkeypatch):
    _seed(env, "MSFT", _series(TODAY - timedelta(days=99), 100))
    _seed(env, "AVB", _series(TODAY - timedelta(days=99), 100))
    with Session(env) as session:
        session.add(TickerScore(ticker="AVB", computed_at=datetime(2026, 9, 24), delisted_at=datetime(2026, 9, 24)))
        session.commit()
    before = _rows(env, "MSFT")
    summary = _run(monkeypatch, FakeFMP({"AVB": _series(TODAY - timedelta(days=99), 100, scale=2)}, failing={"MSFT"}), ["MSFT", "AVB"])
    assert summary["kept_not_served"] == ["MSFT"] and summary["delisted_skipped"] == ["AVB"]
    assert _rows(env, "AVB")[TODAY] == _series(TODAY - timedelta(days=99), 100)[TODAY]


def test_refuses_to_run_while_daily_prices_is_off(env, monkeypatch):
    import core.data_groups as dg

    dg.set_group_enabled("daily_prices", False)
    with pytest.raises(RuntimeError):
        _run(monkeypatch, FakeFMP({}), ["AAPL"])


def test_non_us_tickers_are_skipped_and_reported(env, monkeypatch):
    summary = _run(monkeypatch, FakeFMP({"AAPL": {date(2026, 9, 1): 10.0}}), ["AAPL", "0005.HK"], dry_run=True)
    assert summary["served_by_fmp"] == 1 and summary["non_us_skipped"] == 1
