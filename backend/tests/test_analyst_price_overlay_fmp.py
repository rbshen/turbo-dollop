"""Analyst Ratings price overlay on FMP: the long-history store's split-only closes; nothing else
(Yahoo was removed in Phase 6b, so no store row means an empty overlay)."""

import asyncio
import json
from datetime import date, datetime

import pandas as pd
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


def _run(ticker="KO"):
    return asyncio.run(ard._fetch_price_history(ticker))


def test_overlay_is_the_stores_split_only_close():
    _seed("KO", {date(2016, 6, 1): 60.0, date(2016, 6, 2): 61.0, date(2016, 6, 3): 61.5})
    series = _run()
    assert series.loc[pd.Timestamp("2016-06-01")] == 60.0  # split-only close
    assert series.index.is_monotonic_increasing and series.index.tz is None


def test_price_on_date_alignment_uses_the_last_close_on_or_before():
    _seed("KO", {date(2016, 6, 1): 60.0, date(2016, 6, 2): 61.0, date(2016, 6, 6): 62.0})
    series = _run()
    assert ard._price_on_or_before(series, pd.Timestamp("2016-06-02")) == 61.0
    assert ard._price_on_or_before(series, pd.Timestamp("2016-06-04")) == 61.0  # weekend -> Friday
    assert ard._price_on_or_before(series, pd.Timestamp("2016-05-31")) is None  # before the first bar: never extrapolated


def test_group_off_serves_the_stored_row_without_a_fetch():
    _seed("KO", {date(2016, 6, 1): 60.0})
    dg.set_group_enabled("daily_prices_long", False)
    assert _run().loc[pd.Timestamp("2016-06-01")] == 60.0


def test_group_off_with_no_stored_row_is_an_empty_overlay_not_an_error():
    dg.set_group_enabled("daily_prices_long", False)
    assert _run().empty


def test_a_failing_store_is_an_empty_overlay_not_an_error(monkeypatch):
    async def boom(_ticker):
        raise RuntimeError("store exploded")

    monkeypatch.setattr(ard, "get_long_history", boom)
    assert _run().empty


def test_the_yahoo_path_is_gone():
    assert not hasattr(ard, "yahoo_client") and not hasattr(ard, "PRICE_OVERLAY_FETCH_PERIOD")
