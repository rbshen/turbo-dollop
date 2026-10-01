import core.data_groups as _dg
import asyncio
from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.ticker_search as ticker_search
from core.models import IndexConstituent
from data.ticker_search import search_tickers


@pytest.fixture(autouse=True)
def _isolated_search_engine(monkeypatch):
    """search_tickers marks known ETFs from the local DB (data.etf_data.known_etf_tickers): every test
    gets an empty in-memory one so none reads the real database."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(ticker_search, "engine", engine)
    return engine


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


# --- Ranking: primary listing vs. leveraged ETP / cross-listed lookalike ----


def test_leveraged_etp_ranks_below_the_primary_listing_even_when_returned_first(monkeypatch):
    # A leveraged tracker product must not outrank the real primary listing
    # purely because FMP returned it first. The endpoints expose no
    # security-type field, so this is a ranking rule (name-prefix tier + a
    # same-tier leveraged-keyword/digit-symbol penalty), not a filter.
    async def fake_search_symbol(query, limit):
        return []

    async def fake_search_name(query, limit):
        return [
            {"symbol": "3AAPL", "name": "Apple 3x Long ETP Securities", "exchange": "NASDAQ"},
            {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
        ]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("Apple"))

    assert [r.symbol for r in results] == ["AAPL", "3AAPL"]


def test_non_us_listings_are_dropped_from_results(monkeypatch):
    # Fathom does not support non-US tickers: a foreign primary listing
    # (HSBA.L, 0005.HK, MC.PA) must never reach the results, while the US
    # ADR/OTC/ETF listings of the same names do.
    async def fake_search_symbol(query, limit):
        return [
            {"symbol": "HSBC", "name": "HSBC Holdings plc", "exchange": "NYSE"},
            {"symbol": "HSBA.L", "name": "HSBC Holdings plc", "exchange": "LSE"},
            {"symbol": "0005.HK", "name": "HSBC Holdings plc", "exchange": "HKSE"},
        ]

    async def fake_search_name(query, limit):
        return [
            {"symbol": "HBCYF", "name": "HSBC Holdings plc", "exchange": "OTC"},
            {"symbol": "HBC1.DE", "name": "HSBC Holdings plc", "exchange": "XETRA"},
        ]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("HSBC"))

    assert sorted(r.symbol for r in results) == ["HBCYF", "HSBC"]


def test_exact_symbol_match_always_outranks_a_mere_name_prefix_match(monkeypatch):
    async def fake_search_symbol(query, limit):
        return [{"symbol": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ"}]

    async def fake_search_name(query, limit):
        return [{"symbol": "MSFU", "name": "MSFT-adjacent leveraged fund", "exchange": "NASDAQ"}]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("MSFT"))

    assert [r.symbol for r in results] == ["MSFT", "MSFU"]


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


def test_fmp_disabled_falls_back_to_tracked_universe_without_calling_fmp(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(IndexConstituent(index_name="sp500", ticker="AAPL", company_name="Apple", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="sp500", ticker="AAPD", company_name="Direxion Daily AAPL Bear 1X ETF", last_synced_at=datetime.now()))
        session.add(IndexConstituent(index_name="sp500", ticker="MSFT", company_name="Microsoft", last_synced_at=datetime.now()))
        session.commit()

    monkeypatch.setattr(ticker_search, "engine", engine)
    _dg.set_master(False)

    async def fail_if_called(query, limit):
        raise AssertionError("must not call FMP while FMP_ENABLED is False")

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fail_if_called)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fail_if_called)

    results = asyncio.run(search_tickers("aap"))

    # load_full_tracked_universe returns a sorted list, so matches come back
    # alphabetically (AAPD before AAPL) rather than any relevance ranking --
    # MSFT correctly excluded (doesn't match the "AAP" prefix/substring).
    assert [r.symbol for r in results] == ["AAPD", "AAPL"]
    assert results[0].name is None  # no company-name data available locally


def test_fmp_disabled_empty_query_returns_empty_without_touching_the_db(monkeypatch):
    _dg.set_master(False)

    def fail_if_called(session):
        raise AssertionError("should not reach the tracked-universe fallback for an empty query")

    monkeypatch.setattr(ticker_search, "load_full_tracked_universe", fail_if_called)

    assert asyncio.run(search_tickers("")) == []
