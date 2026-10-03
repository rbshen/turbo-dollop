"""Holiday- and early-close-aware "most recently completed 60m bar" (clients/shared_bars_cache.py::
_most_recent_completed_intraday_bar_start) and the 60m stale count built on it. The calendar is
pandas_market_calendars' XNYS (lazily imported, schedule lookup in helpers/trading_calendar.py)."""

import asyncio
import logging
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_bar_sources as dbs
import clients.shared_bars_cache as cache
from core.models import FundamentalsCache, SharedBarsCache

ET = ZoneInfo("America/New_York")


def _et(text: str) -> datetime:
    return pd.Timestamp(text, tz=ET).to_pydatetime()


# ---- (a) replay of the real nightly schedule against an independent oracle ----

def test_replaying_every_nightly_0120_utc_run_since_2024_09_20_is_never_wrong():
    """The old weekday-only logic was wrong on 40 of these 743 nights (after each half-day and on each holiday)."""
    import pandas_market_calendars as mcal

    schedule = mcal.get_calendar("XNYS").schedule(start_date="2024-09-01", end_date="2026-10-05")
    closes = schedule["market_close"].dt.tz_convert(ET)
    sessions = [d.date() for d in schedule.index]
    early = {d.date() for d, c in closes.items() if c.hour < 16}

    def oracle(ref: datetime) -> datetime:
        day = max(s for s in sessions if s <= ref.astimezone(ET).date())  # the cron runs hours after the close
        return datetime(day.year, day.month, day.day, 12 if day in early else 15, 30)

    wrong, day = [], date(2024, 9, 20)
    while day <= date(2026, 10, 2):
        ref = datetime(day.year, day.month, day.day, 1, 20, tzinfo=timezone.utc)
        if cache._most_recent_completed_intraday_bar_start(ref) != oracle(ref):
            wrong.append(day)
        day += timedelta(days=1)
    assert wrong == []
    assert len(early) == 5  # 2024-11-29, 2024-12-24, 2025-07-03, 2025-11-28, 2025-12-24: the oracle did see half-days


# ---- (b) holidays and half-days, (c) weekends and pre-open, (d) mid-session ----

@pytest.mark.parametrize(
    "reference_et, expected",
    [
        # Labor Day 2026 (Mon 09-07): the holiday itself, day and night -> Friday's last bar
        ("2026-09-07 12:00", datetime(2026, 9, 4, 15, 30)),
        ("2026-09-07 21:20", datetime(2026, 9, 4, 15, 30)),
        ("2026-09-08 08:00", datetime(2026, 9, 4, 15, 30)),
        ("2026-09-08 10:30", datetime(2026, 9, 8, 9, 30)),
        # Thanksgiving week 2025: Thu 11-27 closed, Fri 11-28 closes at 13:00
        ("2025-11-26 21:20", datetime(2025, 11, 26, 15, 30)),
        ("2025-11-27 21:20", datetime(2025, 11, 26, 15, 30)),
        ("2025-11-28 09:00", datetime(2025, 11, 26, 15, 30)),
        ("2025-11-28 14:00", datetime(2025, 11, 28, 12, 30)),  # the day after Thanksgiving, after the early close
        ("2025-11-28 21:20", datetime(2025, 11, 28, 12, 30)),
        ("2025-11-29 21:20", datetime(2025, 11, 28, 12, 30)),  # Saturday
        ("2025-11-30 21:20", datetime(2025, 11, 28, 12, 30)),  # Sunday
        ("2025-12-01 08:00", datetime(2025, 11, 28, 12, 30)),
        ("2025-12-01 21:20", datetime(2025, 12, 1, 15, 30)),
        # Dec 24 2025 (Wed) half-day; Jul 3 2025 (Thu) half-day; Jul 3 2026 (Fri) is the observed Independence Day
        ("2025-12-24 21:20", datetime(2025, 12, 24, 12, 30)),
        ("2025-12-25 21:20", datetime(2025, 12, 24, 12, 30)),
        ("2025-07-03 21:20", datetime(2025, 7, 3, 12, 30)),
        ("2026-07-03 21:20", datetime(2026, 7, 2, 15, 30)),
        # Good Friday 2026-04-03
        ("2026-04-03 21:20", datetime(2026, 4, 2, 15, 30)),
    ],
)
def test_holidays_and_early_closes(reference_et, expected):
    assert cache._most_recent_completed_intraday_bar_start(_et(reference_et)) == expected


