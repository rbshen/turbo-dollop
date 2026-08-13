import asyncio
from datetime import date, timedelta

from sqlmodel import Session, SQLModel, create_engine

import helpers.earnings as earnings_module
from helpers.earnings import most_recent_reported_earnings_date, resolve_most_recent_earnings_date

TODAY = date.today()


def _iso(d: date) -> str:
    return d.isoformat()


def test_most_recent_reported_earnings_date_picks_the_max_past_date():
    rows = [
        {"date": _iso(TODAY - timedelta(days=90)), "epsActual": 1.0},
        {"date": _iso(TODAY - timedelta(days=1)), "epsActual": 1.5},  # most recent reported
        {"date": _iso(TODAY - timedelta(days=180)), "epsActual": 0.9},
    ]
    assert most_recent_reported_earnings_date(rows) == TODAY - timedelta(days=1)


def test_most_recent_reported_earnings_date_ignores_future_rows():
    rows = [
        {"date": _iso(TODAY + timedelta(days=30)), "epsActual": None},  # not yet reported
        {"date": _iso(TODAY - timedelta(days=10)), "epsActual": 2.0},
    ]
    assert most_recent_reported_earnings_date(rows) == TODAY - timedelta(days=10)


def test_most_recent_reported_earnings_date_accepts_revenue_actual_alone():
    # Doesn't strictly require epsActual -- either actual value is enough
    # evidence FMP genuinely posted results for this date.
    rows = [{"date": _iso(TODAY - timedelta(days=2)), "epsActual": None, "revenueActual": 109_000_000_000}]
    assert most_recent_reported_earnings_date(rows) == TODAY - timedelta(days=2)


def test_most_recent_reported_earnings_date_today_counts_as_reported():
    rows = [{"date": _iso(TODAY), "epsActual": 1.5}]
    assert most_recent_reported_earnings_date(rows) == TODAY


def test_most_recent_reported_earnings_date_returns_none_for_all_future_rows():
    # ETFs (SPY, QQQ, ...) never report earnings -- every row FMP returns is
    # all-future with a null epsActual (per _next_earnings_date's own
    # docstring). An empty/all-future response must read as "no signal",
    # never a fabricated date.
    rows = [{"date": _iso(TODAY + timedelta(days=60)), "epsActual": None}]
    assert most_recent_reported_earnings_date(rows) is None


def test_most_recent_reported_earnings_date_rejects_past_dated_placeholder_rows():
    # Real confirmed case: SPY's entire cached /earnings history is
    # past-dated rows with BOTH epsActual and revenueActual null, going back
    # years -- an ETF-shaped placeholder pattern, not real reports. Every
    # one of these must be rejected, not just the newest one, so the
    # function falls back to "no signal" (None) rather than fabricating a
    # years-stale "most recent earnings date".
    rows = [
        {"date": _iso(TODAY - timedelta(days=365 * 2)), "epsActual": None, "revenueActual": None},
        {"date": _iso(TODAY - timedelta(days=365 * 3)), "epsActual": None, "revenueActual": None},
    ]
    assert most_recent_reported_earnings_date(rows) is None


def test_most_recent_reported_earnings_date_skips_unconfirmed_rows_for_a_real_reporter():
    # A ticker with a genuine reporting history AND a stale placeholder-shaped
    # row further back must still pick the real reported date, not None and
    # not the placeholder.
    rows = [
        {"date": _iso(TODAY - timedelta(days=5)), "epsActual": 2.1, "revenueActual": 5_000_000_000},
        {"date": _iso(TODAY - timedelta(days=200)), "epsActual": None, "revenueActual": None},
    ]
    assert most_recent_reported_earnings_date(rows) == TODAY - timedelta(days=5)


def test_most_recent_reported_earnings_date_returns_none_for_empty_list():
    assert most_recent_reported_earnings_date([]) is None


def test_resolve_most_recent_earnings_date_reads_from_cache(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    async def fake_get_earnings(ticker):
        raise AssertionError("must not call FMP -- cache_only=True")

    monkeypatch.setattr(earnings_module.fmp_client, "get_earnings", fake_get_earnings)

    async def run():
        with Session(engine) as session:
            return await resolve_most_recent_earnings_date(session, "AAPL", staleness_days=7, cache_only=True)

    # No cache row exists and cache_only=True -- must return None, not raise.
    result = asyncio.run(run())
    assert result is None


def test_resolve_most_recent_earnings_date_fetches_and_reduces(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    async def fake_get_earnings(ticker):
        return [
            {"date": _iso(TODAY - timedelta(days=3)), "epsActual": 1.2},
            {"date": _iso(TODAY + timedelta(days=90)), "epsActual": None},
        ]

    monkeypatch.setattr(earnings_module.fmp_client, "get_earnings", fake_get_earnings)

    async def run():
        with Session(engine) as session:
            return await resolve_most_recent_earnings_date(session, "AAPL", staleness_days=7, cache_only=False)

    result = asyncio.run(run())
    assert result == TODAY - timedelta(days=3)
