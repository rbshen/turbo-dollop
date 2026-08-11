import json
from datetime import datetime, timedelta

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from core.cache import safe_fetch
from core.config import settings
from core.db import engine
from clients.fmp_client import fmp_client
from core.models import NewsCache
from core.schemas import NewsArticle, NewsOut
from core.tickers import normalize_ticker

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

        data = await safe_fetch(f"{ticker} stock news", fmp_client.get_stock_news(ticker, ARTICLE_LIMIT))
        raw = data if isinstance(data, list) else []
        raw_json = json.dumps(raw)

        stmt = sqlite_insert(NewsCache).values(ticker=ticker, fetched_at=now, raw_json=raw_json)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_={"raw_json": raw_json, "fetched_at": now})
        session.execute(stmt)
        session.commit()

    return NewsOut(ticker=ticker, articles=_normalize(raw))
