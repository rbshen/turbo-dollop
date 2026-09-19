"""End-to-end coverage of the overlap the shared bars cache exists to
remove: the REAL cache (in-memory DB) with only yahoo_client faked, driven
through each consumer's actual read entry point -- BB+RSI via
clients/technical_sources.py, Warren/Trend/Liquidity Zones via the same
get_or_fetch_bars_batch call their nightly jobs make (with each job's own
lookback constant). Asserts on how many live Yahoo fetches happen, in
either job order, on the first night and in steady state."""

import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import SQLModel, create_engine

import clients.shared_bars_cache as cache
from clients.shared_bars_cache import DAILY_INTERVAL, INTRADAY_INTERVAL, get_or_fetch_bars_batch
from clients.technical_sources import YahooTechnicalSource
from data.liquidity_zone_data import LOOKBACK_DAYS as LZ_LOOKBACK_DAYS
from data.trend_analysis_data import LOOKBACK_DAYS as TREND_LOOKBACK_DAYS
from pipeline.nightly_entry_signal_calculation import LOOKBACK_DAYS as BBRSI_LOOKBACK_DAYS
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS as WARREN_LOOKBACK_DAYS

_PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825, "10y": 3650}
_SESSION_STARTS = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]


class FakeYahoo:
    """A stand-in for yahoo_client.get_history whose data "ends" at whatever
    the test's current pinned session is, and which records every call."""

    def __init__(self):
        self.calls: list[dict] = []
        self.last_trading_date: date = date(2026, 9, 17)  # Thursday
        self.last_bar: datetime = datetime(2026, 9, 17, 15, 30)

    async def get_history(self, tickers, period="2y", interval="1d", auto_adjust=True):
        self.calls.append({"tickers": list(tickers), "period": period, "interval": interval, "auto_adjust": auto_adjust})
        days = _PERIOD_DAYS[period]
        if interval == DAILY_INTERVAL:
            dates = [self.last_trading_date - timedelta(days=d) for d in range(days)]
            index = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in dates if d.weekday() < 5))
        else:
            stamps = []
            for d in range(days):
                day = self.last_bar.date() - timedelta(days=d)
                if day.weekday() >= 5:
                    continue
                for h, m in _SESSION_STARTS:
                    ts = datetime(day.year, day.month, day.day, h, m)
                    if ts <= self.last_bar:
                        stamps.append(pd.Timestamp(ts, tz="America/New_York"))
            index = pd.DatetimeIndex(sorted(stamps))
        n = len(index)
        frame = pd.DataFrame(
            {"Open": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n, "Close": [100.5] * n, "Volume": [1000] * n}, index=index
        )
        return {t: frame.copy() for t in tickers}

    def advance_one_session(self):
        """Simulate the next trading day having completed (Thursday ->
        Friday) -- both what "most recently completed" resolves to and what
        Yahoo now has."""
        self.last_trading_date += timedelta(days=1)
        self.last_bar = datetime(self.last_trading_date.year, self.last_trading_date.month, self.last_trading_date.day, 15, 30)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cache, "engine", engine)
    fake = FakeYahoo()
    monkeypatch.setattr(cache.yahoo_client, "get_history", fake.get_history)
    # Pin "most recently completed session/bar" and "today" to the fake's
    # own pinned session, so these tests never depend on the wall clock.
    monkeypatch.setattr(cache, "_most_recent_completed_trading_date", lambda reference=None: fake.last_trading_date)
    monkeypatch.setattr(cache, "_most_recent_completed_intraday_bar_start", lambda reference=None: fake.last_bar)
    monkeypatch.setattr(cache, "_eastern_today", lambda reference=None: fake.last_trading_date)
    return fake


def _warren(tickers):
    return asyncio.run(get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, WARREN_LOOKBACK_DAYS, auto_adjust=False))


def _bbrsi(tickers):
    return asyncio.run(YahooTechnicalSource().get_intraday_bars(tickers, BBRSI_LOOKBACK_DAYS))


def _trend(tickers):
    return asyncio.run(get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, TREND_LOOKBACK_DAYS, auto_adjust=False))


def _lz(tickers):
    return asyncio.run(get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, LZ_LOOKBACK_DAYS, auto_adjust=False))


def test_lookback_constants_are_the_widths_the_design_assumes():
    assert WARREN_LOOKBACK_DAYS == 730
    assert BBRSI_LOOKBACK_DAYS == 60
    assert TREND_LOOKBACK_DAYS == 730
    assert LZ_LOOKBACK_DAYS >= 4 * 365


