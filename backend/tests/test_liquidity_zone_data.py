from datetime import datetime

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.liquidity_zone_data as liquidity_zone_data
from core.models import LiquidityZoneAnalysis, LiquidityZoneConfig
from data.liquidity_zone_data import compute_and_store_liquidity_zones, get_liquidity_zone_data
from helpers.liquidity_zone_config import DEFAULT_CLUSTER_PCT, DEFAULT_NUM_ZONES, DEFAULT_SWING_BARS


def _fresh_engine(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(liquidity_zone_data, "engine", engine)
    return engine


def _ohlcv(n: int = 730) -> pd.DataFrame:
    """~2 years of daily bars with one clean, isolated swing low and one
    clean swing high, both well inside the trailing-1yr slice."""
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    low = [100.0] * n
    high = [105.0] * n
    low[n - 100] = 90.0
    high[n - 60] = 130.0
    close = [(lo + hi) / 2 for lo, hi in zip(low, high)]
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": [1000] * n}, index=dates)


def _config() -> LiquidityZoneConfig:
    return LiquidityZoneConfig(
        key="default",
        daily_swing_bars=DEFAULT_SWING_BARS,
        daily_cluster_pct=DEFAULT_CLUSTER_PCT,
        daily_num_zones=DEFAULT_NUM_ZONES,
        weekly_swing_bars=DEFAULT_SWING_BARS,
        weekly_cluster_pct=DEFAULT_CLUSTER_PCT,
        weekly_num_zones=DEFAULT_NUM_ZONES,
        updated_at=datetime.now(),
    )


def test_compute_and_store_creates_both_daily_and_weekly_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    compute_and_store_liquidity_zones("AAPL", _ohlcv(), source="fmp", config=_config())

    with Session(engine) as session:
        rows = session.exec(select(LiquidityZoneAnalysis).where(LiquidityZoneAnalysis.ticker == "AAPL")).all()
    assert {r.timeframe for r in rows} == {"daily", "weekly"}
    assert all(r.source == "fmp" for r in rows)


def test_get_liquidity_zone_data_returns_none_when_never_computed(monkeypatch):
    _fresh_engine(monkeypatch)

    assert get_liquidity_zone_data("ZZZZINVALID") is None


def test_get_liquidity_zone_data_parses_zones_and_computes_distance_pct(monkeypatch):
    _fresh_engine(monkeypatch)
    compute_and_store_liquidity_zones("AAPL", _ohlcv(), source="fmp", config=_config())

    out = get_liquidity_zone_data("AAPL")

    assert out is not None
    assert out.daily is not None and out.weekly is not None
    assert out.daily.last_price == pytest.approx(102.5)
    assert len(out.daily.support_zones) == 1
    support = out.daily.support_zones[0]
    assert support.price == pytest.approx(90.0)
    assert support.distance_pct == pytest.approx((90.0 - 102.5) / 102.5 * 100.0)
    assert len(out.daily.resistance_zones) == 1
    resistance = out.daily.resistance_zones[0]
    assert resistance.price == pytest.approx(130.0)
    assert resistance.distance_pct == pytest.approx((130.0 - 102.5) / 102.5 * 100.0)


def test_recompute_upserts_rather_than_duplicating_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    ohlcv = _ohlcv()
    compute_and_store_liquidity_zones("AAPL", ohlcv, source="fmp", config=_config())
    compute_and_store_liquidity_zones("AAPL", ohlcv, source="fmp", config=_config())

    with Session(engine) as session:
        rows = session.exec(select(LiquidityZoneAnalysis).where(LiquidityZoneAnalysis.ticker == "AAPL")).all()
    assert len(rows) == 2  # one daily + one weekly, never duplicated


def test_raises_on_empty_ohlcv(monkeypatch):
    _fresh_engine(monkeypatch)

    with pytest.raises(ValueError):
        compute_and_store_liquidity_zones("AAPL", pd.DataFrame(), source="fmp", config=_config())


def test_only_one_timeframe_computed_still_returns_the_other_side_as_none(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    with Session(engine) as session:
        session.add(
            LiquidityZoneAnalysis(
                ticker="AAPL",
                timeframe="daily",
                last_price=100.0,
                as_of=pd.Timestamp("2026-01-01").date(),
                support_zones_json="[]",
                resistance_zones_json="[]",
                source="fmp",
                computed_at=datetime.now(),
            )
        )
        session.commit()

    out = get_liquidity_zone_data("AAPL")

    assert out is not None
    assert out.daily is not None
    assert out.weekly is None
