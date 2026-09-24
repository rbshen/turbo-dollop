import asyncio

from sqlmodel import Session

from clients.fmp_client import fmp_client
from core.data_groups import group_live
from core.db import engine
from core.schemas import TickerSearchResult
from core.tickers import normalize_ticker
from pipeline.nightly_fundamentals_fetch import load_full_tracked_universe

SEARCH_RESULT_LIMIT = 10

# Common naming shape for leveraged/inverse tracker products (e.g. Leverage
# Shares/WisdomTree/GraniteShares ETPs) -- confirmed via the motivating
# "LVMH search surfacing 3LLV.PA" case: the real primary listing's company
# name starts with the query, the tracker product's doesn't (its own name
# starts with the provider/product framing instead), so this only ever acts
# as a same-tier tiebreaker below, never overrides a genuine name-prefix
# match into a worse tier.
_LEVERAGED_KEYWORDS = ("leveraged", "inverse", "2x", "3x", "-1x", "-2x", "-3x", "etp", "etn")


def _rank_key(index: int, symbol: str, name: str | None, query: str) -> tuple[int, int, int]:
    """Lower sorts first. `tier` alone decides ranking across genuinely
    different match qualities (an exact symbol match always outranks a
    mere name-prefix match, which always outranks everything else) --
    `penalty` only breaks ties *within* one tier, so a leveraged/inverse
    product's name never gets to leapfrog a clean match in a better tier
    just by also happening to satisfy that tier. `index` preserves each
    endpoint's own relative order as the final tiebreak (symbol_matches
    results already sort before name_matches results at the call site,
    matching the merge order before this function existed)."""
    name_lower = (name or "").lower()
    query_lower = query.lower()

    if symbol.upper() == query.upper():
        tier = 0
    elif name_lower.startswith(query_lower):
        tier = 1
    else:
        tier = 2

    penalty = 0
    if any(keyword in name_lower for keyword in _LEVERAGED_KEYWORDS):
        penalty += 2
    # A leveraged-product ticker commonly carries a leverage-factor digit
    # (e.g. "3LLV") that a plain company-name/ticker query typically
    # doesn't -- a soft signal only, so it's a smaller penalty than the
    # name-keyword check above, and never fires when the query itself has
    # a digit (a genuine digit-bearing ticker search, e.g. "3M").
    if any(char.isdigit() for char in symbol) and not any(char.isdigit() for char in query):
        penalty += 1

    return (tier, penalty, index)


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
    company name" in one box.

    Results are re-ranked (see _rank_key) before dedup so a leveraged/
    inverse ETP or a loosely-matching cross-listing doesn't outrank the
    real primary listing purely because FMP happened to return it first
    (confirmed real case: an "LVMH" search surfacing "3LLV.PA", a Leverage
    Shares 3x tracker, above "MC.PA", the real LVMH listing) -- neither
    /search-symbol nor /search-name exposes an exchange/security-type field
    to filter on directly, so this re-ranks on symbol/name shape instead of
    filtering. symbol_matches are still queried/concatenated ahead of
    name_matches (preserved as this function's own index order into
    _rank_key) so a query that looks like a ticker still wins ties against
    an equally-ranked name match, matching the original design intent.
    Deduped by symbol (best-ranked occurrence wins, not first-seen-in-
    FMP's-raw-order), capped at SEARCH_RESULT_LIMIT total.

    While the profile_quote group is not live, falls back to
    _search_tracked_universe instead of calling FMP directly -- this
    function is the one call site in the app that never went through
    core.cache (deliberately uncached, see above), so it needs its own
    explicit check rather than being covered for free by cache.py's.
    """
    query = query.strip()
    if not query:
        return []

    if not group_live("profile_quote"):
        return _search_tracked_universe(query)

    symbol_matches, name_matches = await asyncio.gather(
        fmp_client.search_symbol(query, SEARCH_RESULT_LIMIT),
        fmp_client.search_name(query, SEARCH_RESULT_LIMIT),
    )

    raw_candidates = (symbol_matches if isinstance(symbol_matches, list) else []) + (
        name_matches if isinstance(name_matches, list) else []
    )

    candidates: list[tuple[tuple[int, int, int], TickerSearchResult]] = []
    for index, raw in enumerate(raw_candidates):
        symbol = raw.get("symbol")
        if not symbol:
            continue
        name = raw.get("name")
        candidates.append(
            (
                _rank_key(index, symbol, name, query),
                TickerSearchResult(symbol=normalize_ticker(symbol), name=name, exchange=raw.get("exchange")),
            )
        )
    candidates.sort(key=lambda pair: pair[0])

    results: list[TickerSearchResult] = []
    seen: set[str] = set()
    for _, result in candidates:
        if result.symbol in seen:
            continue
        seen.add(result.symbol)
        results.append(result)
        if len(results) >= SEARCH_RESULT_LIMIT:
            break

    return results
