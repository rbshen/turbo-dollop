from sqlmodel import Session, select

from core.data_groups import group_for_statement_type, group_live, master_on
from core.db import engine
from core.models import FundamentalsCache
from core.schemas import RefreshResult
from core.tickers import normalize_ticker


# The score recompute that ticker_refresh runs right after the clear always
# needs these two groups live, whether or not they have cached rows yet.
_REFRESH_ALWAYS_NEEDS = ("profile_quote", "fundamentals")


def groups_blocking_refresh(ticker: str) -> list[str]:
    """Data groups that are not live but that a refresh of `ticker` would
    clear rows from (or re-fetch through). Empty list = safe to refresh.
    If anything is blocking, the refresh must 503 rather than clear only
    part of the cache: a cleared row in an off group can never be
    re-fetched."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        cached_types = set(
            session.exec(select(FundamentalsCache.statement_type).where(FundamentalsCache.ticker == ticker)).all()
        )
    if not master_on():
        return ["master switch (FMP paused)"]
    needed = set(_REFRESH_ALWAYS_NEEDS)
    for statement_type in cached_types:
        group = group_for_statement_type(statement_type)
        if group is not None:  # unmapped types are only subject to the master switch
            needed.add(group)
    return sorted(g for g in needed if not group_live(g))


def clear_ticker_cache(ticker: str) -> RefreshResult:
    """Deletes every FundamentalsCache row for this ticker (all statement
    types/periods), so the next fetch of any kind for this ticker is a cold
    start and hits FMP fresh regardless of the staleness window. Only ever
    touches FundamentalsCache -- never GrowthCatalystNote, which is
    manually-curated user data, not fetched-from-FMP cache.

    Does not itself call FMP. Its only caller, ticker_refresh (main.py),
    triggers the actual fresh fetch immediately afterward via
    compute_ticker_score(cache_only=False) -- covering the score-relevant
    cache keys (step1/2/4/5 + summary) synchronously within the same
    request, so TickerScore is never left stale after a refresh. Every
    other tab's cache keys (Financials' fuller statements, Ratios,
    Segmentation, Analyst Ratings, News) still repopulate lazily the normal
    way, via the frontend's own GETs after this cache-clear. Either path
    reuses the same safe_fetch/get_or_fetch error handling every cold-start
    ticker already goes through -- no new FMP-failure path to handle here."""
    ticker = normalize_ticker(ticker)
    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache).where(FundamentalsCache.ticker == ticker)).all()
        statement_types = sorted({row.statement_type for row in rows})
        cleared = len(rows)
        for row in rows:
            session.delete(row)
        session.commit()

    return RefreshResult(ticker=ticker, cleared_entries=cleared, statement_types=statement_types)
