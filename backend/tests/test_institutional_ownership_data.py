import asyncio
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import SQLModel, create_engine

import core.data_groups as data_groups
import data.institutional_ownership_data as iod
from clients.fmp_client import fmp_client
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
    test_engine = _fresh_engine(monkeypatch)
    quarters = _quarters_back(TREND_QUARTERS)
    summary_by_quarter = {qy: _plausible_row() for qy in quarters}
    _patch_common(monkeypatch, summary_by_quarter)

    # First call populates the cache row normally (fresh fetched_at).
    result = asyncio.run(get_institutional_ownership_data("STALE"))
    assert result.data_stale_warning is False

    # Backdate the cached row's fetched_at well past STALE_WARNING_DAYS, and
    # force cache_only so no live refetch resets it.
    from sqlmodel import Session, select

    from core.models import FundamentalsCache

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
