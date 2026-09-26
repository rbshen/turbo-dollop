import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import clients.shared_bars_cache as shared_bars_cache
from clients.shared_bars_cache import (
    DAILY_INTERVAL,
    INTRADAY_INTERVAL,
    _is_stale,
    _most_recent_completed_intraday_bar_start,
    _most_recent_completed_trading_date,
    _period_for,
    get_or_fetch_bars,
    get_or_fetch_bars_batch,
)
from core.models import SharedBarsCache


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(shared_bars_cache, "engine", engine)
    return engine


def _seed_row(engine, ticker: str, interval: str, bar_time: datetime, fetched_at: datetime, close: float = 100.0, source: str | None = "fmp") -> None:
    with Session(engine) as session:
        session.add(
            SharedBarsCache(
                ticker=ticker,
                interval=interval,
                bar_time=bar_time,
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=1000,
                fetched_at=fetched_at,
                source=source,
            )
        )
        session.commit()


def _daily_df(dates: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    n = len(dates)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=index,
    )


def _intraday_df(timestamps: list[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(t, tz="America/New_York") for t in timestamps])
    n = len(timestamps)
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=index,
    )


class _FakeBarSource:
    """Stands in for BOTH FMP sources at the cache boundary (FMPDailySource via
    get_daily_bar_source, FMPIntradaySource): serves the given frames, records every call, and
    reports what it could not serve. Frames may use either casing (the real sources return
    lowercase)."""

    def __init__(self, frames_by_ticker: dict[str, pd.DataFrame], calls: list[dict]):
        self._frames, self.calls = frames_by_ticker, calls

    def _serve(self, interval, tickers_with_days, unserved_tickers, auto_adjust=None):
        self.calls.append(
            {"tickers": list(tickers_with_days), "days": dict(tickers_with_days), "interval": interval, "auto_adjust": auto_adjust}
        )
        out = {t: self._frames[t].rename(columns=str.lower) for t in tickers_with_days if t in self._frames}
        if unserved_tickers is not None:
            unserved_tickers.extend(t for t in tickers_with_days if t not in out)
        return out

    async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, unserved_tickers=None, replace_tickers=None, full_refresh=False):
        return self._serve("1d", tickers_with_days, unserved_tickers, auto_adjust)

    async def get_intraday_bars(self, tickers_with_days, reference=None, replace_tickers=None, full_refresh=False, unserved_tickers=None):
        return self._serve("60m", tickers_with_days, unserved_tickers)


def _patch_fetch(monkeypatch, frames_by_ticker: dict[str, pd.DataFrame]):
    calls: list[dict] = []
    source = _FakeBarSource(frames_by_ticker, calls)
    monkeypatch.setattr(shared_bars_cache, "get_daily_bar_source", lambda: source)
    monkeypatch.setattr(shared_bars_cache, "FMPIntradaySource", lambda: source)
    return calls


def _patch_no_fetch(monkeypatch, message: str = "must not fetch live"):
    """Any live fetch (either interval) fails the test."""

    class _Boom:
        async def get_daily_bars(self, *a, **k):
            raise AssertionError(message)

        get_intraday_bars = get_daily_bars

    monkeypatch.setattr(shared_bars_cache, "get_daily_bar_source", lambda: _Boom())
    monkeypatch.setattr(shared_bars_cache, "FMPIntradaySource", lambda: _Boom())


# ---------------------------------------------------------------------------
# _most_recent_completed_trading_date (ported verbatim from the deleted
# clients/daily_price_sources.py -- same cases, still correct here).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference_utc, expected",
    [
        (datetime(2026, 9, 15, 3, 25, tzinfo=timezone.utc), date(2026, 9, 14)),
        (datetime(2026, 9, 14, 13, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 11, 21, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 12, 15, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 13, 15, 0, tzinfo=timezone.utc), date(2026, 9, 11)),
        (datetime(2026, 9, 15, 3, 25), date(2026, 9, 14)),
    ],
)
def test_most_recent_completed_trading_date(reference_utc, expected):
    assert _most_recent_completed_trading_date(reference_utc) == expected


