from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine, select

import data.liquidity_zone_data as liquidity_zone_data
from analysis.liquidity_zones.types import BrokenZone, LiquidityZoneResult
from analysis.liquidity_zones.types import LiquidityZoneSettings
from core.models import LiquidityZoneAnalysis
from data.liquidity_zone_data import compute_and_store_liquidity_zones, get_liquidity_zone_data, sweep_stale_liquidity_zones


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


def _config() -> LiquidityZoneSettings:
    return LiquidityZoneSettings()


def test_compute_and_store_creates_both_daily_and_weekly_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)

    compute_and_store_liquidity_zones("AAPL", _ohlcv(), source="fmp", settings=_config())

    with Session(engine) as session:
        rows = session.exec(select(LiquidityZoneAnalysis).where(LiquidityZoneAnalysis.ticker == "AAPL")).all()
    assert {r.timeframe for r in rows} == {"daily", "weekly"}
    assert all(r.source == "fmp" for r in rows)


def test_get_liquidity_zone_data_returns_none_when_never_computed(monkeypatch):
    _fresh_engine(monkeypatch)

    assert get_liquidity_zone_data("ZZZZINVALID") is None


def test_get_liquidity_zone_data_parses_zones_and_computes_distance_pct(monkeypatch):
    _fresh_engine(monkeypatch)
    compute_and_store_liquidity_zones("AAPL", _ohlcv(), source="fmp", settings=_config())

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


def test_broken_zone_round_trips_through_storage_and_read(monkeypatch):
    # Bypasses the real swing engine (already exhaustively covered in
    # analysis/liquidity_zones/test_engine.py) to isolate this test to the
    # data-layer's own JSON persist/parse plumbing for the new
    # broken_support/broken_resistance fields.
    engine = _fresh_engine(monkeypatch)
    fake_result = LiquidityZoneResult(
        last_price=100.0,
        as_of=date(2026, 1, 10),
        support=[],
        resistance=[],
        broken_support=BrokenZone(price=90.0, formed_at=date(2026, 1, 1), breached_at=date(2026, 1, 5)),
        broken_resistance=None,
    )
    monkeypatch.setattr(liquidity_zone_data, "compute_liquidity_zones", lambda *args, **kwargs: fake_result)

    compute_and_store_liquidity_zones("AAPL", _ohlcv(), source="fmp", settings=_config())
    out = get_liquidity_zone_data("AAPL")

    assert out is not None
    for lp_read in (out.daily, out.weekly):
        assert lp_read.broken_support is not None
        assert lp_read.broken_support.price == 90.0
        assert lp_read.broken_support.formed_at == date(2026, 1, 1)
        assert lp_read.broken_support.breached_at == date(2026, 1, 5)
        assert lp_read.broken_support.distance_pct == pytest.approx((90.0 - 100.0) / 100.0 * 100.0)
        assert lp_read.broken_resistance is None


