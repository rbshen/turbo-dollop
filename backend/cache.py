import json
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import httpx
from sqlmodel import Session, select

from models import FundamentalsCache

logger = logging.getLogger(__name__)


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


async def safe_fetch(label: str, coro: Awaitable[dict | list]) -> dict | list:
    """Isolate one FMP sub-fetch: a failure here (e.g. an FMP plan lacking
    access to a given endpoint) shouldn't take down the whole request — the
    caller falls back to nulls for whatever fields depended on it."""
    try:
        return await coro
    except httpx.HTTPError as exc:
        logger.warning("FMP fetch failed for %s: %s", label, exc)
        return {}
