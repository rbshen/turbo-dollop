import json
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    cache_only: bool = False,
) -> dict | list | None:
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

    if cache_only:
        # Used by ticker_score.py's recompute path, which must make zero
        # FMP calls -- returns whatever's cached (even if stale) rather
        # than nothing, since a slightly-stale score is still far more
        # useful than no score; a missing row returns None, which every
        # existing call site already treats the same as a failed fetch
        # (see safe_fetch's {} fallback and the `if isinstance(x, list)
        # else []`/`_first` patterns throughout step*_data.py).
        return json.loads(row.raw_json) if row else None

    data = await fetch_fn()
    raw_json = json.dumps(data)

    # Upsert, not a plain insert: two concurrent requests for the same cache
    # key (e.g. TickerHeader and Step1Card both mounting on a fresh ticker
    # page and racing to cache "profile", or React Strict Mode double-firing
    # an effect in dev) can both see a cache miss above and both reach this
    # write. A plain INSERT would raise a UNIQUE constraint violation (500)
    # when the second one lands; ON CONFLICT DO UPDATE makes the write itself
    # atomic, so the loser updates instead of erroring.
    stmt = sqlite_insert(FundamentalsCache).values(
        ticker=ticker,
        statement_type=statement_type,
        period=period,
        fetched_at=now,
        raw_json=raw_json,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "statement_type", "period"],
        set_={"raw_json": raw_json, "fetched_at": now},
    )
    session.execute(stmt)
    session.commit()
    return data


async def force_fetch(
    session: Session,
    ticker: str,
    statement_type: str,
    period: str,
    fetch_fn: Callable[[], Awaitable[dict | list]],
) -> dict | list:
    """Like get_or_fetch, but always calls fetch_fn() and overwrites the
    cache row regardless of fetched_at -- for one-off targeted refreshes
    that must ignore the normal staleness window (e.g. backfilling a cache
    key after a fetch-limit change, see bulk_refresh_step4_annual.py).
    Not used by any live request path -- those all go through get_or_fetch."""
    data = await fetch_fn()
    raw_json = json.dumps(data)
    now = datetime.now()

    stmt = sqlite_insert(FundamentalsCache).values(
        ticker=ticker,
        statement_type=statement_type,
        period=period,
        fetched_at=now,
        raw_json=raw_json,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "statement_type", "period"],
        set_={"raw_json": raw_json, "fetched_at": now},
    )
    session.execute(stmt)
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