# ---------------------------------------------------------------------------
# _most_recent_completed_intraday_bar_start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference_et, expected_naive_et",
    [
        # Before market open on a trading day -- no bar has started today at
        # all, falls back to the prior trading day's own last (15:30) bar.
        ("2026-09-17 04:30", datetime(2026, 9, 16, 15, 30)),
        # Between open and the first bar's own completion (09:30-10:30) --
        # today's 09:30 bar is still in progress, not yet complete.
        ("2026-09-17 09:45", datetime(2026, 9, 16, 15, 30)),
        # Exactly at the first bar's completion boundary -- inclusive.
        ("2026-09-17 10:30", datetime(2026, 9, 17, 9, 30)),
        # Mid-session -- the 11:30 bar (11:30-12:30) is the most recent one
        # whose own window has fully elapsed.
        ("2026-09-17 12:45", datetime(2026, 9, 17, 11, 30)),
        # After close -- today's own last (15:30) bar, a 30-minute bar
        # ending at the 16:00 close, not a full 60-minute one.
        ("2026-09-17 17:00", datetime(2026, 9, 17, 15, 30)),
        # Weekend -- rolls back to the preceding Friday's last bar.
        ("2026-09-19 15:00", datetime(2026, 9, 18, 15, 30)),
    ],
)
def test_most_recent_completed_intraday_bar_start(reference_et, expected_naive_et):
    reference = pd.Timestamp(reference_et, tz=ZoneInfo("America/New_York")).to_pydatetime()
    assert _most_recent_completed_intraday_bar_start(reference) == expected_naive_et


# ---------------------------------------------------------------------------
# _is_stale
# ---------------------------------------------------------------------------


def test_is_stale_none_reads_as_stale():
    assert _is_stale(None, DAILY_INTERVAL) is True
    assert _is_stale(None, INTRADAY_INTERVAL) is True


def test_is_stale_daily_fresh_and_stale():
    reference = datetime(2026, 9, 15, 3, 25, tzinfo=timezone.utc)  # -> most recent completed date 2026-09-14
    assert _is_stale(datetime(2026, 9, 14), DAILY_INTERVAL, reference) is False
    assert _is_stale(datetime(2026, 9, 13), DAILY_INTERVAL, reference) is True
    assert _is_stale(datetime(2026, 9, 15), DAILY_INTERVAL, reference) is False  # newer than expected is fine


def test_is_stale_intraday_fresh_and_stale():
    reference = pd.Timestamp("2026-09-17 12:45", tz=ZoneInfo("America/New_York")).to_pydatetime()
    # Expected most-recent-completed bar is today 11:30.
    assert _is_stale(datetime(2026, 9, 17, 11, 30), INTRADAY_INTERVAL, reference) is False
    assert _is_stale(datetime(2026, 9, 17, 10, 30), INTRADAY_INTERVAL, reference) is True
    assert _is_stale(datetime(2026, 9, 16, 15, 30), INTRADAY_INTERVAL, reference) is True  # yesterday's close, stale mid-session


def test_is_stale_rejects_unsupported_interval():
    with pytest.raises(ValueError):
        _is_stale(datetime(2026, 9, 14), "1wk")


# ---------------------------------------------------------------------------
# _period_for
# ---------------------------------------------------------------------------


def test_period_for_snaps_up_to_the_nearest_covering_tier():
    assert _period_for(DAILY_INTERVAL, 45) == "3mo"
    assert _period_for(DAILY_INTERVAL, 730) == "2y"
    assert _period_for(DAILY_INTERVAL, 1800) == "5y"


def test_period_for_intraday_clamps_at_its_widest_tier():
    # The 60m history limit is ~730 days -- there is no wider tier
    # to snap to, so an over-large request clamps rather than erroring.
    assert _period_for(INTRADAY_INTERVAL, 60) == "3mo"
    assert _period_for(INTRADAY_INTERVAL, 730) == "2y"
    assert _period_for(INTRADAY_INTERVAL, 5000) == "2y"


# ---------------------------------------------------------------------------
# get_or_fetch_bars_batch -- growth + freshness behavior
# ---------------------------------------------------------------------------

_REFERENCE = datetime(2026, 9, 18, 3, 10, tzinfo=timezone.utc)  # 2026-09-17 23:10 ET -> most recent completed date 2026-09-17
_TODAY = _most_recent_completed_trading_date(_REFERENCE)


