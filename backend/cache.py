import json
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlmodel import Session, select

from models import FundamentalsCache


async def get_or_fetch(
    session: Session,
    ticker: str,
    statement_type: str,
    period: str,
    fetch_fn: Callable[[], Awaitable[dict | list]],
    staleness_days: int,
) -> dict | list:
    row = session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.statement_type == statement_type,
            FundamentalsCache.period == period,
        )
    ).first()

    now = datetime.now()
    if row and now - row.fetched_at < timedelta(days=staleness_days):
        return json.loads(row.raw_json)

    data = await fetch_fn()
    raw_json = json.dumps(data)

    if row:
        row.raw_json = raw_json
        row.fetched_at = now
    else:
        row = FundamentalsCache(
            ticker=ticker,
            statement_type=statement_type,
            period=period,
            fetched_at=now,
            raw_json=raw_json,
        )
    session.add(row)
    session.commit()
    return data
