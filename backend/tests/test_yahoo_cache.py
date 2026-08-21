import asyncio
from datetime import datetime, timedelta

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine, select

import clients.yahoo_cache as yahoo_cache_module
from core.models import YahooPriceCache


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _sample_df(n: int = 5, start_price: float = 100.0) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "Open": [start_price + i for i in range(n)],
            "High": [start_price + i + 1 for i in range(n)],
            "Low": [start_price + i - 1 for i in range(n)],
            "Close": [start_price + i for i in range(n)],
            "Volume": [1000 + i for i in range(n)],
        },
        index=dates,
    )


def test_get_or_fetch_price_history_fetches_and_caches_when_empty(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    call_count = {"n": 0}

    async def fake_get_history(tickers, period="2y", interval="1d"):
        call_count["n"] += 1
        return {"AAPL": _sample_df()}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    assert call_count["n"] == 1
    assert len(rows) == 5
    assert rows[0].close == 100.0


def test_get_or_fetch_price_history_returns_cached_when_fresh(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    with Session(engine) as session:
        session.add(
            YahooPriceCache(
                ticker="AAPL",
                date=pd.Timestamp("2024-01-01").date(),
                open=1,
                high=2,
                low=0.5,
                close=1.5,
                volume=100,
                fetched_at=datetime.now(),
            )
        )
        session.commit()

    def fail_if_called(tickers, period="2y", interval="1d"):
        raise AssertionError("must not fetch live when cache is fresh")

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fail_if_called)

    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    assert len(rows) == 1


def test_get_or_fetch_price_history_cache_only_never_fetches_live(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    def fail_if_called(tickers, period="2y", interval="1d"):
        raise AssertionError("cache_only must never call Yahoo live")

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fail_if_called)

    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL", cache_only=True))

    assert rows == []  # nothing cached yet, cache_only never fetches to fill it


def test_get_or_fetch_price_history_batch_fetches_only_stale_tickers(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    # AAPL already fresh -- must be skipped from the live batch fetch entirely.
    with Session(engine) as session:
        session.add(
            YahooPriceCache(
                ticker="AAPL",
                date=pd.Timestamp("2024-01-01").date(),
                open=1,
                high=2,
                low=0.5,
                close=1.5,
                volume=100,
                fetched_at=datetime.now(),
            )
        )
        session.commit()

    requested_batches = []

    async def fake_get_history(tickers, period="2y", interval="1d"):
        requested_batches.append(list(tickers))
        return {"MSFT": _sample_df()}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history)

    result = asyncio.run(yahoo_cache_module.get_or_fetch_price_history_batch(["AAPL", "MSFT"]))

    assert requested_batches == [["MSFT"]]  # AAPL skipped -- already fresh
    assert len(result["AAPL"]) == 1
    assert len(result["MSFT"]) == 5


def test_upsert_overwrites_same_ticker_date_row_not_duplicate(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(yahoo_cache_module, "engine", engine)

    async def fake_get_history_v1(tickers, period="2y", interval="1d"):
        return {"AAPL": _sample_df(n=1, start_price=100.0)}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history_v1)
    asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    # Force staleness so a second fetch actually happens, with a different close.
    with Session(engine) as session:
        row = session.exec(select(YahooPriceCache).where(YahooPriceCache.ticker == "AAPL")).first()
        row.fetched_at = datetime.now() - timedelta(days=10)
        session.add(row)
        session.commit()

    async def fake_get_history_v2(tickers, period="2y", interval="1d"):
        return {"AAPL": _sample_df(n=1, start_price=200.0)}

    monkeypatch.setattr(yahoo_cache_module.yahoo_client, "get_history", fake_get_history_v2)
    rows = asyncio.run(yahoo_cache_module.get_or_fetch_price_history("AAPL"))

    assert len(rows) == 1  # same (ticker, date) key -- updated in place, not duplicated
    assert rows[0].close == 200.0