def test_fetches_live_when_nothing_cached(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_fetch(monkeypatch, {"AAPL": _daily_df(["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17"])})

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=3, reference=_REFERENCE))

    assert len(calls) == 1
    assert "AAPL" in result
    assert not result["AAPL"].empty


def test_fresh_and_sufficient_coverage_is_served_without_a_live_call(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    for i in range(3):
        _seed_row(
            engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY - timedelta(days=2 - i), datetime.min.time()), datetime(2026, 9, 18, 3, 0)
        )

    _patch_no_fetch(monkeypatch, "must not fetch live when cache is fresh and wide enough")

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=2, reference=_REFERENCE))

    assert len(result["AAPL"]) == 2  # cache holds 3 days, but lookback_days=2 (today + 1 prior) trims to the caller's own window


def test_insufficient_coverage_triggers_a_wider_fetch_and_extends_the_cache(monkeypatch):
    """The exact BB+RSI/Warren and Liquidity-Zone/Trend scenario: a
    narrower consumer's own already-fresh cache doesn't satisfy a wider
    consumer's request -- the wider request must trigger a live fetch
    sized to its own need, not just skip because SOMETHING is cached."""
    engine = _fresh_engine(monkeypatch)
    # Only 2 days cached (as if a 60-day BB+RSI-shaped consumer wrote this),
    # reaching all the way up to today -- fresh, just too narrow.
    _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY - timedelta(days=1), datetime.min.time()), datetime(2026, 9, 18, 3, 0))
    _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY, datetime.min.time()), datetime(2026, 9, 18, 3, 0))

    wider_df = _daily_df([(_TODAY - timedelta(days=d)).isoformat() for d in range(25, -1, -1)])
    calls = _patch_fetch(monkeypatch, {"AAPL": wider_df})

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=25, reference=_REFERENCE))

    assert len(calls) == 1
    assert len(result["AAPL"]) >= 25  # the wider window was actually fetched and stored


def test_stale_row_forces_a_refetch_even_with_sufficient_coverage(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    # 30 days of history, but the last bar is 2 days behind today -- missing
    # the most recent 2 sessions' closes entirely, even though the WIDTH is
    # plenty for the 10-day request below.
    last_cached = _TODAY - timedelta(days=2)
    for i in range(30):
        _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(last_cached - timedelta(days=29 - i), datetime.min.time()), datetime(2026, 9, 16, 3, 0))

    calls = _patch_fetch(
        monkeypatch, {"AAPL": _daily_df([(last_cached + timedelta(days=d)).isoformat() for d in range(3)])}
    )

    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=10, reference=_REFERENCE))

    assert len(calls) == 1  # forced a live refetch despite already having 30 days cached


def test_narrower_consumer_reuses_a_wider_already_fresh_cached_row_with_zero_live_calls(monkeypatch):
    """The BB+RSI-reuses-Warren's-row scenario, at the cache-module level:
    once a wide (2y) fresh row exists, a narrower (60d) request must be
    served entirely from cache."""
    engine = _fresh_engine(monkeypatch)
    for i in range(400):
        _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY - timedelta(days=399 - i), datetime.min.time()), datetime(2026, 9, 18, 3, 5))

    _patch_no_fetch(monkeypatch, "narrower request must not trigger its own live fetch")

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=60, reference=_REFERENCE))

    assert not result["AAPL"].empty


def test_results_are_trimmed_to_the_callers_own_lookback_window(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    for i in range(100):
        _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY - timedelta(days=99 - i), datetime.min.time()), datetime(2026, 9, 18, 3, 0))

    _patch_no_fetch(monkeypatch, "should be served entirely from cache")

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=10, reference=_REFERENCE))

    assert len(result["AAPL"]) <= 11  # trimmed down from the full 100-row cache


def test_force_true_always_live_fetches_regardless_of_freshness(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY, datetime.min.time()), datetime(2026, 9, 18, 3, 5))

    calls = _patch_fetch(monkeypatch, {"AAPL": _daily_df(["2026-09-17"])})

    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=1, force=True, reference=_REFERENCE))

    assert len(calls) == 1


