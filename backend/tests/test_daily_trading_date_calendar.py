"""Holiday- and early-close-aware "most recently completed trading date" (clients/shared_bars_cache.py::
_most_recent_completed_trading_date) and the daily freshness check built on it. The calendar is
pandas_market_calendars' XNYS (lazily imported, schedule lookup in helpers/trading_calendar.py); on any calendar
error the helper falls back to _weekday_only_completed_trading_date. Mirrors test_intraday_bar_calendar.py."""

import asyncio
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

import clients.daily_bar_sources as dbs
import clients.shared_bars_cache as cache
from core.models import SharedBarsCache

ET = ZoneInfo("America/New_York")
helper = cache._most_recent_completed_trading_date


def _et(text: str) -> datetime:
    return pd.Timestamp(text, tz=ET).to_pydatetime()


# ---- (a) replay of the real schedules and of request times against an independent oracle ----

# Every daily job that reaches the helper fires in the 00:00-03:35 UTC band across all schedule eras (00:00-00:40,
# 01:00-01:45, 02:00-02:40, 03:10, 03:35) -- 19:00-23:35 ET whatever the DST offset -- plus momentum at 02:50.
_FIRE_TIMES_UTC = [(0, 0), (0, 40), (1, 0), (1, 5), (1, 15), (1, 35), (1, 40), (1, 45), (2, 0), (2, 40), (2, 50), (3, 10), (3, 35)]


def _oracle_sessions():
    import pandas_market_calendars as mcal

    schedule = mcal.get_calendar("XNYS").schedule(start_date="2024-09-01", end_date="2026-10-05")
    return [(d.date(), c.to_pydatetime().astimezone(ET)) for d, c in schedule["market_close"].items()]


def _oracle(sessions, ref: datetime) -> date:
    return max(day for day, close in sessions if close <= ref)


def test_replaying_every_job_fire_time_since_2024_09_20_is_never_wrong():
    """The weekday-only logic was wrong on 31 of these 743 nights per job (16 single-night holidays, 5 Fridays x 3)."""
    sessions = _oracle_sessions()
    wrong, day, n = [], date(2024, 9, 20), 0
    while day <= date(2026, 10, 2):
        for hour, minute in _FIRE_TIMES_UTC:
            ref = datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)
            n += 1
            if helper(ref) != _oracle(sessions, ref):
                wrong.append((day, hour, minute))
        day += timedelta(days=1)
    assert n == 743 * len(_FIRE_TIMES_UTC)
    assert wrong == []


def test_replaying_request_times_since_2024_09_20_is_never_wrong():
    sessions = _oracle_sessions()
    wrong, day = [], date(2024, 9, 20)
    while day <= date(2026, 10, 2):
        for hour in (9, 12, 17):
            ref = datetime(day.year, day.month, day.day, hour, 0, tzinfo=ET)
            if helper(ref) != _oracle(sessions, ref):
                wrong.append((day, hour))
        day += timedelta(days=1)
    assert wrong == []


# ---- (b) holidays: weekday holiday, Friday holiday, normal night ----

