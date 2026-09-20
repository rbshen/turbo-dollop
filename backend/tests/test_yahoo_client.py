import asyncio

import pandas as pd

import clients.yahoo_client as yahoo_client_module
from clients.yahoo_client import YahooClient


def _sample_ohlcv(n: int = 10) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=dates,
    )


def _fake_multi_ticker_frame(tickers_data: dict) -> pd.DataFrame:
    # Mirrors yfinance's group_by="ticker" shape: a two-level column
    # MultiIndex with ticker as the outer level -- pd.concat with a dict
    # produces this even for a single-entry dict.
    return pd.concat(tickers_data, axis=1)


def test_get_history_batch_calls_yf_download_once_for_multiple_tickers(monkeypatch):
    call_count = {"n": 0}

    def fake_download(tickers, **kwargs):
        call_count["n"] += 1
        return _fake_multi_ticker_frame({"AAPL": _sample_ohlcv(), "MSFT": _sample_ohlcv()})

    monkeypatch.setattr(yahoo_client_module.yf, "download", fake_download)
    client = YahooClient()

    result = asyncio.run(client.get_history(["AAPL", "MSFT"]))

    assert call_count["n"] == 1  # one batch call, not one per ticker
    assert set(result.keys()) == {"AAPL", "MSFT"}
    assert len(result["AAPL"]) == 10


def test_get_history_isolates_bad_ticker_in_batch(monkeypatch):
    def fake_download(tickers, **kwargs):
        # MSFT requested but absent from the response entirely -- the real
        # yfinance shape for a bad/delisted symbol.
        return _fake_multi_ticker_frame({"AAPL": _sample_ohlcv()})

    monkeypatch.setattr(yahoo_client_module.yf, "download", fake_download)
    client = YahooClient()

    result = asyncio.run(client.get_history(["AAPL", "MSFT"]))

    assert set(result.keys()) == {"AAPL"}  # MSFT silently absent, batch not raised


def test_get_history_empty_ticker_list_never_calls_yf_download(monkeypatch):
    def fail_if_called(tickers, **kwargs):
        raise AssertionError("must not call yf.download for an empty ticker list")

    monkeypatch.setattr(yahoo_client_module.yf, "download", fail_if_called)
    client = YahooClient()

    result = asyncio.run(client.get_history([]))

    assert result == {}


def test_get_history_download_exception_returns_empty_dict(monkeypatch):
    def raising_download(tickers, **kwargs):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(yahoo_client_module.yf, "download", raising_download)
    client = YahooClient()

    result = asyncio.run(client.get_history(["AAPL"]))

    assert result == {}  # degrades gracefully, never raises out of get_history


def test_get_dividends_returns_the_series_and_none_becomes_empty(monkeypatch):
    series = pd.Series([0.27], index=pd.DatetimeIndex(["2026-08-10"]))

    class FakeTicker:
        def __init__(self, symbol):
            self.dividends = series if symbol == "AAPL" else None

    monkeypatch.setattr(yahoo_client_module.yf, "Ticker", FakeTicker)
    client = YahooClient()

    assert asyncio.run(client.get_dividends("AAPL")).equals(series)
    assert asyncio.run(client.get_dividends("NOPE")).empty


def test_get_earnings_dates_passes_limit_through_and_none_becomes_empty(monkeypatch):
    seen = {}
    frame = pd.DataFrame({"Reported EPS": [1.0]}, index=pd.DatetimeIndex(["2026-07-30"]))

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def get_earnings_dates(self, limit):
            seen["limit"] = limit
            return frame if self.symbol == "AAPL" else None

    monkeypatch.setattr(yahoo_client_module.yf, "Ticker", FakeTicker)
    client = YahooClient()

    assert asyncio.run(client.get_earnings_dates("AAPL", limit=12)).equals(frame)
    assert seen["limit"] == 12
    assert asyncio.run(client.get_earnings_dates("SPY")).empty


def test_get_dividends_propagates_fetch_errors(monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            pass

        @property
        def dividends(self):
            raise RuntimeError("yahoo down")

    monkeypatch.setattr(yahoo_client_module.yf, "Ticker", FakeTicker)

    import pytest

    with pytest.raises(RuntimeError):
        asyncio.run(YahooClient().get_dividends("AAPL"))
