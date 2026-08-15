import asyncio

from sqlmodel import Session

from clients.fmp_client import fmp_client
from core.config import settings
from core.db import engine
from core.schemas import TickerSearchResult
from core.tickers import normalize_ticker
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe

SEARCH_RESULT_LIMIT = 10


def _search_tracked_universe(query: str) -> list[TickerSearchResult]:
    """FMP_ENABLED=False fallback -- prefix/substring match against the
    app's own tracked ticker universe (index constituents + ever-viewed +
    watchlisted, see load_full_tracked_universe) instead of FMP's live
    symbol/name search. That function returns bare ticker symbols only, no
    company name, so this only matches the query against the SYMBOL --
    materially narrower than the live path (no name matching), which is
    the expected, accepted tradeoff while FMP is paused rather than 502ing
    on every search."""
    normalized_query = query.strip().upper()
    with Session(engine) as session:
        universe = load_full_tracked_universe(session)

    prefix_matches = [t for t in universe if t.startswith(normalized_query)]
    substring_matches = [t for t in universe if normalized_query in t and t not in prefix_matches]
    matches = (prefix_matches + substring_matches)[:SEARCH_RESULT_LIMIT]
    return [TickerSearchResult(symbol=t) for t in matches]


async def search_tickers(query: str) -> list[TickerSearchResult]:
    """Typeahead search backing the nav search box -- queried against FMP's
    own live ticker universe (not just the app's tracked S&P 500/Dow +
    watchlisted set), per the ticker-search UX investigation.

    /search-symbol and /search-name are two genuinely distinct FMP
    endpoints, not a fallback pair: search-symbol prefix-matches only the
    ticker SYMBOL (a company-name query returns []), while search-name
    substring-matches the company NAME (and does not reliably surface a
    ticker-symbol-prefix match the way search-symbol does). Querying both
    concurrently is the only way to cover "typed a ticker" and "typed a
    company name" in one box. Symbol matches are ranked first (a query
    that looks like a ticker is more likely meant as one), then name
    matches, deduped by symbol, capped at SEARCH_RESULT_LIMIT total.

    While FMP is paused (settings.fmp_enabled=False), falls back to
    _search_tracked_universe instead of calling FMP directly -- this
    function is the one call site in the app that never went through
    core.cache (deliberately uncached, see above), so it needs its own
    explicit check rather than being covered for free by cache.py's.
    """
    query = query.strip()
    if not query:
        return []

    if not settings.fmp_enabled:
        return _search_tracked_universe(query)

    symbol_matches, name_matches = await asyncio.gather(
        fmp_client.search_symbol(query, SEARCH_RESULT_LIMIT),
        fmp_client.search_name(query, SEARCH_RESULT_LIMIT),
    )

    results: list[TickerSearchResult] = []
    seen: set[str] = set()
    for raw in (symbol_matches if isinstance(symbol_matches, list) else []) + (
        name_matches if isinstance(name_matches, list) else []
    ):
        symbol = raw.get("symbol")
        if not symbol:
            continue
        symbol = normalize_ticker(symbol)
        if symbol in seen:
            continue
        seen.add(symbol)
        results.append(
            TickerSearchResult(symbol=symbol, name=raw.get("name"), exchange=raw.get("exchange"))
        )
        if len(results) >= SEARCH_RESULT_LIMIT:
            break

    return results
