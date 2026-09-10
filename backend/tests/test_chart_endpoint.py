import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

import core.main as main
import data.chart_data as chart_data
import data.entry_signal_data as entry_signal_data


def _fresh_entry_signal_engine(monkeypatch):
    # StaticPool -- TestClient's request runs the async endpoint on a
    # different thread than this test function (see test_entry_signal_endpoint.py's
    # own comment for the same fix). Empty (no rows added) is enough here --
    # this endpoint's own tests care about the bars/indicators shape, not
    # the entry-signal marker (that's covered by test_chart_data.py).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(entry_signal_data, "engine", engine)


def _patch_fmp_bars(monkeypatch, n: int = 300):
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    closes = pd.Series([100.0 + i for i in range(n)], index=index)
    df = pd.DataFrame(
        {"open": closes - 0.5, "high": closes + 1.0, "low": closes - 1.0, "close": closes, "volume": 1000}, index=index
    )

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {tickers[0]: df}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)


def test_endpoint_returns_chart_for_valid_ticker(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _patch_fmp_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "D_1Y"})

    assert response.status_code == 200
    body = response.json()
    assert body["range"] == "D_1Y"
    assert body["timeframe"] == "daily"
    assert body["chart_available"] is True
    assert len(body["bars"]) > 0
    assert len(body["sma200"]) > 0
    assert "ema21" in body and len(body["ema21"]) > 0
    assert "sma20" not in body
    assert body["entry_signal_available"] is False
    assert body["entry_signal_marker"] is None
    assert body["source"] == "fmp"


def test_endpoint_defaults_to_d_1y_range(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _patch_fmp_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart")

    assert response.status_code == 200
    assert response.json()["range"] == "D_1Y"


def test_endpoint_accepts_d_6m_range(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _patch_fmp_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "D_6M"})

    assert response.status_code == 200
    body = response.json()
    assert body["range"] == "D_6M"
    assert body["timeframe"] == "daily"
    assert body["chart_available"] is True


def test_endpoint_accepts_w_4y_range(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _patch_fmp_bars(monkeypatch, n=365 * 9)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "W_4Y"})

    assert response.status_code == 200
    assert response.json()["timeframe"] == "weekly"


def test_endpoint_rejects_invalid_range_value(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _patch_fmp_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "BOGUS"})

    assert response.status_code == 422


def test_endpoint_returns_chart_unavailable_for_a_ticker_with_no_bars(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    monkeypatch.setattr(chart_data.settings, "fmp_enabled", True)

    async def fake_get_daily_bars(self, tickers, lookback_years):
        return {}

    monkeypatch.setattr(chart_data.FMPDailyBarSource, "get_daily_bars", fake_get_daily_bars)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/ZZZZINVALID/chart")

    assert response.status_code == 200
    body = response.json()
    assert body["chart_available"] is False
    assert body["bars"] == []