@pytest.mark.parametrize(
    "reference_et, expected",
    [
        # Labor Day 2026 (Mon 09-07): the holiday itself, its night, the morning after, then the first real night
        ("2026-09-07 12:00", date(2026, 9, 4)),
        ("2026-09-07 21:05", date(2026, 9, 4)),   # the 01:05 UTC cron fire of 09-08
        ("2026-09-08 09:00", date(2026, 9, 4)),   # the morning after: the old helper said the holiday itself
        ("2026-09-08 15:59:59", date(2026, 9, 4)),
        ("2026-09-08 16:00", date(2026, 9, 8)),
        ("2026-09-08 21:05", date(2026, 9, 8)),
        # Good Friday 2026 (Fri 04-03): Fri night, Sat, Sun, Mon morning, Mon night
        ("2026-04-02 21:05", date(2026, 4, 2)),   # a normal night right before it
        ("2026-04-03 21:05", date(2026, 4, 2)),
        ("2026-04-04 21:05", date(2026, 4, 2)),   # Saturday night
        ("2026-04-05 21:05", date(2026, 4, 2)),   # Sunday night
        ("2026-04-06 09:00", date(2026, 4, 2)),
        ("2026-04-06 21:05", date(2026, 4, 6)),
        # Thanksgiving Thursday 2026-11-26 and the next normal night
        ("2026-11-26 21:05", date(2026, 11, 25)),
        # a normal night, a weekend, and a Monday pre-close
        ("2026-09-17 21:05", date(2026, 9, 17)),
        ("2026-09-19 15:00", date(2026, 9, 18)),
        ("2026-09-20 23:59", date(2026, 9, 18)),
        ("2026-09-21 09:00", date(2026, 9, 18)),
        # Jan 9 2025 (national day of mourning) is a closure the calendar knows about
        ("2025-01-09 21:05", date(2025, 1, 8)),
    ],
)
def test_holidays_weekends_and_normal_nights(reference_et, expected):
    assert helper(_et(reference_et)) == expected


# ---- (c) early close: the real close decides, not 16:00 ----

@pytest.mark.parametrize(
    "reference_et, expected",
    [
        # Fri 2025-11-28 closes at 13:00 (Thanksgiving was Thu 11-27)
        ("2025-11-28 09:00", date(2025, 11, 26)),
        ("2025-11-28 12:59:59", date(2025, 11, 26)),
        ("2025-11-28 13:00", date(2025, 11, 28)),  # the session is over from its real close: today
        ("2025-11-28 14:00", date(2025, 11, 28)),  # between 13:00 and 16:00 ET the old helper said 11-26
        ("2025-11-28 15:59:59", date(2025, 11, 28)),
        ("2025-11-28 16:00", date(2025, 11, 28)),
        ("2025-11-28 21:05", date(2025, 11, 28)),
        ("2025-11-29 21:05", date(2025, 11, 28)),
        ("2025-12-01 09:00", date(2025, 11, 28)),
        # Dec 24 2025 (Wed) half-day; its after-close and the Dec 25 holiday night
        ("2025-12-24 12:59:59", date(2025, 12, 23)),
        ("2025-12-24 13:00", date(2025, 12, 24)),
        ("2025-12-25 21:05", date(2025, 12, 24)),
        # a normal day still closes at 16:00
        ("2026-09-17 15:59:59", date(2026, 9, 16)),
        ("2026-09-17 16:00", date(2026, 9, 17)),
    ],
)
def test_the_sessions_real_close_decides(reference_et, expected):
    assert helper(_et(reference_et)) == expected


def test_a_naive_reference_is_read_as_utc_like_before():
    assert helper(datetime(2026, 9, 8, 1, 5)) == date(2026, 9, 4)  # Labor Day night
    assert helper(datetime(2026, 9, 15, 3, 25)) == date(2026, 9, 14)


def test_no_reference_means_now():
    assert helper() == helper(datetime.now(timezone.utc))


# ---- (d) fallback ----

@pytest.fixture
def _fresh_flag(monkeypatch):
    monkeypatch.setattr(cache, "_daily_calendar_fallback_logged", False)


def _boom(*_a, **_k):
    raise RuntimeError("calendar broke")


def test_a_calendar_lookup_error_logs_once_and_behaves_like_the_old_weekday_only_logic(monkeypatch, caplog, _fresh_flag):
    import helpers.trading_calendar as tc

    monkeypatch.setattr(tc, "xnys_sessions", _boom)
    refs = [_et("2026-09-08 09:00"), _et("2026-09-07 21:05"), _et("2026-04-04 21:05"), _et("2026-09-17 21:05")]
    with caplog.at_level(logging.WARNING, logger=cache.logger.name):
        got = [helper(r) for r in refs] + [helper(r) for r in refs]
    assert got[:4] == [cache._weekday_only_completed_trading_date(r) for r in refs]
    assert got[:4] == got[4:]
    assert got[0] == date(2026, 9, 7)  # the old, holiday-blind answer (the real last session was 09-04)
    assert got[2] == date(2026, 4, 3)
    assert len([r for r in caplog.records if "XNYS calendar unavailable" in r.getMessage()]) == 1


