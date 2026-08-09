import asyncio

from clients.fmp_client import fmp_client
from core.schemas import TickerSearchResult

SEARCH_RESULT_LIMIT = 10


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
    """
    query = query.strip()
    if not query:
        return []

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
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        results.append(
            TickerSearchResult(symbol=symbol, name=raw.get("name"), exchange=raw.get("exchange"))
        )
        if len(results) >= SEARCH_RESULT_LIMIT:
            break

    return results
