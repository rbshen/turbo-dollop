import pandas as pd

from analysis.trend_structure.regime import latest_regime


def test_efficiency_ratio_is_one_for_a_perfectly_monotonic_series():
    close = pd.Series([100.0 + i for i in range(100)])  # straight line, no reversals

    er, regime = latest_regime(close)

    assert er == 1.0
    assert regime == "trending"


def test_efficiency_ratio_near_zero_for_a_perfectly_oscillating_series():
    # Oscillates back to the same phase every 2 bars -- net 60-day
    # displacement is ~0 relative to the summed absolute path length.
    close = pd.Series([100.0, 101.0] * 40)

    er, regime = latest_regime(close)

    assert er < 0.15
    assert regime == "range-bound"


def test_latest_regime_returns_none_when_insufficient_history():
    close = pd.Series([100.0, 101.0, 102.0])  # far fewer than 60 bars

    er, regime = latest_regime(close)

    assert er is None
    assert regime is None