def test_auto_adjust_propagates_to_the_underlying_fetch(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = _patch_fetch(monkeypatch, {"AAPL": _daily_df(["2026-09-17"])})

    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=1, auto_adjust=False, reference=_REFERENCE))

    assert calls[0]["auto_adjust"] is False


def test_batch_only_fetches_tickers_that_actually_need_it(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY, datetime.min.time()), datetime(2026, 9, 18, 3, 0))

    calls = _patch_fetch(monkeypatch, {"MSFT": _daily_df(["2026-09-17"])})

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL", "MSFT"], DAILY_INTERVAL, lookback_days=1, reference=_REFERENCE))

    assert calls[0]["tickers"] == ["MSFT"]  # AAPL skipped -- already fresh and wide enough
    assert "AAPL" in result and "MSFT" in result


def test_get_or_fetch_bars_single_ticker_delegates_to_batch(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fetch(monkeypatch, {"AAPL": _daily_df(["2026-09-17"])})

    result = asyncio.run(get_or_fetch_bars("AAPL", DAILY_INTERVAL, lookback_days=1, reference=_REFERENCE))

    assert not result.empty


def test_get_or_fetch_bars_returns_empty_frame_for_a_ticker_with_no_data(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fetch(monkeypatch, {})

    result = asyncio.run(get_or_fetch_bars("BADTICKER", DAILY_INTERVAL, lookback_days=1, reference=_REFERENCE))

    assert result.empty


def test_intraday_frame_has_a_tz_aware_eastern_index(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fetch(monkeypatch, {"AAPL": _intraday_df(["2026-09-17 09:30", "2026-09-17 10:30"])})

    result = asyncio.run(get_or_fetch_bars("AAPL", INTRADAY_INTERVAL, lookback_days=1, reference=_REFERENCE))

    assert str(result.index.tz) == "America/New_York"


def test_daily_frame_has_a_naive_index(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fetch(monkeypatch, {"AAPL": _daily_df(["2026-09-17"])})

    result = asyncio.run(get_or_fetch_bars("AAPL", DAILY_INTERVAL, lookback_days=1, reference=_REFERENCE))

    assert result.index.tz is None


# ---------------------------------------------------------------------------
# Intraday (60m) path -- Warren/BB+RSI's shared row
# ---------------------------------------------------------------------------

# 2026-09-17 12:45 ET -> most recent completed 60m bar is 09-17 11:30.
_INTRADAY_REFERENCE = pd.Timestamp("2026-09-17 12:45", tz=ZoneInfo("America/New_York")).to_pydatetime()


def _seed_intraday_history(engine, days: int, last_bar: datetime, fetched_at: datetime) -> None:
    """`days` trading-day-shaped sessions of 7 bars each, ending with a last
    bar at exactly `last_bar` (weekday-agnostic -- only bar_time ordering and
    coverage width matter to the cache logic under test)."""
    starts = [(9, 30), (10, 30), (11, 30), (12, 30), (13, 30), (14, 30), (15, 30)]
    for d in range(days):
        day = last_bar.date() - timedelta(days=days - 1 - d)
        for h, m in starts:
            bar = datetime(day.year, day.month, day.day, h, m)
            if bar <= last_bar:
                _seed_row(engine, "AAPL", INTRADAY_INTERVAL, bar, fetched_at)


def test_intraday_stale_row_forces_a_refetch_even_with_sufficient_coverage(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    # 70 days wide, but the last bar is yesterday's close -- mid-session
    # today, the 09-17 09:30/10:30 bars have completed and are missing.
    _seed_intraday_history(engine, days=70, last_bar=datetime(2026, 9, 16, 15, 30), fetched_at=datetime(2026, 9, 17, 3, 0))
    calls = _patch_fetch(monkeypatch, {"AAPL": _intraday_df(["2026-09-17 09:30", "2026-09-17 10:30", "2026-09-17 11:30"])})

    asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, lookback_days=60, reference=_INTRADAY_REFERENCE))

    assert len(calls) == 1
    assert calls[0]["interval"] == INTRADAY_INTERVAL


def test_intraday_fresh_row_is_not_marked_stale_overnight(monkeypatch):
    """Guards the false-stale case: outside market hours there is no newer
    bar to wait for, so a row whose last bar is the prior session's close
    must read as fresh at 3:20am (BB+RSI's/Warren's actual run time)."""
    engine = _fresh_engine(monkeypatch)
    overnight = pd.Timestamp("2026-09-18 03:20", tz=ZoneInfo("America/New_York")).to_pydatetime()
    _seed_intraday_history(engine, days=70, last_bar=datetime(2026, 9, 17, 15, 30), fetched_at=datetime(2026, 9, 17, 23, 0))

    _patch_no_fetch(monkeypatch, "overnight read of a row ending at the last session's close must not refetch")

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, lookback_days=60, reference=overnight))

    assert not result["AAPL"].empty


def test_intraday_fresh_row_is_not_marked_stale_over_a_weekend(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    saturday = pd.Timestamp("2026-09-19 10:00", tz=ZoneInfo("America/New_York")).to_pydatetime()
    _seed_intraday_history(engine, days=70, last_bar=datetime(2026, 9, 18, 15, 30), fetched_at=datetime(2026, 9, 18, 23, 0))

    _patch_no_fetch(monkeypatch, "a weekend read of Friday's close must not refetch")

    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, lookback_days=60, reference=saturday))

    assert not result["AAPL"].empty


