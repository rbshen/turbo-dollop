import json
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from clients.alpha_vantage_client import AlphaVantageThrottled, alpha_vantage_client
from core.config import settings
from core.db import engine
from core.models import NewsSentimentCache
from core.schemas import NewsSentimentArticle, NewsSentimentOut, SentimentDistribution

logger = logging.getLogger(__name__)

_LABEL_TO_FIELD = {
    "Bearish": "bearish",
    "Somewhat-Bearish": "somewhat_bearish",
    "Neutral": "neutral",
    "Somewhat-Bullish": "somewhat_bullish",
    "Bullish": "bullish",
}


def _parse_time_published(raw: str) -> str:
    return datetime.strptime(raw, "%Y%m%dT%H%M%S").isoformat()


def _normalize(ticker: str, raw: dict) -> tuple[list[NewsSentimentArticle], SentimentDistribution]:
    feed = raw.get("feed", []) if isinstance(raw, dict) else []
    counts = {field: 0 for field in _LABEL_TO_FIELD.values()}
    articles: list[NewsSentimentArticle] = []

    for item in feed:
        ticker_entry = next(
            (t for t in item.get("ticker_sentiment", []) if t.get("ticker") == ticker),
            None,
        )
        if ticker_entry is None:
            # We requested tickers=<ticker>, so this shouldn't normally
            # happen -- skip defensively rather than fabricating a
            # ticker-specific score AV never actually returned.
            continue

        label = ticker_entry.get("ticker_sentiment_label", "Neutral")
        counts[_LABEL_TO_FIELD.get(label, "neutral")] += 1

        articles.append(
            NewsSentimentArticle(
                title=item["title"],
                url=item["url"],
                source=item.get("source", ""),
                published_at=_parse_time_published(item["time_published"]),
                summary=item.get("summary", ""),
                overall_sentiment_score=float(item["overall_sentiment_score"]),
                overall_sentiment_label=item["overall_sentiment_label"],
                ticker_relevance_score=float(ticker_entry["relevance_score"]),
                ticker_sentiment_score=float(ticker_entry["ticker_sentiment_score"]),
                ticker_sentiment_label=label,
            )
        )

    articles.sort(key=lambda a: a.published_at, reverse=True)
    return articles, SentimentDistribution(**counts)


async def get_news_sentiment_data(ticker: str) -> NewsSentimentOut:
    ticker = ticker.upper()
    now = datetime.now()

    with Session(engine) as session:
        row = session.exec(select(NewsSentimentCache).where(NewsSentimentCache.ticker == ticker)).first()
        if row and now - row.fetched_at < timedelta(minutes=settings.news_sentiment_cache_ttl_minutes):
            raw = json.loads(row.raw_json)
            articles, distribution = _normalize(ticker, raw)
            return NewsSentimentOut(ticker=ticker, articles=articles, distribution=distribution)

        try:
            data = await alpha_vantage_client.get_news_sentiment(ticker)
        except AlphaVantageThrottled as exc:
            logger.warning("Alpha Vantage throttled for %s: %s", ticker, exc)
            if row is None:
                # No fallback available -- this must propagate as a
                # distinct error, not collapse into an empty article list
                # that would read identically to "no AV coverage for this
                # ticker." Never cache a throttled response either way.
                raise
            raw = json.loads(row.raw_json)
            articles, distribution = _normalize(ticker, raw)
            return NewsSentimentOut(ticker=ticker, articles=articles, distribution=distribution)
        except httpx.HTTPError as exc:
            # Matches news_data.py's existing convention for a genuine
            # fetch failure (distinct from a throttle, which is a clean
            # 200): fall back to an empty feed rather than erroring.
            logger.warning("Alpha Vantage fetch failed for %s: %s", ticker, exc)
            data = {}

        raw_json = json.dumps(data)
        stmt = sqlite_insert(NewsSentimentCache).values(ticker=ticker, fetched_at=now, raw_json=raw_json)
        stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_={"raw_json": raw_json, "fetched_at": now})
        session.execute(stmt)
        session.commit()

    articles, distribution = _normalize(ticker, data)
    return NewsSentimentOut(ticker=ticker, articles=articles, distribution=distribution)