def test_recompute_upserts_rather_than_duplicating_rows(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    ohlcv = _ohlcv()
    compute_and_store_liquidity_zones("AAPL", ohlcv, source="fmp", settings=_config())
    compute_and_store_liquidity_zones("AAPL", ohlcv, source="fmp", settings=_config())

    with Session(engine) as session:
        rows = session.exec(select(LiquidityZoneAnalysis).where(LiquidityZoneAnalysis.ticker == "AAPL")).all()
    assert len(rows) == 2  # one daily + one weekly, never duplicated


def test_raises_on_empty_ohlcv(monkeypatch):
    _fresh_engine(monkeypatch)

    with pytest.raises(ValueError):
        compute_and_store_liquidity_zones("AAPL", pd.DataFrame(), source="fmp", settings=_config())


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


def _seed_row(
    engine,
    computed_at: datetime,
    support_json: str = '[{"price": 90.0, "cluster_size": 1, "formed_at": "2026-01-01"}]',
    resistance_json: str = '[{"price": 130.0, "cluster_size": 1, "formed_at": "2026-01-01"}]',
    broken_support_json: str | None = None,
    broken_resistance_json: str | None = None,
):
    with Session(engine) as session:
        session.add(
            LiquidityZoneAnalysis(
                ticker="AAPL",
                timeframe="daily",
                last_price=100.0,
                as_of=computed_at.date(),
                support_zones_json=support_json,
                resistance_zones_json=resistance_json,
                broken_support_json=broken_support_json,
                broken_resistance_json=broken_resistance_json,
                source="fmp",
                computed_at=computed_at,
            )
        )
        session.commit()


def test_sweep_clears_a_stale_rows_zones_but_leaves_as_of_source_computed_at_alone(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale_computed_at = now - timedelta(days=8)
    _seed_row(engine, stale_computed_at)

    cleared = sweep_stale_liquidity_zones(now=now)

    assert cleared == 1
    with Session(engine) as session:
        row = session.get(LiquidityZoneAnalysis, ("AAPL", "daily"))
    assert row.support_zones_json == "[]"
    assert row.resistance_zones_json == "[]"
    assert row.last_price == 100.0
    assert row.as_of == stale_computed_at.date()
    assert row.source == "fmp"
    assert row.computed_at == stale_computed_at


def test_sweep_leaves_a_fresh_row_untouched(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    fresh_computed_at = now - timedelta(days=6)
    _seed_row(engine, fresh_computed_at)

    cleared = sweep_stale_liquidity_zones(now=now)

    assert cleared == 0
    with Session(engine) as session:
        row = session.get(LiquidityZoneAnalysis, ("AAPL", "daily"))
    assert row.support_zones_json != "[]"


def test_sweep_clears_a_stale_rows_broken_zone_fields_to_null(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale_computed_at = now - timedelta(days=8)
    _seed_row(
        engine,
        stale_computed_at,
        broken_support_json='{"price": 85.0, "formed_at": "2026-01-01", "breached_at": "2026-01-05"}',
    )

    cleared = sweep_stale_liquidity_zones(now=now)

    assert cleared == 1
    with Session(engine) as session:
        row = session.get(LiquidityZoneAnalysis, ("AAPL", "daily"))
    assert row.broken_support_json is None
    assert row.broken_resistance_json is None


def test_sweep_triggers_on_a_stale_row_whose_only_leftover_state_is_a_broken_zone(monkeypatch):
    # Active zones already "[]" (a previously-swept row), but a broken
    # zone was recorded on a later run before the ticker fell off the
    # watchlist again -- the WHERE clause's broken-zone half must catch
    # this, not just the support/resistance-json half.
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale_computed_at = now - timedelta(days=8)
    _seed_row(
        engine,
        stale_computed_at,
        support_json="[]",
        resistance_json="[]",
        broken_support_json='{"price": 85.0, "formed_at": "2026-01-01", "breached_at": "2026-01-05"}',
    )

    assert sweep_stale_liquidity_zones(now=now) == 1


def test_sweep_is_idempotent_on_an_already_cleared_row(monkeypatch):
    engine = _fresh_engine(monkeypatch)
    now = datetime(2026, 9, 9, 12, 0)
    stale_computed_at = now - timedelta(days=8)
    _seed_row(engine, stale_computed_at, support_json="[]", resistance_json="[]")

    assert sweep_stale_liquidity_zones(now=now) == 0  # both already "[]" -- nothing left to clear


# --- 2H.90D Chart range: live LP read on 2h candles ---------------------------------------------------------


def _candles_2h(n: int = 80) -> pd.DataFrame:
    """Four candles a day on a naive ET window-start index, one clean swing low early and one breached later."""
    idx = pd.DatetimeIndex([pd.Timestamp("2026-01-05 09:30") + pd.Timedelta(days=i // 4, hours=2 * (i % 4)) for i in range(n)])
    low, high = [100.0] * n, [105.0] * n
    low[10] = 90.0
    high[30] = 130.0
    close = [(lo + hi) / 2 for lo, hi in zip(low, high)]
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1000}, index=idx)


def test_2h_compute_hardcodes_breach_recency_to_20_candles_and_leaves_other_settings_shared():
    from data.liquidity_zone_data import LP_2H_BREACH_RECENCY_BARS, compute_liquidity_zones_2h

    assert LP_2H_BREACH_RECENCY_BARS == 20
    candles = _candles_2h()
    # A swing low breached 12 candles before the end: outside the shared 5-bar recency, inside the 2h 20.
    candles.loc[candles.index[66], "low"] = 80.0  # breaches the 90 swing (and is itself the new lowest)
    shared = LiquidityZoneSettings(swing_bars_each_side=2, cluster_pct=0.0, max_lps_per_side=3, breach_recency_bars=5)
    result = compute_liquidity_zones_2h(candles, shared)
    assert result.broken_support is not None and result.broken_support.price == 90.0
    assert result.broken_support.formed_ts == candles.index[10].to_pydatetime()
    # ...and with the 2h override ignoring the (small) shared value, the zone caps/swings still come from the shared settings.
    assert len(result.support) <= 3 and len(result.resistance) <= 3


def test_2h_compute_returns_timestamps_and_does_not_touch_the_database(monkeypatch):
    from data.liquidity_zone_data import compute_liquidity_zones_2h

    engine = _fresh_engine(monkeypatch)
    result = compute_liquidity_zones_2h(_candles_2h(), LiquidityZoneSettings(swing_bars_each_side=2, cluster_pct=0.0, max_lps_per_side=3))
    assert result.resistance and result.resistance[0].formed_ts == _candles_2h().index[30].to_pydatetime()
    with Session(engine) as session:
        assert session.exec(select(LiquidityZoneAnalysis)).all() == []