def test_intraday_narrow_row_grows_to_a_wider_request_and_narrow_reader_then_reuses_it(monkeypatch):
    """BB+RSI-reuses-Warren's-row at the cache level for the real 60m
    interval: a 60d row is widened by a 730d request, after which a 60d
    request is a zero-live-call cache hit."""
    engine = _fresh_engine(monkeypatch)
    overnight = pd.Timestamp("2026-09-18 03:20", tz=ZoneInfo("America/New_York")).to_pydatetime()
    _seed_intraday_history(engine, days=60, last_bar=datetime(2026, 9, 17, 15, 30), fetched_at=datetime(2026, 9, 18, 3, 10))

    wide = _intraday_df(["2025-09-20 09:30", "2026-09-17 15:30"])
    calls = _patch_fetch(monkeypatch, {"AAPL": wide})

    asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, lookback_days=730, reference=overnight))
    assert len(calls) == 1
    assert calls[0]["days"] == {"AAPL": 730}

    _patch_no_fetch(monkeypatch, "narrow reader must reuse the widened row")
    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, lookback_days=60, reference=overnight))
    assert not result["AAPL"].empty


def test_a_refetch_triggered_by_the_narrower_consumer_preserves_the_wider_cached_width(monkeypatch):
    """The steady-state nightly case: BB+RSI (60d) finds the 2y row stale
    and refetches -- it must request enough to KEEP the 2y width, not
    shrink the cache to its own 60d need."""
    engine = _fresh_engine(monkeypatch)
    overnight = pd.Timestamp("2026-09-18 03:20", tz=ZoneInfo("America/New_York")).to_pydatetime()
    # Wide (~2y) row whose last bar is one session behind (09-16 close).
    _seed_intraday_history(engine, days=728, last_bar=datetime(2026, 9, 16, 15, 30), fetched_at=datetime(2026, 9, 17, 3, 0))
    calls = _patch_fetch(monkeypatch, {"AAPL": _intraday_df(["2026-09-17 15:30"])})

    asyncio.run(get_or_fetch_bars_batch(["AAPL"], INTRADAY_INTERVAL, lookback_days=60, reference=overnight))

    assert calls[0]["days"] == {"AAPL": 730}  # not 60 -- the existing (2y-tier) width was preserved


def test_preserved_lookback_snaps_to_a_tier_and_does_not_drift_as_bars_accumulate():
    from clients.shared_bars_cache import _preserved_lookback_days

    def span(first: date, last: date):
        return datetime.combine(first, datetime.min.time()), datetime.combine(last, datetime.min.time())

    # A "2y"-fetched row, right after fetch and a year of nightly appends later:
    assert _preserved_lookback_days(*span(date(2024, 9, 20), date(2026, 9, 17)), DAILY_INTERVAL) == 730
    assert _preserved_lookback_days(*span(date(2024, 9, 20), date(2027, 9, 17)), DAILY_INTERVAL) == 730
    # A "5y"-fetched row (span a few days short of 1825 -- weekend at the boundary):
    assert _preserved_lookback_days(*span(date(2021, 9, 21), date(2026, 9, 17)), DAILY_INTERVAL) == 1825
    # Tiny row -> its own span; empty -> 0:
    assert _preserved_lookback_days(*span(date(2026, 9, 16), date(2026, 9, 17)), DAILY_INTERVAL) == 2
    assert _preserved_lookback_days(None, None, DAILY_INTERVAL) == 0


