"""Focused test for data/watchlist_data.py's field passthrough -- this
module had no dedicated unit test before (only CRUD endpoint tests in
test_watchlist_endpoints.py exist), so this is scoped to the one thing this
round's change touches: speculative_growth_qualifies flowing from
compute_ticker_score's TickerScore row into WatchlistRowOut, mirroring the
existing moat/perf_5y_vs_spy_status passthrough it sits next to."""

import asyncio
from datetime import datetime

import data.watchlist_data as watchlist_data
from core.models import TickerScore, WatchlistTicker
from core.schemas import Step1Out, TrendAnalysisOut
from data.watchlist_data import get_watchlist_rows


def _score(ticker="AAPL", speculative_growth_qualifies=True):
    return TickerScore(
        ticker=ticker,
        company_name="Apple Inc.",
        sector="Technology",
        computed_at=datetime(2026, 1, 1),
        speculative_growth_qualifies=speculative_growth_qualifies,
    )


def _step1(ticker="AAPL"):
    return Step1Out(
        ticker=ticker,
        years=["TTM"],
        revenue=[1.0],
        net_income=[1.0],
        operating_income=[1.0],
        gross_margin=[1.0],
        net_margin=[1.0],
        score=90,
        verdict="Pass",
        components={},
        weights={},
    )


def _patch(monkeypatch, score):
    async def fake_compute_ticker_score(ticker, cache_only=False):
        return score

    async def fake_consensus_rating(ticker):
        return "N/A"

    async def fake_cached_exchange(ticker):
        return "NASDAQ"

    async def fake_get_step1_data(ticker, cache_only=False):
        return _step1(ticker)

    async def fake_get_trend_analysis_data(ticker, cache_only=False):
        return None  # no TrendAnalysis row -- not the focus of this test file

    monkeypatch.setattr(watchlist_data, "compute_ticker_score", fake_compute_ticker_score)
    monkeypatch.setattr(watchlist_data, "_consensus_rating", fake_consensus_rating)
    monkeypatch.setattr(watchlist_data, "_cached_exchange", fake_cached_exchange)
    monkeypatch.setattr(watchlist_data, "get_step1_data", fake_get_step1_data)
    monkeypatch.setattr(watchlist_data, "get_trend_analysis_data", fake_get_trend_analysis_data)


def test_speculative_growth_qualifies_true_flows_into_the_row(monkeypatch):
    _patch(monkeypatch, _score(speculative_growth_qualifies=True))
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].speculative_growth_qualifies is True


def test_speculative_growth_qualifies_false_flows_into_the_row(monkeypatch):
    _patch(monkeypatch, _score(speculative_growth_qualifies=False))
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].speculative_growth_qualifies is False


def test_speculative_growth_qualifies_none_when_no_ticker_score_row(monkeypatch):
    # compute_ticker_score returns None for a ticker with no cached profile
    # at all -- the row should still render, just with every score field
    # (including this one) null, same convention as moat/perf_5y_vs_spy_status.
    _patch(monkeypatch, None)
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].speculative_growth_qualifies is None


def test_trend_fields_flow_into_the_row_from_trend_analysis(monkeypatch):
    _patch(monkeypatch, _score())

    async def fake_get_trend_analysis_data(ticker, cache_only=False):
        return TrendAnalysisOut(
            ticker=ticker,
            computed_at=datetime(2026, 1, 1),
            trend_state="uptrend",
            magnitude_tier="strong",
            persistence_count=3,
            bars_since_confirmation=2,
            warning_flag=False,
            blended_score=7.5,
            bar_level=5,
            ad_bullish_divergence=True,
        )

    monkeypatch.setattr(watchlist_data, "get_trend_analysis_data", fake_get_trend_analysis_data)
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].bar_level == 5
    assert rows[0].blended_score == 7.5
    assert rows[0].trend_state == "uptrend"
    assert rows[0].ad_bullish_divergence is True


def test_trend_fields_are_none_when_no_trend_analysis_row_yet(monkeypatch):
    # get_trend_analysis_data returns None when the nightly trend cron
    # hasn't computed a row for this ticker yet -- the row should still
    # render, with the trend fields null, same convention as every other
    # None-able field here.
    _patch(monkeypatch, _score())
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].bar_level is None
    assert rows[0].blended_score is None
    assert rows[0].trend_state is None
    assert rows[0].ad_bullish_divergence is None
