import numpy as np
import pandas as pd
import pytest

from analysis.trend_structure.stochastic import compute_stochastic


def _ema(values: list[float], n: int) -> list[float]:
    """Independent hand-rolled classic recursive EMA, seeded with the first value."""
    a = 2 / (n + 1)
    out = [values[0]]
    for x in values[1:]:
        out.append(out[-1] + a * (x - out[-1]))
    return out


def _reference(high, low, close, k=5, s=3, d=3):
    """thinkScript StochasticFull, written loop-by-loop (no pandas rolling/ewm)."""
    fast = []
    for i in range(k - 1, len(close)):
        lo = min(low[i - k + 1 : i + 1])
        hi = max(high[i - k + 1 : i + 1])
        fast.append((close[i] - lo) / (hi - lo) * 100 if hi - lo != 0 else 0.0)
    fk = _ema(fast, s)
    fd = _ema(fk, d)
    return [np.nan] * (k - 1) + fk, [np.nan] * (k - 1) + fd


def test_matches_independent_recursive_ema_reference_on_synthetic_series():
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 1.5, 300))
    high = close + rng.uniform(0.1, 2.0, 300)
    low = close - rng.uniform(0.1, 2.0, 300)

    full_k, full_d = compute_stochastic(pd.Series(high), pd.Series(low), pd.Series(close))
    ref_k, ref_d = _reference(list(high), list(low), list(close))

    np.testing.assert_allclose(full_k.to_numpy(), ref_k, atol=1e-9, equal_nan=True)
    np.testing.assert_allclose(full_d.to_numpy(), ref_d, atol=1e-9, equal_nan=True)


def test_regression_fixed_fixture_known_5_3_3_ema_values():
    high = pd.Series([12.0, 14.0, 11.0, 15.0, 13.0, 16.0, 10.0])
    low = pd.Series([10.0, 11.0, 9.0, 12.0, 11.0, 13.0, 8.0])
    close = pd.Series([11.0, 13.0, 10.0, 14.0, 12.0, 15.0, 9.0])

    full_k, full_d = compute_stochastic(high, low, close)

    # FastK (idx 4,5,6): 50.0, 600/7, 12.5. EMA alpha=0.5 seeded with the first FastK:
    #   K4 = 50; K5 = 50 + .5*(85.714286-50) = 67.857143; K6 = 67.857143 + .5*(12.5-67.857143) = 40.178571
    #   D4 = 50; D5 = 58.928571; D6 = 49.553571
    assert full_k.iloc[:4].isna().all() and full_d.iloc[:4].isna().all()
    assert full_k.iloc[4:].tolist() == pytest.approx([50.0, 67.857142857, 40.178571429])
    assert full_d.iloc[4:].tolist() == pytest.approx([50.0, 58.928571429, 49.553571429])


def test_zero_range_window_reads_zero_and_never_produces_nan():
    # Flat for 5+ bars: highest_high == lowest_low -> FastK 0 (thinkScript), no NaN downstream.
    flat = pd.Series([10.0] * 8)
    full_k, full_d = compute_stochastic(flat, flat, flat)
    assert full_k.iloc[:4].isna().all()
    assert full_k.iloc[4:].tolist() == [0.0] * 4
    assert full_d.iloc[4:].tolist() == [0.0] * 4


def test_zero_range_mid_series_does_not_poison_later_values():
    close = pd.Series([10.0, 11, 12, 13, 14, 15, 15, 15, 15, 15, 15, 16, 17])
    high, low = close.copy(), close.copy()
    full_k, full_d = compute_stochastic(high, low, close)
    assert full_k.iloc[4:].notna().all() and full_d.iloc[4:].notna().all()


def test_constant_fast_k_settles_full_k_and_full_d_to_the_same_value():
    n = 12
    close = pd.Series([10.0 + i for i in range(n)])
    full_k, full_d = compute_stochastic(close + 1, close - 1, close)
    expected = 100 * 5 / 6
    assert full_k.iloc[:4].isna().all()
    assert full_k.iloc[4:].tolist() == pytest.approx([expected] * (n - 4))
    assert full_d.iloc[4:].tolist() == pytest.approx([expected] * (n - 4))


def test_custom_k_period_and_smooth_are_honored():
    close = pd.Series([float(i) for i in range(10)])
    full_k, full_d = compute_stochastic(close + 1, close - 1, close, k_period=3, smooth=2)
    assert full_k.iloc[:2].isna().all()
    assert full_k.iloc[2:].notna().all()
    ref_k, ref_d = _reference(list(close + 1), list(close - 1), list(close), k=3, s=2, d=2)
    np.testing.assert_allclose(full_d.to_numpy(), ref_d, atol=1e-9, equal_nan=True)
