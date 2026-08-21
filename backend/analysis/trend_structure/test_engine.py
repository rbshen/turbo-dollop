import numpy as np
import pandas as pd

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
    assert -10.0 <= result.blended_score <= 10.0


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