def test_each_ticker_is_fetched_at_the_width_it_needs(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    # WIDE already holds a 5y-tier row that is one session stale; NEW has nothing.
    for d in (_TODAY - timedelta(days=1826), _TODAY - timedelta(days=1)):
        _seed_row(engine, "WIDE", DAILY_INTERVAL, datetime.combine(d, datetime.min.time()), datetime(2026, 9, 17, 3, 0))
    calls = _patch_fetch(monkeypatch, {"WIDE": _daily_df([_TODAY.isoformat()]), "NEW": _daily_df([_TODAY.isoformat()])})

    asyncio.run(get_or_fetch_bars_batch(["WIDE", "NEW"], DAILY_INTERVAL, lookback_days=730, reference=_REFERENCE))

    assert len(calls) == 1 and calls[0]["days"] == {"WIDE": 1825, "NEW": 730}  # WIDE keeps its 5y tier, NEW gets its own need


def test_upsert_is_idempotent_and_overwrites_the_same_bar(monkeypatch):
    _fresh_engine(monkeypatch)
    df1 = _daily_df([_TODAY.isoformat()])
    _patch_fetch(monkeypatch, {"AAPL": df1})
    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=1, force=True, reference=_REFERENCE))
    df2 = _daily_df([_TODAY.isoformat()])
    df2["Close"] = 555.0
    _patch_fetch(monkeypatch, {"AAPL": df2})
    result = asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=1, force=True, reference=_REFERENCE))

    assert len(result["AAPL"]) == 1  # same (ticker, interval, bar_time) key -- updated, not duplicated
    assert result["AAPL"]["close"].iloc[0] == 555.0


# ---------------------------------------------------------------------------
# P2: FMP full-history replace, provisional last bar
# ---------------------------------------------------------------------------


def _count_rows(engine, ticker: str) -> int:
    from sqlalchemy import func
    from sqlmodel import select

    with Session(engine) as session:
        return session.exec(
            select(func.count()).select_from(SharedBarsCache).where(SharedBarsCache.ticker == ticker, SharedBarsCache.interval == DAILY_INTERVAL)
        ).one()


def test_a_full_history_result_replaces_the_tickers_old_rows_instead_of_upserting_over_them(monkeypatch):
    """Symbol-reuse / restated history: rows on dates the new series lacks must not survive."""
    engine = _fresh_engine(monkeypatch)
    old_first = _TODAY - timedelta(days=40)
    for i in range(41):  # a stitched/stale history, fresh last bar
        _seed_row(engine, "META", DAILY_INTERVAL, datetime.combine(old_first + timedelta(days=i), datetime.min.time()), datetime(2026, 9, 18, 3, 0), close=14.0)
    new_dates = [_TODAY - timedelta(days=d) for d in range(29, -1, -1)]

    class FullReplaceSource:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, unserved_tickers=None, replace_tickers=None, full_refresh=False):
            replace_tickers.extend(tickers_with_days)
            return {t: _daily_df([d.isoformat() for d in new_dates]).rename(columns=str.lower) for t in tickers_with_days}

    monkeypatch.setattr(shared_bars_cache, "get_daily_bar_source", lambda: FullReplaceSource())
    asyncio.run(get_or_fetch_bars_batch(["META"], DAILY_INTERVAL, lookback_days=60, reference=_REFERENCE))  # 41 bars < 60d: insufficient -> fetch
    assert _count_rows(engine, "META") == 30  # the old 41 rows are gone, only the new 30 remain


