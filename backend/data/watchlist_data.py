import asyncio

from sqlmodel import Session, select

from core.cache import get_or_fetch, safe_fetch
from core.config import settings
from core.db import engine
from helpers.first import _first
from clients.fmp_client import fmp_client
from core.models import EtfScreenerRow, WatchlistTicker
from core.schemas import EtfWatchlistRowOut, WatchlistExportTickerOut, WatchlistRowOut
from core.tickers import normalize_ticker
from data.etf_screener_data import _row_out as etf_screener_row_out
from data.last_close_data import get_cached_last_closes
from data.step1_data import get_step1_data
from data.ticker_score import compute_ticker_score

# LATEST_YEARS_SHOWN of Step 1's Revenue/Net Income/CFO series back each
# row's mini trend bar chart -- Step1Out's own `years` is 10yr+TTM, more
# than a table cell has room for.
LATEST_YEARS_SHOWN = 5

# _consensus_rating holds a DB session open for the duration of a live FMP
# call (get_or_fetch's own contract -- harmless for a single ticker page,
# but get_watchlist_rows fans this out across every row via asyncio.gather).
# A watchlist with many tickers needing a live consensus-rating fetch at
# once can hold more concurrent sessions than the pool allows (pool_size=5
# + max_overflow=10 = 15, db.py::engine) and raise sqlalchemy.exc.TimeoutError
# instead of responding -- confirmed via a real 29-ticker watchlist. Capped
# well under the pool limit, with headroom for the cache-only reads
# (_cached_exchange, compute_ticker_score, get_step1_data) running
# concurrently alongside these.
_LIVE_FETCH_CONCURRENCY = asyncio.Semaphore(8)

# WatchlistRowOut.consensus_rating is never null: this is the "no rating" placeholder (also what an ETF
# row carries without any FMP call). The table renders it dim, and the sort puts it last.
NO_CONSENSUS_RATING = "N/A"


