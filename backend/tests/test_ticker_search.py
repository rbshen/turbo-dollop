import core.data_groups as _dg
import asyncio
from datetime import datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine

import data.ticker_search as ticker_search
from core.models import IndexConstituent
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


# --- Ranking: primary listing vs. leveraged ETP / cross-listed lookalike ----


def test_lvmh_search_ranks_the_primary_listing_above_a_leveraged_etp(monkeypatch):
    # The motivating real case: searching "LVMH" used to surface a
    # leveraged tracker product (3LLV.PA) ahead of the real primary listing
    # (MC.PA) purely because FMP happened to return it first/at all in its
    # own raw order. Neither /search-symbol nor /search-name exposes an
    # exchange/security-type field to filter on, so this is a ranking fix
    # (name-prefix tier + a same-tier leveraged-keyword/digit-symbol
    # penalty), not a filter.
    async def fake_search_symbol(query, limit):
        return []

    async def fake_search_name(query, limit):
        # Deliberately returned in the "wrong" (ETP-first) order -- the fix
        # must re-rank regardless of FMP's own raw order, not just happen
        # to preserve an already-correct one.
        return [
            {"symbol": "3LLV.PA", "name": "Leverage Shares 3x Long LVMH ETP Securities", "exchange": "PAR"},
            {"symbol": "MC.PA", "name": "LVMH Moet Hennessy Louis Vuitton SE", "exchange": "PAR"},
        ]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("LVMH"))

    assert [r.symbol for r in results] == ["MC.PA", "3LLV.PA"]


def test_leveraged_product_ranks_below_a_same_tier_primary_listing(monkeypatch):
    # Same-tier tiebreak: both names start with the query (tier alone
    # doesn't resolve this), so it's the leveraged-keyword/digit-symbol
    # penalty specifically doing the work here, not just the name-prefix
    # tier.
    async def fake_search_symbol(query, limit):
        return []

    async def fake_search_name(query, limit):
        return [
            {"symbol": "3AAPL.L", "name": "Apple 3x Long ETP Securities", "exchange": "LSE"},
            {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"},
        ]

    monkeypatch.setattr(ticker_search.fmp_client, "search_symbol", fake_search_symbol)
    monkeypatch.setattr(ticker_search.fmp_client, "search_name", fake_search_name)

    results = asyncio.run(search_tickers("Apple"))

    assert [r.symbol for r in results] == ["AAPL", "3AAPL.L"]


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