def test_force_is_passed_to_the_daily_source_as_full_refresh(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    seen = {}

    class Src:
        async def get_daily_bars(self, tickers_with_days, auto_adjust, reference=None, unserved_tickers=None, replace_tickers=None, full_refresh=False):
            seen["full_refresh"] = full_refresh
            return {}

    monkeypatch.setattr(shared_bars_cache, "get_daily_bar_source", lambda: Src())
    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=5, force=True, reference=_REFERENCE))
    assert seen["full_refresh"] is True


def test_a_last_bar_written_before_its_sessions_close_is_refetched(monkeypatch):
    """The 2026-09-23 15:50 ET incident: a bar dated the most recent session but
    written mid-session is provisional, and a date-only freshness check kept it forever."""
    engine = _fresh_engine(monkeypatch)
    written_mid_session = datetime.combine(_TODAY, datetime(2026, 1, 1, 19, 50).time())  # 19:50 UTC = 15:50 ET
    for i in range(5):
        _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY - timedelta(days=4 - i), datetime.min.time()), written_mid_session)
    calls = _patch_fetch(monkeypatch, {"AAPL": _daily_df([_TODAY.isoformat()])})
    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=3, reference=_REFERENCE))
    assert len(calls) == 1


def test_a_last_bar_written_after_the_close_is_trusted(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    after_close = datetime.combine(_TODAY + timedelta(days=1), datetime(2026, 1, 1, 3, 10).time())  # 03:10 UTC next day
    for i in range(5):
        _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(_TODAY - timedelta(days=4 - i), datetime.min.time()), after_close)
    calls = _patch_fetch(monkeypatch, {"AAPL": _daily_df([_TODAY.isoformat()])})
    asyncio.run(get_or_fetch_bars_batch(["AAPL"], DAILY_INTERVAL, lookback_days=3, reference=_REFERENCE))
    assert calls == []


# ---------------------------------------------------------------------------
# Routing through the REAL FMPDailySource, fake network at the FMP client only
# ---------------------------------------------------------------------------

import clients.daily_bar_sources as _dbs  # noqa: E402
import core.data_groups as _dg  # noqa: E402
from clients.fmp_client import fmp_client as _fmp_singleton  # noqa: E402

_HK = "0005.HK"
_US = "KO"


def _weekdays(n: int, end: date = _TODAY) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _fmp_rows(days: list[date], base: float = 100.0, extra: list[dict] | None = None) -> list[dict]:
    rows = [
        {"symbol": "X", "date": d.isoformat(), "open": base + i, "high": base + i + 1, "low": base + i - 1,
         "close": base + i + 0.5, "volume": 1000 + i}
        for i, d in enumerate(days)
    ]
    return sorted(rows + (extra or []), key=lambda r: r["date"], reverse=True)


class _RoutingHarness:
    """Real routing + the real FMPDailySource, fake network at the FMP client."""

    def __init__(self, monkeypatch, engine, fmp_rows: dict[str, list[dict]], fmp_fail=()):
        self.fmp_calls: list[tuple[str, str, str]] = []  # (ticker, from, group)
        self.fmp_rows, self.fmp_fail = fmp_rows, set(fmp_fail)

        async def fake_fmp(ticker, from_date, to_date, group="daily_prices"):
            self.fmp_calls.append((ticker, from_date, group))
            if ticker in self.fmp_fail:
                import httpx

                raise httpx.ConnectError("boom")
            return [r for r in self.fmp_rows.get(ticker, []) if r["date"] >= from_date]

        monkeypatch.setattr(_fmp_singleton, "get_historical_price_eod", fake_fmp)
        monkeypatch.setattr(_dbs, "engine", engine)
        monkeypatch.setattr(_dbs, "_completed_session", lambda: _TODAY)


def _run_batch(tickers, **kw):
    fb = _dbs.UnservedTickers()
    frames = asyncio.run(
        get_or_fetch_bars_batch(tickers, DAILY_INTERVAL, lookback_days=30, reference=_REFERENCE, unserved_tickers=fb, **kw)
    )
    return frames, fb