@pytest.mark.parametrize(
    "reference_et, expected",
    [
        ("2026-09-19 15:00", datetime(2026, 9, 18, 15, 30)),  # Saturday
        ("2026-09-20 23:59", datetime(2026, 9, 18, 15, 30)),  # Sunday
        ("2026-09-21 04:30", datetime(2026, 9, 18, 15, 30)),  # Monday, pre-open
        ("2026-09-21 09:29:59", datetime(2026, 9, 18, 15, 30)),
        ("2026-09-21 09:45", datetime(2026, 9, 18, 15, 30)),  # open, but the 09:30 bar is not complete
        ("2026-09-21 10:29:59", datetime(2026, 9, 18, 15, 30)),
    ],
)
def test_weekend_and_pre_open_fall_back_to_the_previous_sessions_last_bar(reference_et, expected):
    assert cache._most_recent_completed_intraday_bar_start(_et(reference_et)) == expected


@pytest.mark.parametrize(
    "reference_et, expected",
    [
        # normal day: bars 09:30..15:30, the 15:30 one only 30 minutes long
        ("2026-09-17 10:30", datetime(2026, 9, 17, 9, 30)),
        ("2026-09-17 12:45", datetime(2026, 9, 17, 11, 30)),
        ("2026-09-17 15:29:59", datetime(2026, 9, 17, 13, 30)),
        ("2026-09-17 15:30", datetime(2026, 9, 17, 14, 30)),
        ("2026-09-17 15:59:59", datetime(2026, 9, 17, 14, 30)),  # the final 30-minute bar is not done until 16:00
        ("2026-09-17 16:00", datetime(2026, 9, 17, 15, 30)),
        ("2026-09-17 23:00", datetime(2026, 9, 17, 15, 30)),
        # half-day 2025-11-28: bars 09:30, 10:30, 11:30 and a 30-minute 12:30 one
        ("2025-11-28 10:30", datetime(2025, 11, 28, 9, 30)),
        ("2025-11-28 12:45", datetime(2025, 11, 28, 11, 30)),
        ("2025-11-28 12:59:59", datetime(2025, 11, 28, 11, 30)),
        ("2025-11-28 13:00", datetime(2025, 11, 28, 12, 30)),
    ],
)
def test_mid_session_returns_the_last_fully_elapsed_slot_using_the_real_close(reference_et, expected):
    assert cache._most_recent_completed_intraday_bar_start(_et(reference_et)) == expected


def test_a_naive_reference_is_read_as_utc_like_before():
    assert cache._most_recent_completed_intraday_bar_start(datetime(2026, 9, 8, 1, 20)) == datetime(2026, 9, 4, 15, 30)


# ---- (e) fallback ----

@pytest.fixture
def _fresh_flag(monkeypatch):
    monkeypatch.setattr(cache, "_calendar_fallback_logged", False)


def _boom(*_a, **_k):
    raise RuntimeError("calendar broke")


def test_a_calendar_lookup_error_logs_once_and_behaves_like_the_old_logic(monkeypatch, caplog, _fresh_flag):
    import helpers.trading_calendar as tc

    monkeypatch.setattr(tc, "xnys_sessions", _boom)
    refs = [_et("2025-11-28 21:20"), _et("2026-09-08 01:20"), _et("2026-09-17 12:45")]
    with caplog.at_level(logging.WARNING, logger=cache.logger.name):
        got = [cache._most_recent_completed_intraday_bar_start(r) for r in refs] + [
            cache._most_recent_completed_intraday_bar_start(r) for r in refs
        ]
    assert got[:3] == [cache._weekday_only_intraday_bar_start(r) for r in refs]
    assert got[:3] == got[3:]
    assert got[0] == datetime(2025, 11, 28, 15, 30)  # the old, holiday-blind answer (the real last bar was 12:30)
    assert [r for r in caplog.records if "XNYS calendar unavailable" in r.getMessage()].__len__() == 1


def test_an_import_failure_also_falls_back_and_never_raises(monkeypatch, caplog, _fresh_flag):
    monkeypatch.setitem(sys.modules, "helpers.trading_calendar", None)  # `from helpers.trading_calendar import ...` -> ImportError
    ref = _et("2026-09-17 12:45")
    with caplog.at_level(logging.WARNING, logger=cache.logger.name):
        assert cache._most_recent_completed_intraday_bar_start(ref) == datetime(2026, 9, 17, 11, 30)
        assert cache._most_recent_completed_intraday_bar_start(ref) == datetime(2026, 9, 17, 11, 30)
    assert len([r for r in caplog.records if "XNYS calendar unavailable" in r.getMessage()]) == 1


def test_an_empty_session_lookup_is_a_lookup_error_not_a_crash(monkeypatch, _fresh_flag):
    import helpers.trading_calendar as tc

    monkeypatch.setattr(tc, "xnys_sessions", lambda start, end: ())
    ref = _et("2026-09-17 12:45")
    assert cache._most_recent_completed_intraday_bar_start(ref) == cache._weekday_only_intraday_bar_start(ref)


