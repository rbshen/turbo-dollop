import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import core.data_groups as data_groups
import data.institutional_ownership_data as iod
from clients.fmp_client import fmp_client
from core.models import FundamentalsCache
from data.institutional_ownership_data import (
    TREND_QUARTERS,
    _calendar_quarter,
    _quarter_before,
    get_institutional_ownership_data,
)

# Fathom's own shares-outstanding figure (compute_shares_outstanding prefers
# marketCap/price): 1_000_000_000 / 100 = 10_000_000.
QUOTE = {"marketCap": 1_000_000_000, "price": 100.0}
INCOME_QUARTERLY = [{"weightedAverageShsOutDil": 9_900_000}]


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(iod, "engine", test_engine)
    return test_engine


def _quarters_back(n: int) -> list[tuple[int, int]]:
    """The n most recent calendar quarters (today's first), same walk the
    module itself does -- lets tests build fixtures independent of "today"."""
    out = []
    y, q = _calendar_quarter(date.today())
    for _ in range(n):
        out.append((y, q))
        y, q = _quarter_before(y, q)
    return out


def _plausible_row(*, ownership_percent: float = 66.0, ownership_percent_change: float = 1.0) -> dict:
    # numberOf13Fshares chosen so implied shares-outstanding == 10_000_000
    # exactly (the fixture QUOTE's own figure) -- always passes the
    # divergence leg of the guardrail regardless of ownership_percent's
    # own value, as long as it's within OWNERSHIP_PCT_MAX.
    return {
        "date": "2026-06-30",
        "ownershipPercent": ownership_percent,
        "ownershipPercentChange": ownership_percent_change,
        "investorsHolding": 500,
        "investorsHoldingChange": 10,
        "numberOf13Fshares": 10_000_000 * ownership_percent / 100.0,
        "newPositions": 5,
        "newPositionsChange": 1,
        "increasedPositions": 20,
        "increasedPositionsChange": 2,
        "reducedPositions": 8,
        "reducedPositionsChange": -1,
        "closedPositions": 3,
        "closedPositionsChange": 0,
    }


def _patch_common(monkeypatch, summary_by_quarter: dict[tuple[int, int], dict], holders: list[dict] | None = None):
    holders = holders or []

    async def fake_summary(ticker, year, quarter):
        row = summary_by_quarter.get((year, quarter))
        return [row] if row else []

    async def fake_holders(ticker, year, quarter, page=0, limit=15):
        return holders

    async def fake_quote(ticker):
        return [QUOTE]

    async def fake_income(ticker, period, limit):
        return INCOME_QUARTERLY

    monkeypatch.setattr(fmp_client, "get_institutional_ownership_summary", fake_summary)
    monkeypatch.setattr(fmp_client, "get_institutional_ownership_holders", fake_holders)
    monkeypatch.setattr(fmp_client, "get_quote", fake_quote)
    monkeypatch.setattr(fmp_client, "get_income_statement", fake_income)


def test_normal_ticker_full_read(monkeypatch):
    _fresh_engine(monkeypatch)
    quarters = _quarters_back(TREND_QUARTERS)
    # Rising in 3 of the last 4 quarters -> Accumulating.
    changes = [2.0, 1.0, -0.5, 3.0, 0.1, 0.1, 0.1, 0.1]
    summary_by_quarter = {qy: _plausible_row(ownership_percent_change=c) for qy, c in zip(quarters, changes)}
    holders = [
        {"investorName": "BLACKROCK, INC.", "marketValue": 300, "changeInMarketValuePercentage": 5.0, "sharesNumber": 100, "changeInSharesNumberPercentage": 1.0},
        {"investorName": "VANGUARD", "marketValue": 200, "changeInMarketValuePercentage": -2.0, "sharesNumber": 80, "changeInSharesNumberPercentage": -1.0},
    ]
    _patch_common(monkeypatch, summary_by_quarter, holders)

    result = asyncio.run(get_institutional_ownership_data("AAPL"))

    assert result.enabled is True
    assert result.no_coverage is False
    assert result.ownership_valid is True
    assert result.ownership_percent == 66.0
    assert result.holder_count == 500
    assert result.shares_outstanding == 10_000_000
    assert result.shares_held == pytest.approx(6_600_000)
    assert result.sentiment == "Accumulating"
    assert result.sentiment_rising_count == 3
    assert result.positions is not None
    assert result.positions.opened == 5
    assert result.trend_quarters_shown == TREND_QUARTERS
    assert len(result.trend) == TREND_QUARTERS
    assert len(result.top_holders) == 2
    assert result.top_holders[0].investor_name == "BLACKROCK, INC."
    assert result.note is None
    assert result.data_stale_warning is False


