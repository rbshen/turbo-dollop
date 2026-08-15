import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.config import settings
from core.db import engine
from clients.fmp_client import fmp_client
from core.models import NewsCache
from core.schemas import NewsArticle, NewsOut
from core.tickers import normalize_ticker

logger = logging.getLogger(__name__)

# Latest-N feed, not a paginated archive -- see CLAUDE.md's news feature
# scoping (v1 is deliberately simple, no "load more").
ARTICLE_LIMIT = 30


def _normalize(raw: list[dict]) -> list[NewsArticle]:
    return [
        NewsArticle(
            title=item["title"],
            publisher=item["publisher"],
            site=item["site"],
            snippet=item["text"],
            image=item.get("image"),
            url=item["url"],
            published_at=item["publishedDate"],
        )
        for item in raw
    ]


async def get_news_data(ticker: str) -> NewsOut:
    """TTL-cached (`Settings.news_cache_ttl_minutes`) wrapper around FMP's
    /news/stock -- deliberately separate from cache.py::get_or_fetch, which
    is keyed on FundamentalsCache's (ticker, statement_type, period) shape
    and staleness measured in days; news uses its own NewsCache table keyed
    on ticker alone, staleness measured in minutes."""
    ticker = normalize_ticker(ticker)
    now = datetime.now()

    with Session(engine) as session:
        row = session.exec(select(NewsCache).where(NewsCache.ticker == ticker)).first()
        if row and now - row.fetched_at < timedelta(minutes=settings.news_cache_ttl_minutes):
            raw = json.loads(row.raw_json)
            return NewsOut(ticker=ticker, articles=_normalize(raw))

        try:
            data = await fmp_client.get_stock_news(ticker, ARTICLE_LIMIT)
        except httpx.HTTPError as exc:
            # A failed fetch must never overwrite a good cached row with an
            # empty result -- that would wipe real news and, by resetting
            # fetched_at, make the empty result itself read as "fresh" for
            # the next TTL window, repeating on every attempt while FMP is
            # down. Serve whatever's cached (however stale) instead; if
            # nothing is cached yet, fall through to an empty feed without
            # writing anything, so the next request retries rather than
            # being poisoned by this failure.
            logger.warning("FMP fetch failed for %s stock news: %s", ticker, exc)
            if row is not None:
                raw = json.loads(row.raw_json)
                return NewsOut(ticker=ticker, articles=_normalize(raw))
            return NewsOut(ticker=ticker, articles=[])

        raw = data if isinstance(data, list) else []
        raw_json = json.dumps(raw)

        stmt = sqlite_insert(NewsCache).values(ticker=ticker, fetched_at=now, raw_json=raw_json)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_={"raw_json": raw_json, "fetched_at": now})
        session.execute(stmt)
        session.commit()

    return NewsOut(ticker=ticker, articles=_normalize(raw))
