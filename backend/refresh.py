from sqlmodel import Session, select

from db import engine
from models import FundamentalsCache
from schemas import RefreshResult


def clear_ticker_cache(ticker: str) -> RefreshResult:
    """Deletes every FundamentalsCache row for this ticker (all statement
    types/periods), so the next fetch of any kind for this ticker is a cold
    start and hits FMP fresh regardless of the staleness window. Only ever
    touches FundamentalsCache -- never GrowthCatalystNote, which is
    manually-curated user data, not fetched-from-FMP cache.

    Does not itself call FMP: the "fresh fetch" happens naturally the next
    time any of the existing GET endpoints are hit (which is exactly what
    the frontend does immediately after calling this), reusing the same
    safe_fetch/get_or_fetch error handling every cold-start ticker already
    goes through -- no new FMP-failure path to handle here."""
    ticker = ticker.upper()
    with Session(engine) as session:
        rows = session.exec(select(FundamentalsCache).where(FundamentalsCache.ticker == ticker)).all()
        statement_types = sorted({row.statement_type for row in rows})
        cleared = len(rows)
        for row in rows:
            session.delete(row)
        session.commit()

    return RefreshResult(ticker=ticker, cleared_entries=cleared, statement_types=statement_types)
