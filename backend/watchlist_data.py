import asyncio

from sqlmodel import Session

from analyst_ratings_data import get_analyst_ratings_data
from cache import force_fetch, safe_fetch
from db import engine
from first import _first
from fmp_client import fmp_client
from models import WatchlistTicker
from schemas import WatchlistRowOut
from ticker_score import compute_ticker_score


async def _live_quote(ticker: str) -> dict:
    # A targeted force_fetch on just the "quote" cache key -- NOT a full
    # get_summary(ticker, cache_only=False) call, which would also
    # re-trigger a live refetch cascade of every other stale-per-the-
    # staleness-window field (profile, ratios, earnings, balance sheet,
    # ...) bundled into that function. Same "quote"/"latest" cache key
    # get_summary/get_analyst_ratings_data already share, so this doesn't
    # add a new cache entry, just refreshes the shared one.
    with Session(engine) as session:
        return _first(
            await safe_fetch(
                "quote", force_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker))
            )
        )


async def _compose_row(watchlist_ticker: WatchlistTicker) -> WatchlistRowOut:
    ticker = watchlist_ticker.ticker.upper()
    score, ratings, quote = await asyncio.gather(
        # cache_only=True: opening the Watchlist page must not trigger a
        # live FMP refetch cascade across every ticker in the list, same
        # reasoning as the Screener page. Returns None for a ticker with no
        # cached profile at all -- that's fine, this row just renders with
        # null score fields (see below).
        compute_ticker_score(ticker, cache_only=True),
        get_analyst_ratings_data(ticker, cache_only=True),
        _live_quote(ticker),
    )

    return WatchlistRowOut(
        ticker=ticker,
        company_name=score.company_name if score else None,
        price=quote.get("price"),
        change=quote.get("change"),
        change_percent=quote.get("changePercentage", quote.get("changesPercentage")),
        moat=score.moat if score else None,
        valuation_verdict=score.valuation_verdict if score else None,
        step1_score=score.step1_score if score else None,
        step1_verdict=score.step1_verdict if score else None,
        step2_score=score.step2_score if score else None,
        step2_verdict=score.step2_verdict if score else None,
        step4_score=score.step4_score if score else None,
        step4_verdict=score.step4_verdict if score else None,
        step5_score=score.step5_score if score else None,
        step5_verdict=score.step5_verdict if score else None,
        overall_score=score.overall_score if score else None,
        overall_verdict=score.overall_verdict if score else None,
        market_cap=score.market_cap if score else None,
        pe_ratio=score.pe_ratio if score else None,
        beta=score.beta if score else None,
        consensus_rating=ratings.banner.rating,
        added_at=watchlist_ticker.added_at,
    )


async def get_watchlist_rows(tickers: list[WatchlistTicker]) -> list[WatchlistRowOut]:
    """Composes one row per ticker concurrently (asyncio.gather, both across
    tickers and across the 3 sub-fetches per ticker). The cache-only calls
    (compute_ticker_score, get_analyst_ratings_data) do no network I/O, so
    they don't race each other; the one real network call per ticker (the
    live quote) is what actually benefits from gather -- for a ~20-30
    ticker watchlist this turns N sequential FMP round-trips into one
    parallel batch rather than N times a single round-trip's latency."""
    return list(await asyncio.gather(*[_compose_row(t) for t in tickers]))
