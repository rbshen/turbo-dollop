import pandas as pd

from analysis.trend_structure.swings import extract_swing_points, find_swing_highs, find_swing_lows


def _close_series(values: list[float]) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=dates)


def test_first_and_last_n_bars_can_never_be_confirmed_swings():
    # A single peak in the middle of 20 bars -- the first/last 5 bars can
    # never be confirmed (no full 5-bar window on both sides), False not NaN.
    values = list(range(20))  # monotonic increasing, so no real swing highs at all
    close = _close_series(values)

    highs = find_swing_highs(close)
    lows = find_swing_lows(close)

    assert not highs.iloc[:5].any()
    assert not highs.iloc[-5:].any()
    assert not lows.iloc[:5].any()
    assert not lows.iloc[-5:].any()
    assert highs.dtype == bool and lows.dtype == bool
    assert not highs.isna().any()
    assert not lows.isna().any()


def test_detects_a_genuine_swing_high():
    # Bar 10 is strictly greater than the 5 bars on each side.
    values = [1, 2, 3, 4, 5, 6, 100, 6, 5, 4, 3, 2, 1, 1, 1, 1, 1, 1, 1, 1]
    close = _close_series(values)

    highs = find_swing_highs(close)

    assert highs.iloc[6]  # the value=100 bar
    assert highs.sum() == 1  # exactly one swing high in this series


def test_detects_a_genuine_swing_low():
    values = [10, 9, 8, 7, 6, 5, -100, 5, 6, 7, 8, 9, 10, 10, 10, 10, 10, 10, 10, 10]
    close = _close_series(values)

    lows = find_swing_lows(close)

    assert lows.iloc[6]
    assert lows.sum() == 1


def test_extract_swing_points_orders_chronologically_and_mixes_kinds():
    # A high at index 6, a low at index 13.
    values = [1, 2, 3, 4, 5, 6, 100, 6, 5, 4, 3, 2, 1, -50, 1, 2, 3, 4, 5, 6]
    close = _close_series(values)

    points = extract_swing_points(close)

    assert [p.kind for p in points] == ["high", "low"]
    assert points[0].date < points[1].date
    assert points[0].price == 100
    assert points[1].price == -50


def test_a_bar_is_never_both_a_swing_high_and_swing_low():
    values = [5, 4, 3, 2, 1, 100, 1, 2, 3, 4, 5]
    close = _close_series(values)

    highs = find_swing_highs(close)
    lows = find_swing_lows(close)

    assert not (highs & lows).any()
