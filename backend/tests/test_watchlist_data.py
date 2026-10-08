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
from core.schemas import Step1Out
from data.watchlist_data import get_watchlist_rows


def _score(ticker="AAPL", speculative_growth_qualifies=True, quote_currency=None, reported_currency=None):
    return TickerScore(
        ticker=ticker,
        company_name="Apple Inc.",
        sector="Technology",
        computed_at=datetime(2026, 1, 1),
        speculative_growth_qualifies=speculative_growth_qualifies,
        quote_currency=quote_currency,
        reported_currency=reported_currency,
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

    monkeypatch.setattr(watchlist_data, "compute_ticker_score", fake_compute_ticker_score)
    monkeypatch.setattr(watchlist_data, "_consensus_rating", fake_consensus_rating)
    monkeypatch.setattr(watchlist_data, "_cached_exchange", fake_cached_exchange)
    monkeypatch.setattr(watchlist_data, "get_step1_data", fake_get_step1_data)
    monkeypatch.setattr(watchlist_data, "get_cached_last_closes", lambda tickers: {})


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


def test_quote_currency_flows_into_the_row(monkeypatch):
    # 0700.HK-shaped -- see models.py::TickerScore.quote_currency.
    _patch(monkeypatch, _score(ticker="0700.HK", quote_currency="HKD"))
    ticker = WatchlistTicker(watchlist_id=1, ticker="0700.HK", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].quote_currency == "HKD"


def test_reported_currency_flows_into_the_row_and_matches_quote_currency_independently(monkeypatch):
    # 0700.HK-shaped: reported_currency (CNY, backs the Revenue/Net Income/
    # CFO mini trend chart) and quote_currency (HKD, would back a price/
    # market-cap cell) are genuinely distinct fields -- confirms neither
    # accidentally shadows or falls back to the other.
    _patch(monkeypatch, _score(ticker="0700.HK", quote_currency="HKD", reported_currency="CNY"))
    ticker = WatchlistTicker(watchlist_id=1, ticker="0700.HK", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].reported_currency == "CNY"
    assert rows[0].quote_currency == "HKD"


def test_quote_currency_none_when_no_ticker_score_row(monkeypatch):
    _patch(monkeypatch, None)
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))

    rows = asyncio.run(get_watchlist_rows([ticker]))

    assert rows[0].quote_currency is None
    assert rows[0].reported_currency is None


def test_last_price_is_the_cached_last_close_and_none_when_uncached(monkeypatch):
    _patch(monkeypatch, _score())
    monkeypatch.setattr(watchlist_data, "get_cached_last_closes", lambda tickers: {"AAPL": 187.25})
    rows = asyncio.run(
        get_watchlist_rows(
            [
                WatchlistTicker(watchlist_id=1, ticker="aapl", added_at=datetime(2026, 1, 1)),
                WatchlistTicker(watchlist_id=1, ticker="MSFT", added_at=datetime(2026, 1, 1)),
            ]
        )
    )

    assert [r.last_price for r in rows] == [187.25, None]


def test_an_etf_rows_price_is_the_cached_last_close_the_etf_job_writes(monkeypatch):
    """ETF cutover 2026-10-03: the stock-side last-close job no longer covers ETFs; the nightly ETF job writes their
    TickerLastClose rows, and the Watchlist's price column reads exactly that table (no TickerScore involved)."""
    from datetime import date

    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine, Session

    import data.last_close_data as last_close_data
    from core.models import TickerLastClose

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(last_close_data, "engine", engine)
    with Session(engine) as session:
        session.add(TickerLastClose(ticker="QQQ", close=749.58, as_of_date=date(2026, 10, 2), fetched_at=datetime(2026, 10, 3)))
        session.commit()
    _patch(monkeypatch, _score("QQQ"))
    monkeypatch.setattr(watchlist_data, "get_cached_last_closes", last_close_data.get_cached_last_closes)  # undo _patch's stub

    rows = asyncio.run(get_watchlist_rows([WatchlistTicker(watchlist_id=1, ticker="QQQ", added_at=datetime(2026, 1, 1))]))

    assert rows[0].last_price == 749.58


# --- Stored verdict passthrough ----------------------------------------------------------------------------------------


def _row_for(monkeypatch, score):
    _patch(monkeypatch, score)
    ticker = WatchlistTicker(watchlist_id=1, ticker="AAPL", added_at=datetime(2026, 1, 1))
    return asyncio.run(get_watchlist_rows([ticker]))[0]


def test_the_score_and_verdict_come_from_the_same_stored_row(monkeypatch):
    score = _score()
    score.overall_score = 73
    score.overall_verdict = "Pass with caution"
    row = _row_for(monkeypatch, score)

    assert (row.overall_score, row.overall_verdict) == (73, "Pass with caution")


def test_the_row_carries_no_review_fields(monkeypatch):
    row = _row_for(monkeypatch, _score())

    assert not {"review_status", "review_reasons", "conviction"} & set(type(row).model_fields)