def test_bbrsi_reads_the_row_warren_already_fetched_with_zero_live_calls(env):
    _warren(["AAPL"])
    assert len(env.calls) == 1
    assert env.calls[0]["interval"] == "60m" and env.calls[0]["period"] == "2y"

    bbrsi = _bbrsi(["AAPL"])

    assert len(env.calls) == 1  # BB+RSI did NOT fetch its own
    frame = bbrsi["AAPL"]
    assert str(frame.index.tz) == "America/New_York"  # what build_2h_session_candles needs
    assert (frame.index.max().date() - frame.index.min().date()).days <= BBRSI_LOOKBACK_DAYS  # sliced to its own 60d
    assert all(c["auto_adjust"] is False for c in env.calls)


def test_warren_widens_a_row_bbrsi_created_first_then_bbrsi_reuses_it(env):
    """Current cron order (BB+RSI 3:20, Warren 3:40): first ever night, BB+RSI
    creates a 60d row, Warren must widen it to 2y -- 2 fetches total that
    night, and never a third."""
    _bbrsi(["AAPL"])
    assert [c["period"] for c in env.calls] == ["3mo"]

    _warren(["AAPL"])
    assert [c["period"] for c in env.calls] == ["3mo", "2y"]

    _bbrsi(["AAPL"])
    assert len(env.calls) == 2  # widened row now serves the narrow reader for free


def test_steady_state_night_costs_exactly_one_intraday_fetch_per_ticker_in_the_real_cron_order(env):
    _bbrsi(["AAPL"])
    _warren(["AAPL"])  # night 1 warm-up: row is now 2y wide
    env.calls.clear()

    env.advance_one_session()  # night 2: yesterday's session has closed, both rows are now behind
    _bbrsi(["AAPL"])  # 3:20 -- finds the row stale, refetches
    _warren(["AAPL"])  # 3:40 -- reads what BB+RSI just refreshed

    assert len(env.calls) == 1
    assert env.calls[0]["period"] == "2y"  # BB+RSI's refetch PRESERVED Warren's width, not its own 60d
    frame = _warren(["AAPL"])["AAPL"]
    assert frame.index.max().to_pydatetime().replace(tzinfo=None) == env.last_bar  # and it contains the new session


def test_steady_state_night_is_still_one_fetch_if_warren_runs_first(env):
    _warren(["AAPL"])
    env.calls.clear()

    env.advance_one_session()
    _warren(["AAPL"])
    _bbrsi(["AAPL"])

    assert len(env.calls) == 1


def test_a_row_is_not_refetched_by_either_job_when_no_new_session_has_completed(env):
    _warren(["AAPL"])
    env.calls.clear()

    _bbrsi(["AAPL"])
    _warren(["AAPL"])
    _bbrsi(["AAPL"])

    assert env.calls == []  # same session: overnight/weekend re-runs are free, not falsely stale


def test_trend_and_liquidity_zones_share_one_daily_row_lz_first(env):
    _lz(["AAPL"])
    assert env.calls[0]["period"] == "5y"
    _trend(["AAPL"])
    assert len(env.calls) == 1


def test_trend_first_then_lz_widens_once_then_steady_state_is_one_fetch(env):
    _trend(["AAPL"])  # 3:10 -- creates a 2y row
    _lz(["AAPL"])  # 3:25 -- widens it to 5y
    assert [c["period"] for c in env.calls] == ["2y", "5y"]
    env.calls.clear()

    env.advance_one_session()
    _trend(["AAPL"])  # first job of the night refetches, PRESERVING the 5y width
    _lz(["AAPL"])  # reads it back for free

    assert len(env.calls) == 1
    assert env.calls[0]["period"] == "5y"


def test_a_universe_only_widens_the_tickers_that_actually_need_it(env):
    """Trend fetches the whole universe; only tickers that are ALSO
    Liquidity Zone tickers ever get widened to 5y. After that, a Trend run
    over the full universe must re-download the wide tickers at 5y and the
    rest at 2y -- NOT everything at 5y."""
    universe = ["AAPL", "MSFT", "GOOG", "ONLYTREND1", "ONLYTREND2"]
    lz_tickers = ["AAPL", "MSFT"]
    _trend(universe)
    _lz(lz_tickers)
    env.calls.clear()

    env.advance_one_session()
    _trend(universe)

    periods = {c["period"]: sorted(c["tickers"]) for c in env.calls}
    assert periods == {"5y": ["AAPL", "MSFT"], "2y": ["GOOG", "ONLYTREND1", "ONLYTREND2"]}
    _lz(lz_tickers)
    assert len(env.calls) == 2  # LZ then read everything back for free


def test_daily_and_intraday_rows_for_the_same_ticker_never_interfere(env):
    _trend(["AAPL"])
    _warren(["AAPL"])

    assert {c["interval"] for c in env.calls} == {"1d", "60m"}
    env.calls.clear()
    _trend(["AAPL"])
    _warren(["AAPL"])
    assert env.calls == []
