import httpx
from fastapi.testclient import TestClient

import core.main as main
from core.schemas import TickerSearchResult


def test_search_endpoint_returns_results(monkeypatch):
    async def fake_search_tickers(q):
        assert q == "AAP"
        return [TickerSearchResult(symbol="AAPL", name="Apple Inc.", exchange="NASDAQ")]

    monkeypatch.setattr(main, "search_tickers", fake_search_tickers)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/search", params={"q": "AAP"})

    assert response.status_code == 200
    assert response.json() == [{"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ"}]


def test_search_endpoint_defaults_to_empty_query(monkeypatch):
    async def fake_search_tickers(q):
        assert q == ""
        return []

    monkeypatch.setattr(main, "search_tickers", fake_search_tickers)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/search")

    assert response.status_code == 200
    assert response.json() == []


def test_search_endpoint_502s_on_fmp_outage(monkeypatch):
    async def failing(q):
        raise httpx.ConnectTimeout("connect timed out")

    monkeypatch.setattr(main, "search_tickers", failing)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/search", params={"q": "AAPL"})

    assert response.status_code == 502
