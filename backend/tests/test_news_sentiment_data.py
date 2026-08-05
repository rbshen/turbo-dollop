import asyncio
from datetime import datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine

import data.news_sentiment_data as news_sentiment_data
from alpha_vantage_client import AlphaVantageThrottled
from models import NewsSentimentCache
from data.news_sentiment_data import get_news_sentiment_data


def _article(ticker: str = "AMZN", **overrides) -> dict:
    base = {
        "title": "Amazon Stock Rally Cools After Hours",
        "url": "https://www.benzinga.com/markets/tech/26/08/amazon-stock",
        "time_published": "20260804T040508",
        "source": "Benzinga",
        "summary": "Amazon founder Jeff Bezos plans to sell shares...",
        "overall_sentiment_score": -0.130761,
        "overall_sentiment_label": "Neutral",
        "ticker_sentiment": [
            {
                "ticker": ticker,
                "relevance_score": "1.000000",
                "ticker_sentiment_score": "-0.114585",
                "ticker_sentiment_label": "Neutral",
            }
        ],
    }
    base.update(overrides)
    return base


def _feed(*articles: dict) -> dict:
    return {
        "items": str(len(articles)),
        "sentiment_score_definition": "...",
        "relevance_score_definition": "...",
        "feed": list(articles),
    }


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(news_sentiment_data, "engine", test_engine)
    return test_engine


def test_cache_miss_fetches_and_normalizes(monkeypatch):
    _fresh_engine(monkeypatch)
    call_count = {"n": 0}

    async def fake_get_news_sentiment(ticker):
        call_count["n"] += 1
        return _feed(_article(), _article(overall_sentiment_label="Bullish"))

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fake_get_news_sentiment)

    result = asyncio.run(get_news_sentiment_data("amzn"))

    assert call_count["n"] == 1
    assert result.ticker == "AMZN"
    assert len(result.articles) == 2
    article = result.articles[0]
    assert article.title == "Amazon Stock Rally Cools After Hours"
    assert article.source == "Benzinga"
    assert article.published_at == "2026-08-04T04:05:08"
    assert article.overall_sentiment_score == -0.130761
    assert article.ticker_relevance_score == 1.0
    assert article.ticker_sentiment_score == -0.114585
    assert article.ticker_sentiment_label == "Neutral"
    assert result.distribution.neutral == 2
    assert result.distribution.bearish == 0


def test_fresh_cache_row_is_reused_without_refetching(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)

    async def fail_if_called(ticker):
        raise AssertionError("must not refetch while cache is fresh")

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fail_if_called)

    import json

    with Session(test_engine) as session:
        session.add(
            NewsSentimentCache(
                ticker="AMZN",
                fetched_at=datetime.now(),
                raw_json=json.dumps(_feed(_article(title="Cached Headline"))),
            )
        )
        session.commit()

    result = asyncio.run(get_news_sentiment_data("AMZN"))
    assert len(result.articles) == 1
    assert result.articles[0].title == "Cached Headline"


def test_stale_cache_row_triggers_refetch(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(news_sentiment_data.settings, "news_sentiment_cache_ttl_minutes", 720)

    import json

    with Session(test_engine) as session:
        session.add(
            NewsSentimentCache(
                ticker="AMZN",
                fetched_at=datetime.now() - timedelta(minutes=800),
                raw_json=json.dumps(_feed()),
            )
        )
        session.commit()

    call_count = {"n": 0}

    async def fake_get_news_sentiment(ticker):
        call_count["n"] += 1
        return _feed(_article(title="Fresh Headline"))

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fake_get_news_sentiment)

    result = asyncio.run(get_news_sentiment_data("AMZN"))

    assert call_count["n"] == 1
    assert len(result.articles) == 1
    assert result.articles[0].title == "Fresh Headline"


def test_throttle_with_no_cache_reraises(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_throttled(ticker):
        raise AlphaVantageThrottled("Please consider spreading out your free API requests more sparingly")

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fake_throttled)

    try:
        asyncio.run(get_news_sentiment_data("AMZN"))
        raised = False
    except AlphaVantageThrottled:
        raised = True
    assert raised


def test_throttle_with_stale_cache_serves_stale_copy_and_does_not_overwrite(monkeypatch):
    test_engine = _fresh_engine(monkeypatch)
    monkeypatch.setattr(news_sentiment_data.settings, "news_sentiment_cache_ttl_minutes", 720)

    import json

    stale_time = datetime.now() - timedelta(minutes=800)
    stale_raw = json.dumps(_feed(_article(title="Stale But Real Headline")))

    with Session(test_engine) as session:
        session.add(NewsSentimentCache(ticker="AMZN", fetched_at=stale_time, raw_json=stale_raw))
        session.commit()

    async def fake_throttled(ticker):
        raise AlphaVantageThrottled("Please consider spreading out your free API requests more sparingly")

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fake_throttled)

    result = asyncio.run(get_news_sentiment_data("AMZN"))

    assert len(result.articles) == 1
    assert result.articles[0].title == "Stale But Real Headline"

    with Session(test_engine) as session:
        row = session.get(NewsSentimentCache, "AMZN")
        assert row.raw_json == stale_raw
        assert row.fetched_at == stale_time


def test_http_error_returns_empty_articles_not_an_error(monkeypatch):
    import httpx

    _fresh_engine(monkeypatch)

    async def fake_http_error(ticker):
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fake_http_error)

    result = asyncio.run(get_news_sentiment_data("ZZZZ"))
    assert result.articles == []
    assert result.distribution.bearish == 0
    assert result.distribution.neutral == 0


def test_ticker_sentiment_entry_filtered_to_requested_ticker(monkeypatch):
    _fresh_engine(monkeypatch)

    multi_ticker_article = _article(
        ticker_sentiment=[
            {
                "ticker": "AAPL",
                "relevance_score": "0.61",
                "ticker_sentiment_score": "0.10",
                "ticker_sentiment_label": "Neutral",
            },
            {
                "ticker": "AMZN",
                "relevance_score": "0.73",
                "ticker_sentiment_score": "0.24",
                "ticker_sentiment_label": "Somewhat-Bullish",
            },
        ]
    )

    async def fake_get_news_sentiment(ticker):
        return _feed(multi_ticker_article)

    monkeypatch.setattr(news_sentiment_data.alpha_vantage_client, "get_news_sentiment", fake_get_news_sentiment)

    result = asyncio.run(get_news_sentiment_data("AMZN"))

    assert len(result.articles) == 1
    article = result.articles[0]
    assert article.ticker_relevance_score == 0.73
    assert article.ticker_sentiment_score == 0.24
    assert article.ticker_sentiment_label == "Somewhat-Bullish"
    assert result.distribution.somewhat_bullish == 1
