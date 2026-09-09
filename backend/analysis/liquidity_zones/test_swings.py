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


def test_ordinary_bar_does_not_breach_a_level_only_a_later_swing_does():
    # A confirmed swing low at pos 2 (price 90). Positions 5-6 dip to 80
    # (BELOW 90) but tie with each other, so neither clears the strict
    # "<" test against its own neighbor -- neither is ever confirmed as a
    # swing low, despite being the lowest values in the series. Per the
    # locked spec, only a LATER SWING low can breach an earlier one -- an
    # ordinary (non-swing) dip below the level, like this one, must not --
    # unlike the reference script's any-later-BAR semantics. The later
    # confirmed swing low at pos 9 (price 95) is HIGHER than 90, so it
    # doesn't breach it either.
    values = [100, 100, 90, 100, 100, 80, 80, 100, 100, 95, 100, 100, 100]
    low = _series(values)
    is_low = find_swing_lows(low, k=2)

    assert is_low.iloc[2]  # price 90 confirmed
    assert not is_low.iloc[5] and not is_low.iloc[6]  # the tied 80/80 dip never confirms

    events = annotate_swings(low, is_low, kind="low")
    swing_at_2 = next(e for e in events if e.pos == 2)
    assert swing_at_2.breach_pos is None  # never breached -- the deeper 80 dip was never a swing to begin with
    assert swing_at_2 in valid_prices_at(events, as_of_pos=len(values) - 1)


def test_a_later_swing_low_breaches_an_earlier_higher_one():
    values = [100, 100, 90, 100, 100, 100, 100, 80, 100, 100, 100, 100]
    low = _series(values)
    is_low = find_swing_lows(low, k=2)
    events = annotate_swings(low, is_low, kind="low")

    swing_at_2 = next(e for e in events if e.pos == 2)
    swing_at_7 = next(e for e in events if e.pos == 7)
    assert swing_at_2.breach_pos == 7
    assert swing_at_7.breach_pos is None

    valid_at_end = valid_prices_at(events, as_of_pos=len(values) - 1)
    assert swing_at_2 not in valid_at_end
    assert swing_at_7 in valid_at_end


def test_a_later_swing_high_breaches_an_earlier_lower_one():
    values = [1, 1, 110, 1, 1, 1, 1, 130, 1, 1, 1, 1]
    high = _series(values)
    is_high = find_swing_highs(high, k=2)
    events = annotate_swings(high, is_high, kind="high")

    swing_at_2 = next(e for e in events if e.pos == 2)
    swing_at_7 = next(e for e in events if e.pos == 7)
    assert swing_at_2.breach_pos == 7
    assert swing_at_7.breach_pos is None


def test_valid_prices_at_respects_confirmation_time_too():
    # A swing not yet reached (as_of_pos before its own pos) is never valid.
    values = [100, 100, 90, 100, 100, 100, 100, 100, 100, 100]
    low = _series(values)
    is_low = find_swing_lows(low, k=2)
    events = annotate_swings(low, is_low, kind="low")

    assert valid_prices_at(events, as_of_pos=1) == []
    assert len(valid_prices_at(events, as_of_pos=2)) == 1
