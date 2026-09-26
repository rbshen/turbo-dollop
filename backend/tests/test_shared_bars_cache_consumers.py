"""End-to-end coverage of the overlap the shared bars cache exists to
remove: the REAL cache (in-memory DB) with only the FMP bar sources faked, driven
through each consumer's actual read entry point -- BB+RSI via
clients/technical_sources.py, Warren/Trend/Liquidity Zones via the same
get_or_fetch_bars_batch call their nightly jobs make (with each job's own
lookback constant). Asserts on how many live fetches happen, in
either job order, on the first night and in steady state."""

import asyncio
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import SQLModel, create_engine

import clients.shared_bars_cache as cache
from clients.shared_bars_cache import DAILY_INTERVAL, INTRADAY_INTERVAL, get_or_fetch_bars_batch
from clients.technical_sources import FMPTechnicalSource
from data.liquidity_zone_data import LOOKBACK_DAYS as LZ_LOOKBACK_DAYS
from data.trend_analysis_data import WEINSTEIN_LOOKBACK_DAYS as TREND_LOOKBACK_DAYS  # the trend job now fetches the Weinstein ~5y window
from pipeline.nightly_entry_signal_calculation import LOOKBACK_DAYS as BBRSI_LOOKBACK_DAYS
from pipeline.nightly_warren_signal_calculation import LOOKBACK_DAYS as WARREN_LOOKBACK_DAYS


_PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825, "10y": 3650}
_SESSION_STARTS = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]


class FakeBars:
    """A stand-in for the FMP bar sources (get_daily_bar_source / FMPIntradaySource) whose data
    "ends" at whatever the test's current pinned session is, and which records every call. Like
    the batch downloads it replaces, tickers are grouped by the width tier their own need snaps to
    (one recorded call per tier), so assertions read as "who was fetched at what width"."""

    def __init__(self):
        self.calls: list[dict] = []
        self.last_trading_date: date = date(2026, 9, 17)  # Thursday
        self.last_bar: datetime = datetime(2026, 9, 17, 15, 30)

    async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, unserved_tickers=None, replace_tickers=None, full_refresh=False):
        return self._serve(DAILY_INTERVAL, tickers_with_days, auto_adjust)

    async def get_intraday_bars(self, tickers_with_days, reference=None, replace_tickers=None, full_refresh=False, unserved_tickers=None):
        return self._serve(INTRADAY_INTERVAL, tickers_with_days, None)

    def _serve(self, interval, tickers_with_days, auto_adjust):
        by_period: dict[str, list[str]] = {}
        for ticker, need in tickers_with_days.items():
            by_period.setdefault(cache._period_for(interval, need), []).append(ticker)
        out: dict[str, pd.DataFrame] = {}
        for period, group in by_period.items():
            self.calls.append({"tickers": list(group), "period": period, "interval": interval, "auto_adjust": auto_adjust})
            frame = self._frame(period, interval)
            out.update({t: frame.copy() for t in group})
        return out

    def _frame(self, period, interval):
        days = _PERIOD_DAYS[period]
        if interval == DAILY_INTERVAL:
            # A "5y" width starts at today minus five CALENDAR years (1826-1827 days), a hair
            # wider than the tier's nominal 1825 -- the Trend job asks for exactly that nominal
            # width, so a fake that produced exactly 1825 would put the first bar right on the
            # strict coverage boundary and re-fetch on weekend-aligned dates.
            dates = [self.last_trading_date - timedelta(days=d) for d in range(days + 2)]
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
        return pd.DataFrame(
            {"open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n, "close": [100.5] * n, "volume": [1000] * n}, index=index
        )

    def advance_one_session(self):
        """Simulate the next trading day having completed (Thursday ->
        Friday) -- both what "most recently completed" resolves to and what
        the provider now has."""
        self.last_trading_date += timedelta(days=1)
        self.last_bar = datetime(self.last_trading_date.year, self.last_trading_date.month, self.last_trading_date.day, 15, 30)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cache, "engine", engine)
    fake = FakeBars()
    monkeypatch.setattr(cache, "get_daily_bar_source", lambda: fake)
    monkeypatch.setattr(cache, "FMPIntradaySource", lambda: fake)
    # Pin "most recently completed session/bar" and "today" to the fake's
    # own pinned session, so these tests never depend on the wall clock.
    monkeypatch.setattr(cache, "_most_recent_completed_trading_date", lambda reference=None: fake.last_trading_date)
    monkeypatch.setattr(cache, "_most_recent_completed_intraday_bar_start", lambda reference=None: fake.last_bar)
    monkeypatch.setattr(cache, "_eastern_today", lambda reference=None: fake.last_trading_date)
    return fake


def _warren(tickers):
    return asyncio.run(get_or_fetch_bars_batch(tickers, INTRADAY_INTERVAL, WARREN_LOOKBACK_DAYS, auto_adjust=False))


def _bbrsi(tickers):
    return asyncio.run(FMPTechnicalSource().get_intraday_bars(tickers, BBRSI_LOOKBACK_DAYS))


def _trend(tickers):
    return asyncio.run(get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, TREND_LOOKBACK_DAYS, auto_adjust=False))


def _lz(tickers):
    return asyncio.run(get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, LZ_LOOKBACK_DAYS, auto_adjust=False))


def test_lookback_constants_are_the_widths_the_design_assumes():
    assert WARREN_LOOKBACK_DAYS == 730
    assert BBRSI_LOOKBACK_DAYS == 60
    assert TREND_LOOKBACK_DAYS == 5 * 365
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


def test_trend_first_then_lz_reads_the_same_5y_row_for_free(env):
    _trend(["AAPL"])  # 3:10 -- Trend now asks for the Weinstein ~5y window
    _lz(["AAPL"])  # 3:25 -- LZ's 4y need is already covered
    assert [c["period"] for c in env.calls] == ["5y"]
    env.calls.clear()

    env.advance_one_session()
    _trend(["AAPL"])  # first job of the night refetches, at the preserved 5y width
    _lz(["AAPL"])  # reads it back for free

    assert len(env.calls) == 1
    assert env.calls[0]["period"] == "5y"


def test_a_universe_fetch_is_one_5y_call_for_every_ticker(env):
    """Trend now fetches the whole universe at the Weinstein ~5y width (LZ's
    4y need snaps to the same tier), so a run is one 5y call for everyone --
    no per-ticker 2y/5y split any more -- and LZ then reads it all back."""
    universe = ["AAPL", "MSFT", "GOOG", "ONLYTREND1", "ONLYTREND2"]
    lz_tickers = ["AAPL", "MSFT"]
    _trend(universe)
    _lz(lz_tickers)
    assert [c["period"] for c in env.calls] == ["5y"]
    env.calls.clear()

    env.advance_one_session()
    _trend(universe)

    assert {c["period"]: sorted(c["tickers"]) for c in env.calls} == {"5y": sorted(universe)}
    _lz(lz_tickers)
    assert len(env.calls) == 1  # LZ read everything back for free


def test_daily_and_intraday_rows_for_the_same_ticker_never_interfere(env):
    _trend(["AAPL"])
    _warren(["AAPL"])

    assert {c["interval"] for c in env.calls} == {"1d", "60m"}
    env.calls.clear()
    _trend(["AAPL"])
    _warren(["AAPL"])
    assert env.calls == []
