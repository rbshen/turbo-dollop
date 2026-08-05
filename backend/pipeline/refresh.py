from sqlmodel import Session, select

from core.db import engine
from core.models import FundamentalsCache
from core.schemas import RefreshResult


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
    ticker = ticker.upper()
    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache).where(FundamentalsCache.ticker == ticker)).all()
        statement_types = sorted({row.statement_type for row in rows})
        cleared = len(rows)
        for row in rows:
            session.delete(row)
        session.commit()

    return RefreshResult(ticker=ticker, cleared_entries=cleared, statement_types=statement_types)