def test_an_import_failure_also_falls_back_and_never_raises(monkeypatch, caplog, _fresh_flag):
    monkeypatch.setitem(sys.modules, "helpers.trading_calendar", None)  # `from helpers.trading_calendar import ...` -> ImportError
    with caplog.at_level(logging.WARNING, logger=cache.logger.name):
        assert helper(_et("2026-09-17 21:05")) == date(2026, 9, 17)
        assert helper(_et("2026-09-17 21:05")) == date(2026, 9, 17)
    assert len([r for r in caplog.records if "XNYS calendar unavailable" in r.getMessage()]) == 1


def test_an_empty_session_lookup_is_a_lookup_error_not_a_crash(monkeypatch, _fresh_flag):
    import helpers.trading_calendar as tc

    monkeypatch.setattr(tc, "xnys_sessions", lambda start, end: ())
    ref = _et("2026-09-08 09:00")
    assert helper(ref) == cache._weekday_only_completed_trading_date(ref)


@pytest.mark.parametrize(
    "reference_utc, expected",
    [
        (datetime(2026, 9, 15, 3, 25, tzinfo=timezone.utc), date(2026, 9, 14)),
        (datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 11, 21, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 13, 15, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 15, 3, 25), date(2026, 9, 14)),
        (datetime(2026, 9, 8, 1, 5, tzinfo=timezone.utc), date(2026, 9, 7)),  # holiday-blind, by design
    ],
)
def test_the_weekday_only_fallback_keeps_the_old_behavior(reference_utc, expected):
    assert cache._weekday_only_completed_trading_date(reference_utc) == expected


def test_the_two_weekday_only_fallbacks_do_not_depend_on_the_calendar_aware_helper(monkeypatch):
    """No dependency loop: the intraday fallback is built on the weekday-only daily one, not on the public helper."""
    monkeypatch.setattr(cache, "_most_recent_completed_trading_date", _boom)
    assert cache._weekday_only_intraday_bar_start(_et("2026-09-19 15:00")) == datetime(2026, 9, 18, 15, 30)
    assert cache._weekday_only_completed_trading_date(_et("2026-09-19 15:00")) == date(2026, 9, 18)


# ---- (e) the freshness check and the refetch decision ----

@pytest.fixture
def _engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(cache, "engine", engine)
    monkeypatch.setattr(dbs, "engine", engine)
    return engine


def _bar(engine, ticker: str, bar_day: date, fetched_at: datetime) -> None:
    with Session(engine) as session:
        session.add(SharedBarsCache(
            ticker=ticker, interval="1d", bar_time=datetime(bar_day.year, bar_day.month, bar_day.day), open=1.0, high=1.0,
            low=1.0, close=1.0, volume=1, fetched_at=fetched_at, source=None,
        ))
        session.commit()


def _local_naive(text_et: str) -> datetime:
    """A naive server-local timestamp for an ET wall-clock time (how fetched_at is stored)."""
    return datetime.fromtimestamp(_et(text_et).timestamp())


class _CountingSource:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, unserved_tickers=None, replace_tickers=None, full_refresh=False):
        self.calls.append(list(tickers_with_days))
        return {}


def _seed_through(engine, ticker: str, last: date, fetched_at: datetime, sessions: int = 40) -> None:
    day, n = last, 0
    while n < sessions:
        if day.weekday() < 5:
            _bar(engine, ticker, day, fetched_at)
            n += 1
        day -= timedelta(days=1)


