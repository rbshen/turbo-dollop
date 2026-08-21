import asyncio
from datetime import date, datetime, timedelta

import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.trend_analysis_data as trend_analysis_data_module
from core.models import TrendAnalysis, YahooPriceCache
from data.trend_analysis_data import compute_and_store_trend_analysis, get_trend_analysis_data


def _fresh_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return engine


def _synthetic_rows(n: int = 150) -> list[YahooPriceCache]:
    """A reproducible noisy uptrend -- enough real zigzag to produce genuine
    swings, ATR(14), and the 60-day efficiency ratio (never persisted to
    the DB directly -- returned in place of a real get_or_fetch_price_history
    call)."""
    rng = np.random.default_rng(3)
    trend = np.linspace(0, 30, n)
    noise = rng.normal(0, 1.0, size=n).cumsum() * 0.2
    closes = 100 + trend + noise
    rows = []
    for i in range(n):
        d = date(2024, 1, 1) + timedelta(days=i)
        c = float(closes[i])
        rows.append(YahooPriceCache(ticker="AAPL", date=d, open=c - 0.1, high=c + 0.5, low=c - 0.5, close=c, volume=1000, fetched_at=datetime.now()))
    return rows


def test_compute_and_store_trend_analysis_persists_and_returns_matching_result(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_price_history(ticker, period="2y"):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fake_get_or_fetch_price_history)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    assert result.ticker == "AAPL"
    assert result.trend_state in ("uptrend", "downtrend")
    assert 1 <= result.bar_level <= 5

    with Session(engine) as session:
        row = session.exec(select(TrendAnalysis).where(TrendAnalysis.ticker == "AAPL")).first()
    assert row is not None
    assert row.trend_state == result.trend_state
    assert row.bar_level == result.bar_level


def test_compute_and_store_trend_analysis_raises_when_no_yahoo_data(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_empty(ticker, period="2y"):
        return []

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fake_empty)

    with pytest.raises(ValueError):
        asyncio.run(compute_and_store_trend_analysis("ZZZZINVALID"))


def test_get_trend_analysis_data_cache_only_never_fetches_and_returns_none_when_missing(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    def fail_if_called(ticker, period="2y"):
        raise AssertionError("cache_only must never fetch live")

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fail_if_called)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))

    assert result is None


def test_get_trend_analysis_data_computes_when_missing_and_not_cache_only(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_price_history(ticker, period="2y"):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fake_get_or_fetch_price_history)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=False))

    assert result is not None
    assert result.ticker == "AAPL"


def test_get_trend_analysis_data_returns_fresh_cached_row_without_recomputing(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=datetime.now(),
                trend_state="uptrend",
                magnitude_tier="strong",
                persistence_count=4,
                bars_since_confirmation=1,
                warning_flag=False,
                efficiency_ratio=0.5,
                regime="trending",
                blended_score=8.0,
                bar_level=5,
            )
        )
        session.commit()

    def fail_if_called(ticker, period="2y"):
        raise AssertionError("must not recompute when the cached row is fresh")

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fail_if_called)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=False))

    assert result.bar_level == 5
    assert result.blended_score == 8.0


def test_get_trend_analysis_data_falls_back_to_stale_row_on_yahoo_failure(monkeypatch):
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    stale_time = datetime.now() - timedelta(days=30)
    with Session(engine) as session:
        session.add(
            TrendAnalysis(
                ticker="AAPL",
                computed_at=stale_time,
                trend_state="downtrend",
                magnitude_tier="weak",
                persistence_count=1,
                bars_since_confirmation=5,
                warning_flag=False,
                blended_score=-3.0,
                bar_level=2,
            )
        )
        session.commit()

    async def fake_empty(ticker, period="2y"):
        return []  # Yahoo has no data -- compute_and_store raises ValueError internally

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fake_empty)

    result = asyncio.run(get_trend_analysis_data("AAPL", cache_only=False))

    assert result.bar_level == 2  # served the stale row rather than nothing


def test_swing_detail_json_round_trips_through_a_real_compute(monkeypatch):
    """Exercises the actual JSON serialize/deserialize path for
    last_confirmed_swing (a real dataclass -> str column -> SwingDetailOut
    round trip), not just a mocked-out shortcut."""
    engine = _fresh_engine()
    monkeypatch.setattr(trend_analysis_data_module, "engine", engine)

    async def fake_get_or_fetch_price_history(ticker, period="2y"):
        return _synthetic_rows()

    monkeypatch.setattr(trend_analysis_data_module, "get_or_fetch_price_history", fake_get_or_fetch_price_history)

    result = asyncio.run(compute_and_store_trend_analysis("AAPL"))

    if result.last_confirmed_swing is not None:
        assert isinstance(result.last_confirmed_swing.date, date)
        assert isinstance(result.last_confirmed_swing.ratio, float)

    reread = asyncio.run(get_trend_analysis_data("AAPL", cache_only=True))
    assert reread.last_confirmed_swing == result.last_confirmed_swing
