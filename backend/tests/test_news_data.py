import asyncio
from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

import news_data
from models import NewsCache
from news_data import get_news_data

RAW_ARTICLE = {
    "symbol": "AAPL",
    "publishedDate": "2026-08-01 12:45:00",
    "publisher": "The Motley Fool",
    "title": "Some Headline",
    "image": "https://images.financialmodelingprep.com/news/some-headline.jpg",
    "site": "fool.com",
    "text": "A short snippet.",
    "url": "https://www.fool.com/investing/2026/08/01/some-headline/",
}


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(news_data, "engine", test_engine)
    return test_engine


def test_cache_miss_fetches_and_normalizes(monkeypatch):
    _fresh_engine(monkeypatch)
    call_count = {"n": 0}

    async def fake_get_stock_news(ticker, limit):
        call_count["n"] += 1
        return [RAW_ARTICLE]

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", fake_get_stock_news)

    result = asyncio.run(get_news_data("aapl"))

    assert call_count["n"] == 1
    assert result.ticker == "AAPL"
    assert len(result.articles) == 1
    article = result.articles[0]
    assert article.title == "Some Headline"
    assert article.publisher == "The Motley Fool"
    assert article.site == "fool.com"
    assert article.snippet == "A short snippet."
    assert article.url == RAW_ARTICLE["url"]
    assert article.published_at == "2026-08-01 12:45:00"


def test_fresh_cache_row_is_reused_without_refetching(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)

    async def fail_if_called(ticker, limit):
        raise AssertionError("must not refetch while cache is fresh")

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", fail_if_called)

    with Session(test_engine) as session:
        session.add(
            NewsCache(
                ticker="AAPL",
                fetched_at=datetime.now(),
                raw_json="[{\"symbol\": \"AAPL\", \"publishedDate\": \"2026-08-01 12:45:00\", \"publisher\": \"X\", \"title\": \"Cached\", \"image\": null, \"site\": \"x.com\", \"text\": \"cached snippet\", \"url\": \"https://x.com/a\"}]",
            )
        )
        session.commit()

    result = asyncio.run(get_news_data("AAPL"))
    assert len(result.articles) == 1
    assert result.articles[0].title == "Cached"


def test_stale_cache_row_triggers_refetch(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(news_data.settings, "news_cache_ttl_minutes", 20)

    with Session(test_engine) as session:
        session.add(
            NewsCache(
                ticker="AAPL",
                fetched_at=datetime.now() - timedelta(minutes=30),
                raw_json="[]",
            )
        )
        session.commit()

    call_count = {"n": 0}

    async def fake_get_stock_news(ticker, limit):
        call_count["n"] += 1
        return [RAW_ARTICLE]

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", fake_get_stock_news)

    result = asyncio.run(get_news_data("AAPL"))

    assert call_count["n"] == 1
    assert len(result.articles) == 1


def test_fmp_failure_returns_empty_articles_not_an_error(monkeypatch):
    """safe_fetch swallows httpx.HTTPError to {} -- news_data must treat a
    non-list payload as "no articles" rather than crashing on the list
    comprehension in _normalize."""
    _fresh_engine(monkeypatch)

    async def fake_get_stock_news(ticker, limit):
        return {}

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", fake_get_stock_news)

    result = asyncio.run(get_news_data("ZZZZ"))
    assert result.articles == []
