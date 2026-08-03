import asyncio

from sqlmodel import Session

from cache import force_fetch, get_or_fetch, safe_fetch
from config import settings
from db import engine
from first import _first
from fmp_client import fmp_client
from models import WatchlistTicker
from schemas import WatchlistRowOut
from ticker_score import compute_ticker_score

# _live_quote and _consensus_rating each hold a DB session open for the
# duration of a live FMP call (get_or_fetch/force_fetch's own contract --
# harmless for a single ticker page, but get_watchlist_rows fans this out
# across every row via asyncio.gather). A watchlist with many tickers
# needing a live fetch on both paths at once can hold more concurrent
# sessions than the pool allows (pool_size=5 + max_overflow=10 = 15,
# db.py::engine) and raise sqlalchemy.exc.TimeoutError instead of
# responding -- confirmed via a real 29-ticker watchlist once
# _consensus_rating started fetching live too. Capped well under the pool
# limit, with headroom for the cache-only reads (_cached_exchange,
# compute_ticker_score) running concurrently alongside these.
_LIVE_FETCH_CONCURRENCY = asyncio.Semaphore(8)


async def _cached_exchange(ticker: str) -> str | None:
    # Cache-only read of the same "profile"/"latest" cache entry get_summary
    # already populates (compute_ticker_score's own get_summary(cache_only=
    # True) call, run concurrently with this one) -- no new cache entry, no
    # live FMP call, since get_or_fetch never invokes fetch_fn when
    # cache_only=True. Only needed to build the Export button's
    # EXCHANGE:SYMBOL pairs; TickerScore itself doesn't carry exchange.
    with Session(engine) as session:
        profile = _first(
            await safe_fetch(
                "profile",
                get_or_fetch(
                    session,
                    ticker,
                    "profile",
                    "latest",
                    lambda: fmp_client.get_profile(ticker),
                    settings.cache_staleness_days,
                    True,
                ),
            )
        )
    return profile.get("exchangeShortName") or profile.get("exchange")


async def _live_quote(ticker: str) -> dict:
    # A targeted force_fetch on just the "quote" cache key -- NOT a full
    # get_summary(ticker, cache_only=False) call, which would also
    # re-trigger a live refetch cascade of every other stale-per-the-
    # staleness-window field (profile, ratios, earnings, balance sheet,
    # ...) bundled into that function. Same "quote"/"latest" cache key
    # get_summary/get_analyst_ratings_data already share, so this doesn't
    # add a new cache entry, just refreshes the shared one.
    async with _LIVE_FETCH_CONCURRENCY:
        with Session(engine) as session:
            return _first(
                await safe_fetch(
                    "quote", force_fetch(session, ticker, "quote", "latest", lambda: fmp_client.get_quote(ticker))
                )
            )


async def _consensus_rating(ticker: str) -> str:
    # Targeted get_or_fetch on just the "grades_consensus" cache key --
    # deliberately NOT the full get_analyst_ratings_data(cache_only=True),
    # which reads 3 more cache keys this row doesn't use (price_target_
    # consensus, grades_historical, quote) and, being cache_only, never
    # populates grades_consensus itself -- a ticker whose Ratings tab has
    # never been opened stayed "N/A" forever. This fetches live but subject
    # to the normal staleness window (get_or_fetch cache_only=False, not
    # force_fetch -- a consensus rating doesn't need _live_quote's
    # every-load freshness), so it's a one-time live call per stale/missing
    # ticker and a cache hit on every subsequent watchlist load.
    async with _LIVE_FETCH_CONCURRENCY:
        with Session(engine) as session:
            grades_consensus = _first(
                await safe_fetch(
                    "grades_consensus",
                    get_or_fetch(
                        session,
                        ticker,
                        "grades_consensus",
                        "latest",
                        lambda: fmp_client.get_grades_consensus(ticker),
                        settings.cache_staleness_days,
                        False,
                    ),
                )
            )
    return grades_consensus.get("consensus") or "N/A"


async def _compose_row(watchlist_ticker: WatchlistTicker) -> WatchlistRowOut:
    ticker = watchlist_ticker.ticker.upper()
    score, rating, quote, exchange = await asyncio.gather(
        # cache_only=True: opening the Watchlist page must not trigger a
        # live FMP refetch cascade across every ticker in the list, same
        # reasoning as the Screener page. Returns None for a ticker with no
        # cached profile at all -- that's fine, this row just renders with
        # null score fields (see below).
        compute_ticker_score(ticker, cache_only=True),
        _consensus_rating(ticker),
        _live_quote(ticker),
        _cached_exchange(ticker),
    )

    return WatchlistRowOut(
        ticker=ticker,
        company_name=score.company_name if score else None,
        sector=score.sector if score else None,
        exchange=exchange,
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
        consensus_rating=rating,
        added_at=watchlist_ticker.added_at,
    )


async def get_watchlist_rows(tickers: list[WatchlistTicker]) -> list[WatchlistRowOut]:
    """Composes one row per ticker concurrently (asyncio.gather, both across
    tickers and across the 4 sub-fetches per ticker). compute_ticker_score's
    cache-only call does no network I/O; the live quote always does, and
    _consensus_rating does whenever grades_consensus is stale/missing for
    that ticker -- for a ~20-30 ticker watchlist gather() turns what could be
    several sequential FMP round-trips per row into one parallel batch
    rather than N times a single round-trip's latency."""
    return list(await asyncio.gather(*[_compose_row(t) for t in tickers]))
