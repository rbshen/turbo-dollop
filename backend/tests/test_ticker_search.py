import asyncio

import pytest

import data.ticker_search as ticker_search
from data.ticker_search import search_tickers


def test_merges_and_dedupes_symbol_and_name_matches(monkeypatch):
    async def fake_search_symbol(query, limit):
        return [
            {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
            {"symbol": "AAPD", "name": "Direxion Daily AAPL Bear 1X ETF", "exchange": "NASDAQ"},
        ]

    async def fake_search_name(query, limit):
        return [
            # Same symbol as a search-symbol hit above -- must not be
            # duplicated in the merged result.
            {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
            {"symbol": "APLY", "name": "YieldMax AAPL Option Income Strategy ETF", "exchange": "AMEX"},
        ]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("AAP"))

    symbols = [r.symbol for r in results]
    assert symbols == ["AAPL", "AAPD", "APLY"]  # symbol matches ranked first, AAPL deduped
    assert results[0].name == "Apple Inc."
    assert results[0].exchange == "NASDAQ"


def test_normalizes_dot_notation_symbol_from_fmp_response(monkeypatch):
    # FMP's own search endpoints already return the hyphen form for
    # BRK-B/BF-B in practice, but a dot-notation symbol from any FMP
    # response shape must still normalize -- this is the search-side half
    # of the same choke point the Wikipedia scraper uses on the other side.
    async def fake_search_symbol(query, limit):
        return [{"symbol": "BRK.B", "name": "Berkshire Hathaway Inc.", "exchange": "NYSE"}]

    async def fake_search_name(query, limit):
        return []

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("BRK"))
    assert [r.symbol for r in results] == ["BRK-B"]


def test_caps_at_search_result_limit(monkeypatch):
    async def fake_search_symbol(query, limit):
        return [{"symbol": f"SYM{i}", "name": f"Company {i}", "exchange": "NYSE"} for i in range(limit)]

    async def fake_search_name(query, limit):
        return [{"symbol": f"NAME{i}", "name": f"Company {i}", "exchange": "NYSE"} for i in range(limit)]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("A"))
    assert len(results) == ticker_search.SEARCH_RESULT_LIMIT


def test_empty_query_returns_empty_without_calling_fmp(monkeypatch):
    async def fail_if_called(*args, **kwargs):
        raise AssertionError("should not call FMP for an empty/whitespace query")

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fail_if_called)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fail_if_called)

    assert asyncio.run(search_tickers("")) == []
    assert asyncio.run(search_tickers("   ")) == []


def test_tolerates_one_endpoint_returning_a_non_list_shape(monkeypatch):
    # A malformed/unexpected FMP response on one of the two endpoints
    # shouldn't take down the whole search -- mirrors safe_fetch's own
    # defensive-shape handling elsewhere in this codebase.
    async def fake_search_symbol(query, limit):
        return [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}]

    async def fake_search_name(query, limit):
        return {}

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("AAPL"))
    assert [r.symbol for r in results] == ["AAPL"]


def test_propagates_fmp_http_errors(monkeypatch):
    import httpx

    async def failing(query, limit):
        raise httpx.ConnectTimeout("connect timed out")

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", failing)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", failing)

    with pytest.raises(httpx.HTTPError):
        asyncio.run(search_tickers("AAPL"))
