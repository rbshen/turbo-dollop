import pandas as pd
import pytest

from analysis.trend_structure.atr import compute_atr, true_range


def test_true_range_uses_max_of_the_three_components():
    high = pd.Series([10.0, 12.0, 11.0])
    low = pd.Series([8.0, 9.0, 10.0])
    close = pd.Series([9.0, 11.0, 10.5])

    tr = true_range(high, low, close)

    assert tr.iloc[0] == pytest.approx(2.0)  # no prev close yet -> just high-low
    # bar 1: high-low=3, |high-prevclose|=|12-9|=3, |low-prevclose|=|9-9|=0 -> max=3
    assert tr.iloc[1] == pytest.approx(3.0)


def test_atr_seeds_with_simple_average_then_wilder_smooths():
    n = 20
    high = pd.Series([100.0 + i for i in range(n)])
    low = pd.Series([99.0 + i for i in range(n)])
    close = pd.Series([99.5 + i for i in range(n)])

    atr = compute_atr(high, low, close, period=14)
    tr = true_range(high, low, close)

    assert atr.iloc[:13].isna().all()  # no seed available for the first period-1 bars
    assert atr.iloc[13] == pytest.approx(tr.iloc[:14].mean())  # SMA seed
    expected_next = (atr.iloc[13] * 13 + tr.iloc[14]) / 14  # Wilder's recursive step
    assert atr.iloc[14] == pytest.approx(expected_next)
