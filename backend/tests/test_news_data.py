import asyncio
import json
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session, SQLModel, create_engine, select

import data.news_data as news_data
from core.models import NewsCache
from data.news_data import get_news_data

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
    """A successful fetch that happens to return a non-list payload (e.g.
    {}) must be treated as "no articles" rather than crashing on the list
    comprehension in _normalize -- distinct from a raised httpx.HTTPError,
    which is covered by the failure tests below."""
    _fresh_engine(monkeypatch)

    async def fake_get_stock_news(ticker, limit):
        return {}

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", fake_get_stock_news)

    result = asyncio.run(get_news_data("ZZZZ"))
    assert result.articles == []


def test_fmp_failure_serves_stale_cache_without_overwriting_it(monkeypatch):
    """Regression test for the cache-corruption bug: a failed fetch used to
    unconditionally overwrite NewsCache with an empty result and a fresh
    fetched_at, wiping real cached news and making the empty result itself
    read as fresh for the next TTL window. A failure must instead serve the
    existing row's real articles and leave the row itself untouched."""
    test_engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(news_data.settings, "news_cache_ttl_minutes", 20)

    stale_fetched_at = datetime.now() - timedelta(minutes=30)
    stale_raw_json = json.dumps([RAW_ARTICLE])
    with Session(test_engine) as session:
        session.add(NewsCache(ticker="AAPL", fetched_at=stale_fetched_at, raw_json=stale_raw_json))
        session.commit()

    async def failing_fetch(ticker, limit):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", failing_fetch)

    result = asyncio.run(get_news_data("AAPL"))

    assert len(result.articles) == 1
    assert result.articles[0].title == "Some Headline"

    with Session(test_engine) as session:
        row = session.exec(select(NewsCache).where(NewsCache.ticker == "AAPL")).first()
    assert row.fetched_at == stale_fetched_at  # untouched, not reset to "now"
    assert row.raw_json == stale_raw_json  # untouched, not overwritten with []


def test_fmp_failure_with_no_prior_cache_returns_empty_without_writing_a_row(monkeypatch):
    """A brand-new ticker with nothing cached yet: a failed fetch must still
    degrade gracefully to an empty feed (no crash, no 502), but must not
    create a poisoned empty cache row -- the next request should retry
    against FMP rather than being stuck on a cached []."""
    test_engine = _fresh_engine(monkeypatch)

    async def failing_fetch(ticker, limit):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(news_data.fmp_client, "get_stock_news", failing_fetch)

    result = asyncio.run(get_news_data("ZZZZ"))

    assert result.articles == []
    with Session(test_engine) as session:
        row = session.exec(select(NewsCache).where(NewsCache.ticker == "ZZZZ")).first()
    assert row is None
