"""Regression tests for the 2026-09-24 split-adjustment bug: Massive/Polygon's
`adjusted` flag means SPLIT-adjusted, so `adjusted=false` returns raw prices
(fake split cliffs in SharedBarsCache). Every Massive daily-bar call path must
request adjusted=true regardless of the caller's own yfinance-style
auto_adjust flag. (The one-time backfill script's own path is asserted in
test_backfill_massive_daily_bars.py.)"""

import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_bar_sources as daily_bar_sources
import data.chart_data as chart_data
import pipeline.stale_data_health_check as health_check
from clients.daily_bar_sources import MassiveDailySource
from clients.massive_client import MassiveClient
from core.models import SharedBarsCache

TODAY = date(2026, 9, 23)


def _frame(d: date) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [10]}, index=pd.DatetimeIndex([pd.Timestamp(d)])
    )


def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(daily_bar_sources, "engine", engine)
    return engine


def _seed(engine, ticker, d):
    with Session(engine) as s:
        s.add(SharedBarsCache(ticker=ticker, interval="1d", bar_time=datetime.combine(d, datetime.min.time()),
                              open=1, high=2, low=1, close=1, volume=1, fetched_at=datetime.now()))
        s.commit()


class _Recorder:
    def __init__(self, splits=()):
        self.range_adjusted, self.grouped_adjusted, self._splits = [], [], list(splits)

    async def get_recent_splits(self, since):
        return self._splits

    async def get_daily_bars(self, symbol, start, end, adjusted):
        self.range_adjusted.append(adjusted)
        return _frame(TODAY)

    async def get_grouped_daily(self, day, adjusted):
        self.grouped_adjusted.append(adjusted)
        return {"AAPL": _frame(day)}


def test_range_backfill_requests_split_adjusted_even_when_auto_adjust_false(monkeypatch):
    _engine(monkeypatch)
    rec = _Recorder()
    asyncio.run(MassiveDailySource(client=rec).get_daily_bars({"AAPL": 30}, auto_adjust=False, reference=TODAY))
    assert rec.range_adjusted == [True]


def test_grouped_daily_incremental_requests_split_adjusted(monkeypatch):
    engine = _engine(monkeypatch)
    _seed(engine, "AAPL", TODAY - timedelta(days=800))
    _seed(engine, "AAPL", TODAY - timedelta(days=1))
    rec = _Recorder()
    asyncio.run(MassiveDailySource(client=rec).get_daily_bars({"AAPL": 730}, auto_adjust=False, reference=TODAY))
    assert rec.grouped_adjusted == [True] and rec.range_adjusted == []


def test_recent_split_forces_full_range_refetch_adjusted(monkeypatch):
    """A new split must trigger a full-window refetch (not the incremental
    path) and that refetch must itself be split-adjusted, so the whole
    history is restated at the new scale with no double adjustment."""
    engine = _engine(monkeypatch)
    _seed(engine, "AAPL", TODAY - timedelta(days=800))
    _seed(engine, "AAPL", TODAY - timedelta(days=1))
    rec = _Recorder(splits=[{"ticker": "AAPL", "execution_date": TODAY.isoformat()}])
    asyncio.run(MassiveDailySource(client=rec).get_daily_bars({"AAPL": 730}, auto_adjust=False, reference=TODAY))
    assert rec.range_adjusted == [True] and rec.grouped_adjusted == []


def test_massive_client_defaults_and_wire_param_are_split_adjusted(monkeypatch):
    seen = []

    async def fake_get(self, url, params=None, *, absolute=False):
        seen.append(params["adjusted"])
        return {"results": []}

    monkeypatch.setattr(MassiveClient, "_get", fake_get)
    client = MassiveClient(api_key="x")
    asyncio.run(client.get_daily_bars("AAPL", TODAY, TODAY))
    asyncio.run(client.get_grouped_daily(TODAY))
    assert seen == ["true", "true"]


def test_chart_tab_massive_path_requests_split_adjusted(monkeypatch):
    monkeypatch.setattr(chart_data.settings, "massive_enabled", True)
    seen = []

    async def fake(symbol, start, end, adjusted=False):
        seen.append(adjusted)
        return _frame(TODAY).rename(columns=str)

    monkeypatch.setattr(chart_data.massive_client, "get_daily_bars", fake)
    asyncio.run(chart_data._fetch_bars("AAPL", "D_1Y"))
    assert seen == [True]


def test_delisted_probe_requests_split_adjusted(monkeypatch):
    monkeypatch.setattr(health_check.settings, "massive_enabled", True)
    seen = []

    async def fake(symbol, start, end, adjusted=False):
        seen.append(adjusted)
        return _frame(date.today())

    monkeypatch.setattr(health_check.massive_client, "get_daily_bars", fake)
    asyncio.run(health_check._probe_ticker_for_fresh_bar("AAPL", date.today(), 30))
    assert seen == [True]
