import json
import logging
from datetime import date, datetime, timedelta
from typing import Awaitable, Callable

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.models import FundamentalsCache

logger = logging.getLogger(__name__)

# FMP's own reporting lag after an earnings date -- statement endpoints
# (income/balance/cash-flow statements, ratios, key-metrics, financial-growth,
# revenue segmentation) aren't guaranteed to reflect a just-reported quarter
# the same day the earnings date itself passes. See get_or_fetch_earnings_aware.
EARNINGS_STALENESS_BUFFER_DAYS = 2


def _load_cache_row(session: Session, ticker: str, statement_type: str, period: str) -> FundamentalsCache | None:
    return session.exec(
        select(FundamentalsCache).where(
            FundamentalsCache.ticker == ticker,
            FundamentalsCache.statement_type == statement_type,
            FundamentalsCache.period == period,
        )
    ).first()


def _write_cache_row(
    session: Session, ticker: str, statement_type: str, period: str, data: dict | list, fetched_at: datetime
) -> None:
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
        fetched_at=fetched_at,
        raw_json=raw_json,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "statement_type", "period"],
        set_={"raw_json": raw_json, "fetched_at": fetched_at},
    )
    session.execute(stmt)
    session.commit()


async def get_or_fetch(
    session: Session,
    ticker: str,
    statement_type: str,
    period: str,
    fetch_fn: Callable[[], Awaitable[dict | list]],
    staleness_days: int,
    cache_only: bool = False,
) -> dict | list | None:
    row = _load_cache_row(session, ticker, statement_type, period)

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
    _write_cache_row(session, ticker, statement_type, period, data, now)
    return data


def _is_earnings_aware_stale(
    row: FundamentalsCache, most_recent_earnings_date: date | None, fallback_staleness_days: int
) -> bool:
    """Stale only if a real new earnings date has occurred since this row was
    last fetched, plus EARNINGS_STALENESS_BUFFER_DAYS for FMP's own reporting
    lag -- not the flat calendar window get_or_fetch uses. No earnings signal
    at all (most_recent_earnings_date is None -- no cached /earnings rows, a
    failed fetch, or a ticker FMP has no earnings history for) fails safe to
    the same flat-window check get_or_fetch itself uses, per this feature's
    own fail-safe requirement."""
    now = datetime.now()
    if most_recent_earnings_date is None:
        return now - row.fetched_at >= timedelta(days=fallback_staleness_days)

    cutoff = most_recent_earnings_date + timedelta(days=EARNINGS_STALENESS_BUFFER_DAYS)
    if row.fetched_at.date() >= cutoff:
        # Already fetched at/after the point FMP should have updated -- fresh
        # regardless of how long ago that fetch was. This is the whole point:
        # a ticker that hasn't reported in months stays a cache hit until its
        # next real earnings date, not just for a flat 7 days.
        return False
    # Fetched before the cutoff -- stale only once today has actually reached it.
    return date.today() >= cutoff


async def get_or_fetch_earnings_aware(
    session: Session,
    ticker: str,
    statement_type: str,
    period: str,
    fetch_fn: Callable[[], Awaitable[dict | list]],
    fallback_staleness_days: int,
    most_recent_earnings_date: date | None,
    cache_only: bool = False,
) -> dict | list | None:
    """Like get_or_fetch, but for statement-grain data (income/balance/cash-flow
    statements, ratios, key-metrics, financial-growth, revenue segmentation)
    whose real update cadence is quarterly (tied to the ticker's own earnings
    date), not the flat `fallback_staleness_days` window every other cache key
    uses -- see CLAUDE.md's cache-freshness design note. most_recent_earnings_date
    comes from helpers.earnings.resolve_most_recent_earnings_date, computed once
    per caller from the same /earnings data ticker_summary.py already reads;
    pass None to fall back to the flat window unconditionally (no earnings
    signal available for this ticker)."""
    row = _load_cache_row(session, ticker, statement_type, period)

    if row and not _is_earnings_aware_stale(row, most_recent_earnings_date, fallback_staleness_days):
        return json.loads(row.raw_json)

    if cache_only:
        return json.loads(row.raw_json) if row else None

    data = await fetch_fn()
    _write_cache_row(session, ticker, statement_type, period, data, datetime.now())
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
