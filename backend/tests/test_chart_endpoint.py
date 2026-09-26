import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from analysis.trend_structure.weinstein import resample_to_weekly

import core.main as main
import data.chart_data as chart_data
import data.entry_signal_data as entry_signal_data
import data.liquidity_zone_data as liquidity_zone_data
import data.warren_signal_data as warren_signal_data
from data.chart_events_data import ChartEvents, DividendEvent, EarningsEvent


@pytest.fixture(autouse=True)
def _default_no_chart_events(monkeypatch):
    # get_chart_data fetches earnings/dividends live on every call -- stub it
    # so no endpoint test here makes a real FMP request.
    async def _none(ticker):
        return ChartEvents()

    monkeypatch.setattr(chart_data, "fetch_chart_events", _none)


def _fresh_entry_signal_engine(monkeypatch):
    # StaticPool -- TestClient's request runs the async endpoint on a
    # different thread than this test function (see test_entry_signal_endpoint.py's
    # own comment for the same fix). Empty (no rows added) is enough here --
    # this endpoint's own tests care about the bars/indicators shape, not
    # the entry-signal marker (that's covered by test_chart_data.py).
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(entry_signal_data, "engine", engine)


def _fresh_liquidity_zone_engine(monkeypatch):
    # Same isolation as _fresh_entry_signal_engine above, for
    # data/liquidity_zone_data.py's own independent `engine` reference --
    # without this, get_chart_data's zones/zones_available read would hit
    # the real core.db.engine (see CLAUDE.md's "Ad-hoc reproduction
    # scripts must not touch the real database" section on why every
    # module's own `engine` reference needs its own monkeypatch). Empty is
    # enough here too -- zone-filtering behavior itself is covered by
    # test_chart_data.py.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(liquidity_zone_data, "engine", engine)


def _fresh_warren_signal_engine(monkeypatch):
    # data/warren_signal_data.py's own independent `engine` reference --
    # same isolation rationale as _fresh_entry_signal_engine above, for
    # get_chart_data's new warren_signal_available/warren_signal_markers
    # read.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(warren_signal_data, "engine", engine)


def _fresh_chart_data_engine(monkeypatch):
    # data/chart_data.py holds its own independent `engine` reference too
    # (its historical entry-signal marker query, added alongside this
    # comment, reads TechnicalEntrySignalEvent directly) -- same isolation
    # rationale as the two helpers above. Every test in this file that
    # goes through entry_signal_available=False never actually reaches
    # this query (get_chart_data short-circuits it), but this is added
    # proactively so a future test that DOES exercise it can't silently
    # fall through to the real core.db.engine for a read.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(chart_data, "engine", engine)


def _patch_bars(monkeypatch, n: int = 300):
    """Feeds chart_data's FMP fetch paths from a synthetic daily fixture: the D ranges' direct
    `/historical-price-eod/full` call, and W_4Y's long-history store (chart_data resamples
    those dailies to weekly itself)."""
    index = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    closes = pd.Series([100.0 + i for i in range(n)], index=index)
    df = pd.DataFrame({"open": closes - 0.5, "high": closes + 1.0, "low": closes - 1.0, "close": closes, "volume": 1000}, index=index)
    rows = [
        {"date": ts.strftime("%Y-%m-%d"), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
        for ts, r in df.iloc[::-1].iterrows()
    ]

    async def fake_fmp(ticker, from_date, to_date, group="daily_prices"):
        return rows

    async def fake_long_history(ticker):
        return df

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fake_fmp)
    monkeypatch.setattr(chart_data, "get_long_history", fake_long_history)


def test_endpoint_returns_chart_for_valid_ticker(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)
    _patch_bars(monkeypatch)

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
    assert body["entry_signal_markers"] == []
    assert body["warren_signal_available"] is False
    assert body["warren_signal_markers"] == []
    assert body["zones_available"] is False
    assert body["zones"] == []
    assert body["earnings_markers"] == []
    assert body["dividend_markers"] == []
    assert body["events_source"] is None
    assert body["source"] == "fmp"


def test_endpoint_defaults_to_d_1y_range(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)
    _patch_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart")

    assert response.status_code == 200
    assert response.json()["range"] == "D_1Y"


def test_endpoint_accepts_d_6m_range(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)
    _patch_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "D_6M"})

    assert response.status_code == 200
    body = response.json()
    assert body["range"] == "D_6M"
    assert body["timeframe"] == "daily"
    assert body["chart_available"] is True


def test_endpoint_accepts_w_4y_range(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)
    _patch_bars(monkeypatch, n=365 * 9)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "W_4Y"})

    assert response.status_code == 200
    assert response.json()["timeframe"] == "weekly"


def test_endpoint_rejects_invalid_range_value(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)
    _patch_bars(monkeypatch)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/AAPL/chart", params={"range": "BOGUS"})

    assert response.status_code == 422


def test_endpoint_returns_chart_unavailable_for_a_ticker_with_no_bars(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)

    async def fake_fmp(ticker, from_date, to_date, group="daily_prices"):
        return []

    monkeypatch.setattr(chart_data.fmp_client, "get_historical_price_eod", fake_fmp)

    with TestClient(main.app) as client:
        response = client.get("/api/tickers/ZZZZINVALID/chart")

    assert response.status_code == 200
    body = response.json()
    assert body["chart_available"] is False
    assert body["bars"] == []


def test_endpoint_serializes_earnings_and_dividend_markers(monkeypatch):
    _fresh_entry_signal_engine(monkeypatch)
    _fresh_warren_signal_engine(monkeypatch)
    _fresh_liquidity_zone_engine(monkeypatch)
    _fresh_chart_data_engine(monkeypatch)
    _patch_bars(monkeypatch)
    day = (pd.Timestamp.today().normalize() - pd.offsets.BDay(20)).date()

    async def fake_events(ticker):
        return ChartEvents(
            earnings=[EarningsEvent(day, 1.5, None)],
            dividends=[DividendEvent(day, 0.26)],
            source="fmp",
        )

    monkeypatch.setattr(chart_data, "fetch_chart_events", fake_events)

    with TestClient(main.app) as client:
        body = client.get("/api/tickers/AAPL/chart", params={"range": "D_6M"}).json()

    assert body["events_source"] == "fmp"
    assert body["earnings_markers"] == [
        {"time": day.isoformat(), "event_date": day.isoformat(), "eps_actual": 1.5, "eps_estimated": None}
    ]
    assert body["dividend_markers"] == [{"time": day.isoformat(), "event_date": day.isoformat(), "amount": 0.26}]
