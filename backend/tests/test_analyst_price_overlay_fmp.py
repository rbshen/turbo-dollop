"""Analyst Ratings price overlay on FMP (P3.7): the long-history store's split-only closes,
Yahoo `Adj Close` only as the fall-through."""

import asyncio
import json
from datetime import date, datetime

import pandas as pd
import pytest
from sqlmodel import Session

import clients.long_history_bars as lhb
import core.data_groups as dg
import data.analyst_ratings_data as ard
from core.models import FundamentalsCache, LongHistoryBars


def _seed(ticker: str, closes: dict[date, float], fetched_at=None) -> None:
    fetched_at = fetched_at or datetime.now()
    with Session(lhb.engine) as session:
        for d, c in closes.items():
            session.add(LongHistoryBars(ticker=ticker, bar_time=datetime.combine(d, datetime.min.time()), open=c, high=c, low=c, close=c, volume=1, fetched_at=fetched_at))
        session.commit()


def _profile(ticker: str, exchange: str) -> None:
    with Session(lhb.engine) as session:
        session.add(FundamentalsCache(ticker=ticker, statement_type="profile", period="latest", raw_json=json.dumps([{"exchange": exchange}]), fetched_at=datetime.now()))
        session.commit()


class _Yahoo:
    """Yahoo stand-in: close 60.0 but the dividend-adjusted `Adj Close` 40.0 (the KO-2016 shape)."""

    def __init__(self, frame=None):
        self.calls = 0
        self.frame = frame

    async def get_history(self, tickers, period="2y", interval="1d", auto_adjust=True):
        self.calls += 1
        if self.frame is None:
            return {}
        return {t: self.frame for t in tickers}


def _yahoo_frame():
    idx = pd.DatetimeIndex([pd.Timestamp("2016-06-01"), pd.Timestamp("2016-06-02")], tz="America/New_York")
    return pd.DataFrame({"Close": [60.0, 61.0], "Adj Close": [40.0, 41.0]}, index=idx)


def _run(ticker="KO"):
    return asyncio.run(ard._fetch_price_history(ticker))


def test_overlay_is_the_stores_split_only_close_and_yahoo_is_never_asked(monkeypatch):
    y = _Yahoo(_yahoo_frame())
    monkeypatch.setattr(ard, "yahoo_client", y)
    _seed("KO", {date(2016, 6, 1): 60.0, date(2016, 6, 2): 61.0, date(2016, 6, 3): 61.5})
    series = _run()
    assert y.calls == 0
    assert series.loc[pd.Timestamp("2016-06-01")] == 60.0  # split-only close, not the 40.0 Adj Close
    assert series.index.is_monotonic_increasing and series.index.tz is None


def test_basis_is_pinned_to_split_only_not_the_yahoo_adjusted_close(monkeypatch):
    """The same day on both paths: FMP path says 60.0, the Yahoo fall-through says 40.0."""
    monkeypatch.setattr(ard, "yahoo_client", _Yahoo(_yahoo_frame()))
    dg.set_group_enabled("daily_prices_long", False)  # no row -> Yahoo fall-through
    fallback = _run()
    assert fallback.loc[pd.Timestamp("2016-06-01")] == 40.0
    _seed("KO", {date(2016, 6, 1): 60.0})
    dg.set_group_enabled("daily_prices_long", True)
    assert _run().loc[pd.Timestamp("2016-06-01")] == 60.0


def test_price_on_date_alignment_uses_the_last_close_on_or_before(monkeypatch):
    monkeypatch.setattr(ard, "yahoo_client", _Yahoo())
    _seed("KO", {date(2016, 6, 1): 60.0, date(2016, 6, 2): 61.0, date(2016, 6, 6): 62.0})
    series = _run()
    assert ard._price_on_or_before(series, pd.Timestamp("2016-06-02")) == 61.0
    assert ard._price_on_or_before(series, pd.Timestamp("2016-06-04")) == 61.0  # weekend -> Friday
    assert ard._price_on_or_before(series, pd.Timestamp("2016-05-31")) is None  # before the first bar: never extrapolated


def test_group_off_serves_the_stored_row_without_a_fetch(monkeypatch):
    monkeypatch.setattr(ard, "yahoo_client", _Yahoo())
    _seed("KO", {date(2016, 6, 1): 60.0})
    dg.set_group_enabled("daily_prices_long", False)
    assert _run().loc[pd.Timestamp("2016-06-01")] == 60.0


def test_off_or_failed_with_nothing_anywhere_is_an_empty_overlay_not_an_error(monkeypatch):
    monkeypatch.setattr(ard, "yahoo_client", _Yahoo())  # Yahoo has nothing either
    dg.set_group_enabled("daily_prices_long", False)
    assert _run().empty

    async def boom(_ticker):
        raise RuntimeError("store exploded")

    dg.set_group_enabled("daily_prices_long", True)
    monkeypatch.setattr(ard, "get_long_history", boom)
    assert _run().empty  # falls through to Yahoo, which has nothing


def test_a_failing_store_falls_back_to_yahoo(monkeypatch):
    async def boom(_ticker):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(ard, "get_long_history", boom)
    monkeypatch.setattr(ard, "yahoo_client", _Yahoo(_yahoo_frame()))
    assert _run().loc[pd.Timestamp("2016-06-01")] == 40.0


def test_hk_ticker_overlay_works_through_the_intl_group(monkeypatch):
    monkeypatch.setattr(ard, "yahoo_client", _Yahoo())
    _profile("0005.HK", "HKSE")
    _seed("0005.HK", {date(2024, 1, 2): 60.5, date(2024, 1, 3): 61.0})
    assert _run("0005.HK").loc[pd.Timestamp("2024-01-03")] == 61.0
    dg.set_group_enabled("daily_prices_long", False)  # the US long group is irrelevant for HK
    assert not _run("0005.HK").empty
    dg.set_group_enabled("daily_prices_intl", False)  # the intl group off: stored row still served
    assert not _run("0005.HK").empty
