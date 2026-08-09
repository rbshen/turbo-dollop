from fastapi.testclient import TestClient

import core.main as main
from core.exceptions import TickerNotFoundError


def test_summary_endpoint_returns_404_on_ticker_not_found(monkeypatch):
    async def fake_get_summary(ticker):
        raise TickerNotFoundError(ticker)

    monkeypatch.setattr(main, "get_summary", fake_get_summary)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/INVALIDXYZ/summary")

    assert response.status_code == 404
    assert response.json() == {"detail": "Ticker 'INVALIDXYZ' not found"}