# ---- (f) the calendar library is not loaded at import time ----

def test_importing_the_cache_api_and_chart_modules_does_not_import_mcal():
    code = (
        "import sys\n"
        "import clients.shared_bars_cache, clients.daily_bar_sources, data.chart_data, core.main\n"
        "assert 'pandas_market_calendars' not in sys.modules, 'mcal imported at module import time'\n"
        "assert 'helpers.trading_calendar' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr[-800:]


# ---- (g) the 60m stale count and the refetch decision ----

@pytest.fixture
def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cache, "engine", engine)
    monkeypatch.setattr(dbs, "engine", engine)
    return engine


def _bar(engine, ticker: str, interval: str, bar_time: datetime) -> None:
    with Session(engine) as session:
        session.add(SharedBarsCache(
            ticker=ticker, interval=interval, bar_time=bar_time, open=1.0, high=1.0, low=1.0, close=1.0, volume=1,
            fetched_at=datetime(2026, 9, 1), source="fmp" if interval == "60m" else None,
        ))
        session.commit()


def _profile(engine, ticker: str, exchange: str) -> None:
    import json

    with Session(engine) as session:
        session.add(FundamentalsCache(
            ticker=ticker, statement_type="profile", period="latest", fetched_at=datetime(2026, 9, 1),
            raw_json=json.dumps([{"symbol": ticker, "exchange": exchange}]),
        ))
        session.commit()


def test_non_us_tickers_are_left_out_of_the_60m_count_but_not_the_daily_one(_engine):
    ref = _et("2026-09-17 21:20")
    latest = datetime(2026, 9, 17, 15, 30)
    _bar(_engine, "AAPL", "60m", latest)                       # fresh US
    _bar(_engine, "MSFT", "60m", latest - timedelta(days=3))   # stale US
    _profile(_engine, "HKFOO", "HKSE")                         # non-US by listing exchange, no dot
    _profile(_engine, "TSM", "NYSE")                           # an ADR listed in the US: counted (and stale: no bars)
    # "0700.HK" has no cached profile: the dot-suffix fallback marks it non-US
    count, stale = cache.stale_ticker_count(["AAPL", "MSFT", "0700.HK", "HKFOO", "TSM"], "60m", ref)
    assert (count, sorted(stale)) == (2, ["MSFT", "TSM"])
    d_count, d_stale = cache.stale_ticker_count(["0700.HK", "HKFOO"], "1d", ref)  # daily counts do not route by listing
    assert (d_count, sorted(d_stale)) == (2, ["0700.HK", "HKFOO"])


def test_a_half_day_or_holiday_night_with_a_current_cache_is_not_stale_and_makes_no_fetch(monkeypatch, _engine):
    calls: list[str] = []

    class Fake:
        async def get_historical_chart_1hour(self, ticker, from_date, to_date):
            calls.append(ticker)
            return []

    monkeypatch.setattr(dbs, "fmp_client", Fake())
    monkeypatch.setattr(dbs.FMPIntradaySource.__init__, "__defaults__", (Fake(),))
    # Fri 2025-11-28 (13:00 early close): the cache holds a bar a day since 11-20 plus the real last bar, 12:30. Seeded
    # wide enough that the coverage rule never asks for a fetch, so only the freshness rule is in play.
    for day in (20, 21, 24, 25, 26):  # 11-27 is Thanksgiving: no bars
        _bar(_engine, "AAPL", "60m", datetime(2025, 11, day, 15, 30))
    for hh, mm in ((9, 30), (10, 30), (11, 30), (12, 30)):
        _bar(_engine, "AAPL", "60m", datetime(2025, 11, 28, hh, mm))
    for ref in (_et("2025-11-28 21:20"), _et("2025-11-29 21:20"), _et("2025-11-30 21:20")):
        assert cache.stale_ticker_count(["AAPL"], "60m", ref) == (0, [])
        asyncio.run(cache.get_or_fetch_bars_batch(["AAPL"], "60m", 7, reference=ref))
    assert calls == []  # the old logic expected a 15:30 bar and refetched on all three nights
    # Labor Day night, cache current through Fri 2026-09-04
    _bar(_engine, "MSFT", "60m", datetime(2026, 9, 4, 15, 30))
    ref = _et("2026-09-07 21:20")
    assert cache.stale_ticker_count(["MSFT"], "60m", ref) == (0, [])
    assert cache._is_stale(datetime(2026, 9, 4, 15, 30), "60m", ref) is False
    assert cache._is_stale(datetime(2026, 9, 4, 14, 30), "60m", ref) is True  # a genuinely missed final bar still reads stale
