from datetime import date

import numpy as np
import pandas as pd
import pytest

from analysis.trend_structure.engine import compute_trend_structure
from analysis.trend_structure.types import TrendStructureResult


def _synthetic_ohlcv(n: int = 150, seed: int = 7) -> pd.DataFrame:
    """A reproducible up-trending-with-noise path -- enough real zigzag to
    produce genuine fractal swings, long enough for both ATR(14) and the
    60-day efficiency ratio to have real values."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 1.5, size=n)
    trend = np.linspace(0, 40, n)
    close = 100 + trend + noise.cumsum() * 0.3
    high = close + np.abs(rng.normal(0.5, 0.3, size=n))
    low = close - np.abs(rng.normal(0.5, 0.3, size=n))
    open_ = close + rng.normal(0, 0.2, size=n)
    volume = rng.integers(1_000, 10_000, size=n)

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=dates)


def test_compute_trend_structure_produces_a_fully_populated_result():
    ohlcv = _synthetic_ohlcv()

    result = compute_trend_structure(ohlcv)

    assert isinstance(result, TrendStructureResult)
    assert result.trend_state in ("uptrend", "downtrend")
    assert result.magnitude_tier in ("weak", "confirmed", "strong", None)
    assert result.persistence_count >= 0
    assert result.regime in ("trending", "range-bound", None)
    assert 1 <= result.bar_level <= 5
    assert isinstance(result.blended_score, float)
    # Not bounded at exactly +/-10.0 any more: the A/D Bullish Divergence
    # booster (1.15x) can push an already-near-ceiling uptrend score
    # slightly past +10.0 -- see conviction.py's own note on this.
    assert -10.0 <= result.blended_score <= 11.5
    assert isinstance(result.ad_bullish_divergence, bool)
    assert result.ad_divergence_swing_date is None or isinstance(result.ad_divergence_swing_date, date)
    # SMA position tracking -- 150 bars of history clears all three windows
    # (20/50/200 would need 200, so 200's fields stay None here).
    assert result.sma20_position_pct is not None
    assert result.sma20_cross in ("up", "down", None)
    assert result.sma50_position_pct is not None
    assert result.sma50_cross in ("up", "down", None)
    assert result.sma200_position_pct is None  # only 150 bars, fewer than the 200-day window
    assert result.sma200_cross is None


def test_compute_trend_structure_is_deterministic_for_the_same_input():
    ohlcv = _synthetic_ohlcv(seed=42)

    result_a = compute_trend_structure(ohlcv)
    result_b = compute_trend_structure(ohlcv)

    assert result_a == result_b


def test_compute_trend_structure_handles_too_short_a_history_gracefully():
    """Fewer bars than FRACTAL_N*2+1 needs -- no swings possible at all, and
    not enough bars for ATR(14) or the 60-day efficiency ratio either. Must
    not raise; degrades to the documented bootstrap defaults."""
    n = 8
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    ohlcv = pd.DataFrame(
        {
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0 + i * 0.1 for i in range(n)],
            "volume": [1000] * n,
        },
        index=dates,
    )

    result = compute_trend_structure(ohlcv)

    assert result.magnitude_tier is None
    assert result.efficiency_ratio is None
    assert result.regime is None
    assert result.bar_level in (1, 2, 3, 4, 5)
    assert result.ad_bullish_divergence is False
    assert result.ad_divergence_swing_date is None
    # 8 bars is fewer than even the smallest SMA window (20) -- all six
    # SMA fields must degrade to None, not raise.
    assert result.sma20_position_pct is None
    assert result.sma20_cross is None
    assert result.sma50_position_pct is None
    assert result.sma50_cross is None
    assert result.sma200_position_pct is None
    assert result.sma200_cross is None


def test_sma_position_fields_flow_through_a_real_up_cross():
    """Wiring test: confirms compute_trend_structure actually threads
    compute_sma_position's output through to the top-level result for a
    genuine crossing, not just that the fields exist (test_sma_position.py
    already covers the calculation itself in isolation)."""
    # 21 bars -- exactly enough for SMA20 to have both a "today" and a
    # "prior" value (period + 1). SMA(20) at t-1 (mean of 18x100 + 90 + 90
    # = 99.0) sits above the prior close (90) -> prior_pos negative; SMA(20)
    # at t (mean of 17x100 + 90 + 90 + 130 = 100.5) sits below today's
    # close (130) -> today_pos positive. Same shape as
    # test_sma_position.py's own up-cross case, scaled to the real 20-day
    # window and wrapped in a full OHLCV frame.
    close = [100.0] * 18 + [90.0, 90.0, 130.0]
    n = len(close)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    ohlcv = pd.DataFrame(
        {"open": close, "high": [c + 1 for c in close], "low": [c - 1 for c in close], "close": close, "volume": [1000] * n},
        index=dates,
    )

    result = compute_trend_structure(ohlcv)

    assert result.sma20_position_pct == pytest.approx(29.35, abs=0.01)
    assert result.sma20_cross == "up"
    assert result.sma50_position_pct is None  # only 21 bars, fewer than 50
    assert result.sma200_position_pct is None


def test_ad_bullish_divergence_selects_the_most_recent_confirmed_ll_and_boosts_blended_score(monkeypatch):
    """Wiring test: with classify_swings/run_state_machine controlled
    directly, confirms compute_trend_structure (a) picks the LAST confirmed
    LL's divergence fields (not an earlier one, not a non-confirmed one),
    and (b) that a True flag on an uptrend result actually boosts
    blended_score vs. the identical setup without divergence -- the two
    halves of the engine wiring that classification.py's and conviction.py's
    own isolated unit tests can't cover on their own."""
    import analysis.trend_structure.engine as engine_module
    from analysis.trend_structure.classification import ClassifiedSwing
    from analysis.trend_structure.state_machine import TrendMachineState
    from analysis.trend_structure.types import SwingDetail, SwingPoint

    d1, d2, d3 = date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)
    non_confirmed_ll = ClassifiedSwing(
        swing=SwingPoint(date=d1, price=90.0, kind="low"),
        classification="LL",
        margin=1.0,
        atr=10.0,
        ratio=0.1,  # below CONFIRMED_RATIO -- must be ignored by the selection
        ad_bullish_divergence=True,
        ad_divergence_swing_date=d1,
    )
    earlier_confirmed_ll_no_divergence = ClassifiedSwing(
        swing=SwingPoint(date=d2, price=85.0, kind="low"),
        classification="LL",
        margin=5.0,
        atr=1.0,
        ratio=5.0,
        ad_bullish_divergence=False,
        ad_divergence_swing_date=None,
    )
    latest_confirmed_ll_with_divergence = ClassifiedSwing(
        swing=SwingPoint(date=d3, price=95.0, kind="low"),
        classification="LL",
        margin=5.0,
        atr=1.0,
        ratio=5.0,
        ad_bullish_divergence=True,
        ad_divergence_swing_date=d3,
    )
    classified = [non_confirmed_ll, earlier_confirmed_ll_no_divergence, latest_confirmed_ll_with_divergence]

    uptrend_state = TrendMachineState(
        trend_state="uptrend",
        magnitude_tier="strong",
        persistence_count=10,
        last_confirmed_swing=SwingDetail(date=d3, price=95.0, margin=5.0, atr=1.0, ratio=5.0),
        warning_flag=False,
        warning_swing=None,
    )

    ohlcv = _synthetic_ohlcv()
    monkeypatch.setattr(engine_module, "classify_swings", lambda swings, atr_by_date, chaikin_osc: classified)
    monkeypatch.setattr(engine_module, "run_state_machine", lambda classified_arg: uptrend_state)
    monkeypatch.setattr(engine_module, "latest_regime", lambda close: (0.5, "trending"))

    result = engine_module.compute_trend_structure(ohlcv)

    assert result.ad_bullish_divergence is True
    assert result.ad_divergence_swing_date == d3  # the LATEST confirmed LL, not the earlier or non-confirmed one

    # Same setup, but the latest confirmed LL has no divergence -- must
    # score strictly lower (no 1.15x boost).
    classified_no_divergence = [non_confirmed_ll, earlier_confirmed_ll_no_divergence]
    monkeypatch.setattr(engine_module, "classify_swings", lambda swings, atr_by_date, chaikin_osc: classified_no_divergence)
    result_no_divergence = engine_module.compute_trend_structure(ohlcv)

    assert result_no_divergence.ad_bullish_divergence is False
    assert result.blended_score > result_no_divergence.blended_score
