"""Chart W_4Y on FMP (P3.6): weekly bars = the long-history daily store resampled with the
existing resample_to_weekly. The parity fixture is REAL: FMP /historical-price-eod/full dailies
and Yahoo native interval="1wk" bars for AAPL/KO/SPY, 2025-06-02..2026-09-18 (captured
2026-09-25, complete weeks only)."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlmodel import Session

import clients.long_history_bars as lhb
import core.data_groups as dg
import data.chart_data as chart_data
from analysis.trend_structure.weinstein import resample_to_weekly
from core.models import FundamentalsCache, LongHistoryBars
from data.chart_events_data import ChartEvents

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "weekly_parity_fmp_daily_vs_yahoo_1wk.json").read_text())
COLS = ["open", "high", "low", "close", "volume"]


@pytest.fixture(autouse=True)
def _quiet_chart_side_channels(monkeypatch):
    async def none_events(ticker):
        return ChartEvents()

    async def none_signal(ticker):
        return None

    monkeypatch.setattr(chart_data, "fetch_chart_events", none_events)
    monkeypatch.setattr(chart_data, "get_warren_signal_data", none_signal)


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["date", *COLS])
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def _seed(ticker: str, daily: pd.DataFrame, fetched_at=None) -> None:
    fetched_at = fetched_at or datetime.now()
    with Session(lhb.engine) as session:
        for ts, r in daily.iterrows():
            session.add(LongHistoryBars(ticker=ticker, bar_time=ts.to_pydatetime(), open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close), volume=int(r.volume), fetched_at=fetched_at))
        session.commit()


def _seed_profile(ticker: str, exchange: str) -> None:
    with Session(lhb.engine) as session:
        session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", raw_json=json.dumps([{"exchange": exchange}]), fetched_at=datetime.now()))
        session.commit()


@pytest.mark.parametrize("ticker", ["AAPL", "KO", "SPY"])
def test_resampled_fmp_dailies_match_yahoos_native_weekly_bars(ticker):
    daily = _frame(FIXTURE[ticker]["fmp_daily"])
    yahoo = _frame(FIXTURE[ticker]["yahoo_weekly"])
    ours = resample_to_weekly(daily)
    assert list(ours.index) == list(yahoo.index)  # identical Monday labels, week for week
    for col in ("open", "high", "low", "close"):
        rel = (ours[col] / yahoo[col] - 1).abs()
        assert (rel <= 0.005).mean() >= 0.98, (ticker, col, rel.max())
    assert ((ours["close"] / yahoo["close"] - 1).abs() <= 0.005).all()
    assert ((ours["volume"] / yahoo["volume"] - 1).abs() <= 0.005).mean() >= 0.90  # vendor volume prints differ slightly


@pytest.mark.parametrize("ticker", ["AAPL", "KO", "SPY"])
def test_fetch_bars_serves_w4y_from_the_long_history_store_as_fmp(ticker):
    daily = _frame(FIXTURE[ticker]["fmp_daily"])
    _seed(ticker, daily)
    bars, source = asyncio.run(chart_data._fetch_bars(ticker, "W_4Y"))
    assert source == "fmp"
    yahoo = _frame(FIXTURE[ticker]["yahoo_weekly"])
    assert list(bars.index[: len(yahoo)]) == list(yahoo.index)
    assert list(bars.columns) == COLS


def test_the_in_progress_week_is_a_partial_bar_labelled_by_its_monday():
    daily = _frame(FIXTURE["KO"]["fmp_daily"])
    monday = pd.Timestamp("2026-09-14")
    partial = daily[daily.index <= monday + pd.Timedelta(days=2)]  # through Wednesday
    _seed("KO", partial)
    bars, source = asyncio.run(chart_data._fetch_bars("KO", "W_4Y"))
    last = bars.iloc[-1]
    wk = partial[partial.index >= monday]
    assert bars.index[-1] == monday and source == "fmp"
    assert last.open == wk.open.iloc[0] and last.close == wk.close.iloc[-1] and last.high == wk.high.max() and last.volume == wk.volume.sum()
    assert len(wk) == 3


def test_hk_ticker_weekly_view_uses_the_intl_group():
    _seed_profile("0005.HK", "HKSE")
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=400)
    daily = pd.DataFrame({"open": 80.0, "high": 81.0, "low": 79.0, "close": [80.0 + (i % 7) for i in range(400)], "volume": 5000}, index=idx)
    _seed("0005.HK", daily)
    bars, source = asyncio.run(chart_data._fetch_bars("0005.HK", "W_4Y"))
    assert source == "fmp" and not bars.empty
    # intl OFF still serves the stored row (cached-only) ...
    dg.set_group_enabled("daily_prices_intl", False)
    _, source = asyncio.run(chart_data._fetch_bars("0005.HK", "W_4Y"))
    assert source == "fmp"


def test_group_off_without_a_row_falls_through_to_yahoo_weekly(monkeypatch):
    dg.set_group_enabled("daily_prices_long", False)
    idx = pd.date_range("2024-01-01", periods=30, freq="W-MON")
    yahoo_weekly = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5, "Volume": 10}, index=idx)

    async def fake_history(tickers, period="2y", interval="1d", auto_adjust=True):
        assert interval == "1wk"
        return {t: yahoo_weekly for t in tickers}

    monkeypatch.setattr(chart_data.yahoo_client, "get_history", fake_history)
    bars, source = asyncio.run(chart_data._fetch_bars("KO", "W_4Y"))
    assert source == "yahoo" and len(bars) == 30


def test_a_long_history_read_error_degrades_to_yahoo_instead_of_failing(monkeypatch):
    async def boom(ticker):
        raise RuntimeError("db exploded")

    async def fake_history(tickers, period="2y", interval="1d", auto_adjust=True):
        return {}

    monkeypatch.setattr(chart_data, "get_long_history", boom)
    monkeypatch.setattr(chart_data.yahoo_client, "get_history", fake_history)
    bars, source = asyncio.run(chart_data._fetch_bars("KO", "W_4Y"))
    assert source == "yahoo" and bars.empty


def test_get_chart_data_w4y_reports_fmp_as_the_source():
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=2200)
    daily = pd.DataFrame({"open": 50.0, "high": 51.0, "low": 49.0, "close": [50.0 + (i % 11) * 0.3 for i in range(2200)], "volume": 1000}, index=idx)
    _seed("KO", daily)
    out = asyncio.run(chart_data.get_chart_data("KO", "W_4Y"))
    assert out.source == "fmp" and out.chart_available and out.bars