def test_plausibility_guardrail_on_latest_quarter_degrades_stats_but_not_positions_or_holders(monkeypatch):
    _fresh_engine(monkeypatch)
    quarters = _quarters_back(TREND_QUARTERS)
    summary_by_quarter = {qy: _plausible_row() for qy in quarters}
    # ARES-shaped: >98% ownership on the LATEST (anchor) quarter only.
    summary_by_quarter[quarters[0]] = _plausible_row(ownership_percent=100.04)
    holders = [{"investorName": "SOME FUND", "marketValue": 50, "changeInMarketValuePercentage": 1.0, "sharesNumber": 10, "changeInSharesNumberPercentage": 1.0}]
    _patch_common(monkeypatch, summary_by_quarter, holders)

    result = asyncio.run(get_institutional_ownership_data("ARES"))

    assert result.enabled is True
    assert result.no_coverage is False
    assert result.ownership_valid is False
    assert result.ownership_percent is None
    assert result.holder_count is None
    assert result.shares_held is None
    assert result.sentiment is None
    assert result.note is not None
    # The implausible anchor quarter itself is dropped from trend entirely,
    # leaving the other 7 (all plausible).
    assert result.trend_quarters_shown == TREND_QUARTERS - 1
    # Positions/top-holders are computed from the anchor row independently
    # of the plausibility guardrail -- they still render.
    assert result.positions is not None
    assert result.positions.opened == 5
    assert len(result.top_holders) == 1
    assert result.top_holders[0].investor_name == "SOME FUND"


def test_older_quarter_plausibility_failure_only_drops_that_point(monkeypatch):
    _fresh_engine(monkeypatch)
    quarters = _quarters_back(TREND_QUARTERS)
    summary_by_quarter = {qy: _plausible_row() for qy in quarters}
    # Quarter 3 slots back (still older than the anchor) fails on its own.
    summary_by_quarter[quarters[3]] = _plausible_row(ownership_percent=99.0)
    _patch_common(monkeypatch, summary_by_quarter)

    result = asyncio.run(get_institutional_ownership_data("TEST"))

    assert result.ownership_valid is True
    assert result.trend_quarters_shown == TREND_QUARTERS - 1
    assert result.note is None


def test_zero_coverage_ticker(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_common(monkeypatch, summary_by_quarter={})

    result = asyncio.run(get_institutional_ownership_data("CNSWF"))

    assert result.enabled is True
    assert result.no_coverage is True
    assert result.ownership_valid is False
    assert result.trend == []
    assert result.top_holders == []
    assert result.positions is None


def test_group_disabled_makes_zero_fmp_calls(monkeypatch):
    _fresh_engine(monkeypatch)
    calls = {"n": 0}

    async def fail_if_called(*args, **kwargs):
        calls["n"] += 1
        raise AssertionError("should not be called while the group is disabled")

    monkeypatch.setattr(fmp_client, "get_institutional_ownership_summary", fail_if_called)
    monkeypatch.setattr(fmp_client, "get_institutional_ownership_holders", fail_if_called)
    monkeypatch.setattr(fmp_client, "get_quote", fail_if_called)
    monkeypatch.setattr(fmp_client, "get_income_statement", fail_if_called)

    data_groups.set_group_enabled("institutional_ownership", False)

    result = asyncio.run(get_institutional_ownership_data("AAPL"))

    assert result.enabled is False
    assert result.no_coverage is False
    assert calls["n"] == 0


def test_data_stale_warning_true_when_fetched_long_ago(monkeypatch):
    """Confirms as_of_quarter/fetched_at/data_stale_warning are all driven
    by a real FundamentalsCache row's own fetched_at column, re-read
    directly from the DB (get_or_fetch itself doesn't return this
    metadata) -- not a placeholder/computed-at-request-time value."""
    test_engine = _fresh_engine(monkeypatch)
    quarters = _quarters_back(TREND_QUARTERS)
    summary_by_quarter = {qy: _plausible_row() for qy in quarters}
    _patch_common(monkeypatch, summary_by_quarter)

    # First call populates the cache row normally (fresh fetched_at).
    result = asyncio.run(get_institutional_ownership_data("STALE"))
    assert result.data_stale_warning is False
    assert result.fetched_at is not None

    # Backdate the cached row's fetched_at well past STALE_WARNING_DAYS, and
    # force cache_only so no live refetch resets it.
    anchor_label = iod._quarter_label(*quarters[0])
    with Session(test_engine) as session:
        row = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == "STALE",
                FundamentalsCache.statement_type == "institutional_ownership_summary",
                FundamentalsCache.period == anchor_label,
            )
        ).first()
        row.fetched_at = datetime.now() - timedelta(days=200)
        session.add(row)
        session.commit()

    result = asyncio.run(get_institutional_ownership_data("STALE", cache_only=True))
    assert result.data_stale_warning is True
    # And the reported fetched_at itself reflects the backdated value, not
    # a fresh "now" -- proof this is a real column read, not a placeholder.
    assert result.fetched_at is not None and (datetime.now() - result.fetched_at) > timedelta(days=199)