def test_non_us_ticker_is_not_fetched_at_all(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    h = _RoutingHarness(monkeypatch, engine, {_HK: _fmp_rows(_weekdays(40)), "AAPL": _fmp_rows(_weekdays(40))})
    frames, fb = _run_batch(["AAPL", _HK])
    assert [c[0] for c in h.fmp_calls] == ["AAPL"]
    assert _HK not in frames or frames[_HK].empty
    assert list(fb) == []


def test_group_off_is_cached_only_and_reports_everything_unserved(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    rows = {"AAPL": _fmp_rows(_weekdays(40))}

    # daily_prices off: nothing is fetched, nothing written, and the ticker is reported unserved
    _dg.set_group_enabled("daily_prices", False)
    h = _RoutingHarness(monkeypatch, engine, rows)
    frames, fb = _run_batch(["AAPL"])
    assert h.fmp_calls == [] and list(fb) == ["AAPL"]
    assert fb.describe() == "1 not served by FMP (cached bars kept)"
    assert "AAPL" not in frames or frames["AAPL"].empty

    # master switch off: the same
    engine3 = _fresh_engine(monkeypatch)
    _dg.set_group_enabled("daily_prices", True)
    _dg.set_master(False)
    h = _RoutingHarness(monkeypatch, engine3, rows)
    _, fb = _run_batch(["AAPL"])
    assert h.fmp_calls == [] and list(fb) == ["AAPL"]


def test_group_off_serves_whatever_is_already_cached_however_stale(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    days = _weekdays(40)[:-3]  # last bar three sessions behind
    for i, d in enumerate(days):
        _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(d, datetime.min.time()), datetime(2026, 9, 10, 3, 0), close=100.0 + i)
    _dg.set_group_enabled("daily_prices", False)
    h = _RoutingHarness(monkeypatch, engine, {})
    frames, fb = _run_batch(["AAPL"])
    assert h.fmp_calls == [] and list(fb) == ["AAPL"] and not frames["AAPL"].empty


def test_fmp_empty_or_error_leaves_the_ticker_unserved_with_its_cache_intact(monkeypatch):
    for fmp_rows, fail in (({"AAPL": []}, ()), ({}, ("AAPL",))):
        engine = _fresh_engine(monkeypatch)
        days = _weekdays(40)[:-2]
        for i, d in enumerate(days):
            _seed_row(engine, "AAPL", DAILY_INTERVAL, datetime.combine(d, datetime.min.time()), datetime(2026, 9, 10, 3, 0), close=100.0 + i)
        n_before = _count_rows(engine, "AAPL")
        _RoutingHarness(monkeypatch, engine, fmp_rows, fmp_fail=fail)
        frames, fb = _run_batch(["AAPL"])
        assert list(fb) == ["AAPL"] and not frames["AAPL"].empty  # served from the stale cache
        assert _count_rows(engine, "AAPL") == n_before  # nothing wiped


def _seed_clean_us_cache(engine, days: list[date], fetched_at: datetime):
    for i, d in enumerate(days):
        _seed_row(engine, _US, DAILY_INTERVAL, datetime.combine(d, datetime.min.time()), fetched_at, close=100.5 + i)


def test_sunday_force_resync_refetches_the_full_window_and_replaces_stale_phantoms(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    days = _weekdays(40)
    _seed_clean_us_cache(engine, days, datetime(2026, 9, 18, 3, 0))
    # a legacy (Yahoo-era or pre-filter) junk row on a weekend date sits in the cache
    junk = days[-5] + timedelta(days=(5 - days[-5].weekday()))  # the Saturday after days[-5]
    _seed_row(engine, _US, DAILY_INTERVAL, datetime.combine(junk, datetime.min.time()), datetime(2026, 9, 18, 3, 0), close=1.0)
    n_before = _count_rows(engine, _US)
    h = _RoutingHarness(monkeypatch, engine, {_US: _fmp_rows(days)})
    _run_batch([_US], force=True)
    assert len(h.fmp_calls) == 1
    assert h.fmp_calls[0][1] < days[-2].isoformat()  # the full window, not the ~7-day overlap
    with Session(engine) as session:
        stored = {r.bar_time.date() for r in session.exec(select(SharedBarsCache).where(SharedBarsCache.ticker == _US)).all()}
    assert junk not in stored and stored and all(d.weekday() < 5 for d in stored)  # replaced, not upserted over
    assert _count_rows(engine, _US) < n_before