@pytest.mark.parametrize(
    "night_et, last_session",
    [
        ("2026-09-07 21:05", date(2026, 9, 4)),   # Labor Day night
        ("2026-09-08 09:00", date(2026, 9, 4)),   # the morning after
        ("2026-04-03 21:05", date(2026, 4, 2)),   # Good Friday night
        ("2026-04-04 21:05", date(2026, 4, 2)),   # Saturday
        ("2026-04-05 21:05", date(2026, 4, 2)),   # Sunday
        ("2026-04-06 09:00", date(2026, 4, 2)),   # Monday morning
    ],
)
def test_a_holiday_night_with_the_prior_session_cached_is_not_stale_and_makes_no_fmp_call(monkeypatch, _engine, night_et, last_session):
    source = _CountingSource()
    monkeypatch.setattr(cache, "get_daily_bar_source", lambda: source)
    ref = _et(night_et)
    written = _local_naive(f"{last_session} 21:05")  # written after that session's close, so not provisional
    _seed_through(_engine, "AAA", last_session, fetched_at=written)
    _seed_through(_engine, "BBB", last_session, fetched_at=written)
    assert cache._is_stale(datetime(last_session.year, last_session.month, last_session.day), "1d", ref) is False
    assert cache.stale_ticker_count(["AAA", "BBB"], "1d", ref) == (0, [])
    out = asyncio.run(cache.get_or_fetch_bars_batch(["AAA", "BBB"], "1d", 30, reference=ref))
    assert source.calls == []  # the old logic expected a bar dated the holiday and refetched every ticker
    assert set(out) == {"AAA", "BBB"}


def test_a_genuinely_missed_session_still_reads_stale_on_a_holiday_night(monkeypatch, _engine):
    source = _CountingSource()
    monkeypatch.setattr(cache, "get_daily_bar_source", lambda: source)
    ref = _et("2026-09-07 21:05")
    _seed_through(_engine, "MISSED", date(2026, 9, 3), fetched_at=_local_naive("2026-09-03 21:05"))  # Fri 09-04 never arrived
    assert cache.stale_ticker_count(["MISSED"], "1d", ref) == (1, ["MISSED"])
    asyncio.run(cache.get_or_fetch_bars_batch(["MISSED"], "1d", 30, reference=ref))
    assert source.calls == [["MISSED"]]


def test_the_first_real_night_after_the_holiday_expects_the_new_session(_engine):
    ref = _et("2026-09-08 21:05")
    assert cache._is_stale(datetime(2026, 9, 4), "1d", ref) is True
    assert cache._is_stale(datetime(2026, 9, 8), "1d", ref) is False


# ---- (f) early-close day and the hard-coded 16:00 in the provisional-bar rule ----

def test_on_an_early_close_afternoon_the_new_helper_and_the_hard_coded_16_00_provisional_rule_are_conservative(_engine):
    """Between the real 13:00 close and 16:10 ET of an early-close day the helper already returns that day, while
    _provisional_last_bar_tickers (unchanged, 16:00 + 10 min settle) still treats a bar written in that window as
    provisional. The only consequence is an extra refetch of that bar in a window no cron job runs in; a bar written
    after 16:10 is final."""
    day = date(2025, 11, 28)
    ref = _et("2025-11-28 14:30")
    assert helper(ref) == day
    _bar(_engine, "AAA", day, _local_naive("2025-11-28 14:00"))
    _bar(_engine, "BBB", day, _local_naive("2025-11-28 21:05"))
    with Session(_engine) as session:
        span = cache._cache_span(session, ["AAA", "BBB"], "1d")
        assert cache._provisional_last_bar_tickers(session, ["AAA", "BBB"], span, ref) == {"AAA"}
        assert cache._provisional_last_bar_tickers(session, ["AAA", "BBB"], span, _et("2025-11-28 21:30")) == {"AAA"}