async def _cached_profile(ticker: str) -> dict:
    # Cache-only read of the same "profile"/"latest" cache entry get_summary
    # already populates (compute_ticker_score's own get_summary(cache_only=
    # True) call, run concurrently with this one) -- no new cache entry, no
    # live FMP call, since get_or_fetch never invokes fetch_fn when
    # cache_only=True. {} for a ticker with no cached profile.
    with Session(engine) as session:
        return _first(
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


def _profile_exchange(profile: dict) -> str | None:
    return profile.get("exchangeShortName") or profile.get("exchange")


async def _cached_exchange(ticker: str) -> str | None:
    # Only needed to build the Export button's EXCHANGE:SYMBOL pairs;
    # TickerScore itself doesn't carry exchange.
    return _profile_exchange(await _cached_profile(ticker))


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
    return grades_consensus.get("consensus") or NO_CONSENSUS_RATING


async def _compose_row(watchlist_ticker: WatchlistTicker, last_close: float | None) -> WatchlistRowOut:
    ticker = normalize_ticker(watchlist_ticker.ticker)
    score, exchange, step1 = await asyncio.gather(
        # cache_only=True: opening the Watchlist page must not trigger a
        # live FMP refetch cascade across every ticker in the list, same
        # reasoning as the Screener page. Returns None for a ticker with no
        # cached profile at all -- that's fine, this row just renders with
        # null score fields (see below).
        compute_ticker_score(ticker, cache_only=True),
        _cached_exchange(ticker),
        # Same cache-only Step1Out compute_ticker_score already runs
        # internally -- re-derived here rather than widening TickerScore's
        # own return shape, since Revenue/Net Income/CFO's raw per-year
        # series aren't otherwise needed by the Screener card TickerScore
        # backs. No new cache entry or FMP call; get_step1_data(cache_only=
        # True) only ever reads FundamentalsCache.
        get_step1_data(ticker, cache_only=True),
    )
    # The one live call per row, made after the cache reads above because it depends on them: a fund has
    # no analyst consensus (FMP answers `[]` for every ETF), so an ETF row skips the call -- and the
    # cached empty row it would write -- and carries the placeholder, which the table renders as a dash.
    # `score` is None only for a ticker with no cached profile, which cannot be known to be an ETF.
    is_etf = bool(score.is_etf) if score else False
    rating = NO_CONSENSUS_RATING if is_etf else await _consensus_rating(ticker)

    years = step1.years[-LATEST_YEARS_SHOWN:]
    revenue = step1.revenue[-LATEST_YEARS_SHOWN:]
    net_income = step1.net_income[-LATEST_YEARS_SHOWN:]
    cfo = step1.cfo[-LATEST_YEARS_SHOWN:] if step1.cfo is not None else None

    return WatchlistRowOut(
        ticker=ticker,
        company_name=score.company_name if score else None,
        sector=score.sector if score else None,
        exchange=exchange,
        years=years,
        revenue=revenue,
        net_income=net_income,
        cfo=cfo,
        moat=score.moat if score else None,
        valuation_verdict=score.valuation_verdict if score else None,
        valuation_source=score.valuation_source if score else None,
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
        quote_currency=score.quote_currency if score else None,
        last_price=last_close,
        reported_currency=score.reported_currency if score else None,
        pe_ratio=score.pe_ratio if score else None,
        beta=score.beta if score else None,
        perf_5y_vs_spy_pct=score.perf_5y_vs_spy_pct if score else None,
        perf_5y_vs_spy_status=score.perf_5y_vs_spy_status if score else None,
        speculative_growth_qualifies=score.speculative_growth_qualifies if score else None,
        weinstein_stage=score.weinstein_stage if score else None,
        weinstein_stage_since_date=score.weinstein_stage_since_date if score else None,
        weinstein_stage_since_is_lower_bound=score.weinstein_stage_since_is_lower_bound if score else None,
        weinstein_ma_slope_pct=score.weinstein_ma_slope_pct if score else None,
        weinstein_vs_ma_pct=score.weinstein_vs_ma_pct if score else None,
        consensus_rating=rating,
        added_at=watchlist_ticker.added_at,
        is_etf=is_etf,
    )


async def get_watchlist_rows(tickers: list[WatchlistTicker]) -> list[WatchlistRowOut]:
    """Composes one row per ticker concurrently (asyncio.gather, both across
    tickers and across the sub-fetches per ticker). compute_ticker_score,
    _cached_exchange, and get_step1_data are all cache-only -- no network
    I/O; _consensus_rating is the only one that ever calls FMP live, and
    only when grades_consensus is stale/missing for that ticker -- for a
    ~20-30 ticker watchlist gather() turns what could be several sequential
    FMP round-trips into one parallel batch rather than N times a single
    round-trip's latency."""
    # One batched DB read of the nightly last close for the whole list (no FMP call).
    last_closes = get_cached_last_closes([normalize_ticker(t.ticker) for t in tickers])
    return list(await asyncio.gather(*[_compose_row(t, last_closes.get(normalize_ticker(t.ticker))) for t in tickers]))


# The numeric/text fields an ETF watchlist row copies from the screener row (EtfWatchlistRowOut minus ticker/exchange).
_ETF_ROW_FIELDS = tuple(f for f in EtfWatchlistRowOut.model_fields if f not in ("ticker", "exchange"))


async def get_etf_watchlist_rows(tickers: list[WatchlistTicker]) -> list[EtfWatchlistRowOut]:
    """The rows of the watchlist named "ETF", in the order of `tickers` (list_watchlist_tickers' added order). STORED data
    only: one select of EtfScreenerRow for the list's tickers (through etf_screener_data._row_out, the one place the
    equity-only Beta rule and the row's value handling live) plus the cache-only profile exchange per ticker. No score
    computation, no Step 1 read, no consensus call, no FMP/network path, no write of any kind. A ticker with no
    EtfScreenerRow (just added, the job has not reached it) is still returned, with None for every figure."""
    names = [normalize_ticker(t.ticker) for t in tickers]
    if not names:
        return []
    with Session(engine) as session:
        stored = {row.ticker: etf_screener_row_out(row) for row in session.exec(select(EtfScreenerRow).where(EtfScreenerRow.ticker.in_(names))).all()}
    exchanges = await asyncio.gather(*[_cached_exchange(name) for name in names])
    rows: list[EtfWatchlistRowOut] = []
    for name, exchange in zip(names, exchanges):
        row = stored.get(name)
        figures = {field: getattr(row, field) for field in _ETF_ROW_FIELDS} if row is not None else {}
        rows.append(EtfWatchlistRowOut(ticker=name, exchange=exchange, **figures))
    return rows



async def get_export_tickers(tickers: list[WatchlistTicker]) -> list[WatchlistExportTickerOut]:
    """The multi-list export's per-ticker payload (GET /api/watchlists/export-data), in the order of `tickers`: the cached
    profile's exchange and sector, from ONE cache-only profile read per ticker. No score, Step 1 or consensus work, no
    FMP/network path, no write. A fund (profile isEtf/isFund) has sector None, the same rule ticker_score.py applies to
    TickerScore.sector (an ETF's profile sector is the sponsor's, not a GICS sector), so the single-list TradingView export
    and this one group alike and an ETF lands in "Other". A ticker with no cached profile has both None."""
    names = [normalize_ticker(t.ticker) for t in tickers]
    profiles = await asyncio.gather(*[_cached_profile(name) for name in names])
    return [
        WatchlistExportTickerOut(
            ticker=name,
            exchange=_profile_exchange(profile),
            sector=None if (profile.get("isEtf") or profile.get("isFund")) else (profile.get("sector") or None),
        )
        for name, profile in zip(names, profiles)
    ]