def test_cache_hit_makes_no_live_fmp_call(monkeypatch):
    _fresh_engine(monkeypatch)
    quarters = _quarters_back(TREND_QUARTERS)
    summary_by_quarter = {qy: _plausible_row() for qy in quarters}
    holders = [{"investorName": "X", "marketValue": 1.0, "changeInMarketValuePercentage": 1.0, "sharesNumber": 1.0, "changeInSharesNumberPercentage": 1.0}]
    _patch_common(monkeypatch, summary_by_quarter, holders)

    first = asyncio.run(get_institutional_ownership_data("CACHEHIT"))
    assert first.ownership_valid is True

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("cache should have been fresh -- no live call expected")

    monkeypatch.setattr(fmp_client, "get_institutional_ownership_summary", fail_if_called)
    monkeypatch.setattr(fmp_client, "get_institutional_ownership_holders", fail_if_called)

    second = asyncio.run(get_institutional_ownership_data("CACHEHIT"))
    assert second.ownership_percent == first.ownership_percent
    assert second.fetched_at == first.fetched_at


def test_cache_miss_within_refetch_window_triggers_a_live_call(monkeypatch):
    """Today's own (in-progress) calendar quarter is always well within its
    own ~101-day refetch-grace window (its quarter-end date is still in the
    future), so a row past the flat 7-day staleness clock but still inside
    that window gets a genuine live refetch."""
    test_engine = _fresh_engine(monkeypatch)
    year, quarter = _quarters_back(1)[0]
    calls = {"n": 0}
    row_v1 = _plausible_row(ownership_percent_change=1.0)
    row_v2 = _plausible_row(ownership_percent_change=9.0)

    async def counting_summary(ticker, y, q):
        calls["n"] += 1
        return [row_v1 if calls["n"] == 1 else row_v2]

    monkeypatch.setattr(fmp_client, "get_institutional_ownership_summary", counting_summary)

    with Session(test_engine) as session:
        first = asyncio.run(iod._fetch_summary_quarter(session, "REFETCH", year, quarter, False))
    assert calls["n"] == 1
    assert first[0]["ownershipPercentChange"] == 1.0

    label = iod._quarter_label(year, quarter)
    with Session(test_engine) as session:
        cached = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == "REFETCH",
                FundamentalsCache.statement_type == "institutional_ownership_summary",
                FundamentalsCache.period == label,
            )
        ).first()
        cached.fetched_at = datetime.now() - timedelta(days=10)  # past the flat 7-day clock
        session.add(cached)
        session.commit()

    with Session(test_engine) as session:
        second = asyncio.run(iod._fetch_summary_quarter(session, "REFETCH", year, quarter, False))
    assert calls["n"] == 2  # a genuine live refetch happened
    assert second[0]["ownershipPercentChange"] == 9.0


def test_past_refetch_window_serves_frozen_cache_without_a_live_call(monkeypatch):
    """A long-settled historical quarter (its own ~101-day grace window
    closed years ago) is never live-refetched again once cached, no matter
    how stale the flat clock says it is -- it's served frozen instead."""
    test_engine = _fresh_engine(monkeypatch)
    old_year, old_quarter = 2020, 1  # ended 2020-03-31
    row = _plausible_row()
    calls = {"n": 0}

    async def counting_summary(ticker, y, q):
        calls["n"] += 1
        return [row]

    monkeypatch.setattr(fmp_client, "get_institutional_ownership_summary", counting_summary)

    with Session(test_engine) as session:
        first = asyncio.run(iod._fetch_summary_quarter(session, "OLDQ", old_year, old_quarter, False))
    assert first == [row]
    assert calls["n"] == 1

    label = iod._quarter_label(old_year, old_quarter)
    with Session(test_engine) as session:
        cached = session.exec(
            select(FundamentalsCache).where(
                FundamentalsCache.ticker == "OLDQ",
                FundamentalsCache.statement_type == "institutional_ownership_summary",
                FundamentalsCache.period == label,
            )
        ).first()
        # Well past the flat 7-day staleness clock, which alone would demand
        # a refetch -- the point of this test is that the refetch-grace-window
        # gate overrides that for a quarter this old.
        cached.fetched_at = datetime.now() - timedelta(days=30)
        session.add(cached)
        session.commit()

    with Session(test_engine) as session:
        second = asyncio.run(iod._fetch_summary_quarter(session, "OLDQ", old_year, old_quarter, False))
    assert second == [row]
    assert calls["n"] == 1  # still 1 -- no live refetch was attempted


def test_past_refetch_window_still_fetches_once_if_never_cached(monkeypatch):
    """The grace-window gate only stops REPEATING an attempt -- a quarter
    with no cached row at all yet is always fetched at least once, however
    old it is."""
    _fresh_engine(monkeypatch)
    old_year, old_quarter = 2018, 1
    row = _plausible_row()

    async def fake_summary(ticker, y, q):
        return [row]

    monkeypatch.setattr(fmp_client, "get_institutional_ownership_summary", fake_summary)

    assert iod._past_refetch_window(old_year, old_quarter) is True  # confirms this is genuinely outside the window

    with Session(iod.engine) as session:
        result = asyncio.run(iod._fetch_summary_quarter(session, "NEVERCACHED", old_year, old_quarter, False))
    assert result == [row]


def test_past_refetch_window_helper():
    # 45 (SEC deadline) + 56 (grace) = 101 days past quarter-end.
    quarter_end = date(2024, 3, 31)
    assert iod._past_refetch_window(2024, 1, today=quarter_end + timedelta(days=101)) is False
    assert iod._past_refetch_window(2024, 1, today=quarter_end + timedelta(days=102)) is True
