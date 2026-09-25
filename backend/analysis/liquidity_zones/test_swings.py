import pandas as pd

from analysis.liquidity_zones.swings import annotate_swings, find_swing_highs, find_swing_lows, valid_prices_at


def _series(values: list[float]) -> pd.Series:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=dates)


def test_first_and_last_k_bars_can_never_be_confirmed_swings():
    values = list(range(20))  # monotonic, no real swings anywhere
    low = _series(values)
    high = _series(values)

    lows = find_swing_lows(low, k=3)
    highs = find_swing_highs(high, k=3)

    assert not lows.iloc[:3].any() and not lows.iloc[-3:].any()
    assert not highs.iloc[:3].any() and not highs.iloc[-3:].any()
    assert not lows.isna().any() and not highs.isna().any()


def test_detects_a_genuine_swing_low_and_high():
    low_values = [10, 9, 8, 7, -100, 7, 8, 9, 10, 10, 10, 10]
    high_values = [1, 2, 3, 4, 100, 4, 3, 2, 1, 1, 1, 1]

    lows = find_swing_lows(_series(low_values), k=2)
    highs = find_swing_highs(_series(high_values), k=2)

    assert lows.iloc[4] and lows.sum() == 1
    assert highs.iloc[4] and highs.sum() == 1


def test_ordinary_non_swing_bar_breaches_a_level():
    # Swing low at pos 2 (90). Positions 5-6 dip to 80 and tie, so neither is
    # ever a confirmed swing low -- but under the reference script's any-
    # later-bar rule an ordinary bar trading below the level still breaches
    # it, at the FIRST such bar (pos 5).
    values = [100, 100, 90, 100, 100, 80, 80, 100, 100, 95, 100, 100, 100]
    low = _series(values)
    is_low = find_swing_lows(low, k=2)

    assert is_low.iloc[2]
    assert not is_low.iloc[5] and not is_low.iloc[6]

    events = annotate_swings(low, is_low, kind="low")
    swing_at_2 = next(e for e in events if e.pos == 2)
    assert swing_at_2.breach_pos == 5
    assert swing_at_2 not in valid_prices_at(events, as_of_pos=len(values) - 1)


def test_touching_the_level_exactly_does_not_breach():
    values = [100, 100, 90, 100, 100, 90, 100, 100, 100, 100]
    low = _series(values)
    events = annotate_swings(low, find_swing_lows(low, k=2), kind="low")

    assert next(e for e in events if e.pos == 2).breach_pos is None


def test_a_later_bar_high_breaches_a_resistance_level():
    values = [1, 1, 110, 1, 1, 1, 120, 120, 1, 1, 1, 1]
    high = _series(values)
    events = annotate_swings(high, find_swing_highs(high, k=2), kind="high")

    assert next(e for e in events if e.pos == 2).breach_pos == 6
