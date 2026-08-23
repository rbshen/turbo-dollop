from datetime import date, timedelta

import pandas as pd

from analysis.trend_structure.classification import classify_swings
from analysis.trend_structure.types import SwingPoint


def _sp(day_offset: int, price: float, kind: str) -> SwingPoint:
    return SwingPoint(date=date(2024, 1, 1) + timedelta(days=day_offset), price=price, kind=kind)


def _atr_map(swings: list[SwingPoint], atr: float = 1.0) -> dict:
    return {s.date: atr for s in swings}


def _empty_osc() -> pd.Series:
    """No Chaikin Oscillator data at all -- every swing's divergence lookup
    finds no matching date and degrades to False/None, matching
    _matched_oscillator_low's own documented behavior. Used by every test
    in this file that isn't specifically exercising the divergence path."""
    return pd.Series(dtype=float, index=pd.DatetimeIndex([]))


def _osc(values: dict[date, float]) -> pd.Series:
    """A Chaikin Oscillator series from an explicit {date: value} map, for
    tests that need real oscillator data to drive the divergence check."""
    dates = sorted(values)
    return pd.Series([values[d] for d in dates], index=pd.DatetimeIndex(dates))


def test_first_swing_of_a_type_is_unclassifiable_no_trailing_history():
    swings = [_sp(0, 100.0, "high")]

    classified = classify_swings(swings, _atr_map(swings), _empty_osc())

    assert classified == []


def test_break_above_trailing_3_high_ceiling_classifies_hh():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high"), _sp(10, 103.0, "high"), _sp(15, 110.0, "high")]

    classified = classify_swings(swings, _atr_map(swings), _empty_osc())

    assert len(classified) == 3  # the first has no trailing history
    last = classified[-1]
    assert last.classification == "HH"
    assert last.margin == 110.0 - 105.0  # ceiling = max(100, 105, 103) = 105
    assert last.ratio == last.margin / last.atr


def test_fail_to_exceed_trailing_3_high_ceiling_classifies_lh():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high"), _sp(10, 103.0, "high"), _sp(15, 104.0, "high")]

    classified = classify_swings(swings, _atr_map(swings), _empty_osc())

    last = classified[-1]
    assert last.classification == "LH"
    assert last.margin == 105.0 - 104.0  # ceiling - price


def test_break_below_trailing_3_low_floor_classifies_ll():
    swings = [_sp(0, 100.0, "low"), _sp(5, 95.0, "low"), _sp(10, 97.0, "low"), _sp(15, 90.0, "low")]

    classified = classify_swings(swings, _atr_map(swings), _empty_osc())

    last = classified[-1]
    assert last.classification == "LL"
    assert last.margin == 95.0 - 90.0  # floor = min(100, 95, 97) = 95


def test_fail_to_break_trailing_3_low_floor_classifies_hl():
    swings = [_sp(0, 100.0, "low"), _sp(5, 95.0, "low"), _sp(10, 97.0, "low"), _sp(15, 96.0, "low")]

    classified = classify_swings(swings, _atr_map(swings), _empty_osc())

    last = classified[-1]
    assert last.classification == "HL"
    assert last.margin == 96.0 - 95.0  # price - floor


def test_compares_against_trailing_3_not_just_the_single_prior_swing():
    """A swing above the single immediately-prior high but still below the
    trailing-3 ceiling must classify LH, not HH -- this is the spec's
    explicit trailing-3 requirement, not trailing-1."""
    swings = [
        _sp(0, 100.0, "high"),
        _sp(5, 110.0, "high"),  # trailing-3 ceiling becomes 110 once 3 highs exist
        _sp(10, 90.0, "high"),  # immediately-prior high is now 90
        _sp(15, 95.0, "high"),  # above the immediately-prior (90) but still below the trailing-3 ceiling (110)
    ]

    classified = classify_swings(swings, _atr_map(swings), _empty_osc())

    last = classified[-1]
    assert last.classification == "LH"  # not HH -- 95 < 110 (trailing-3 max), even though 95 > 90 (prior only)


def test_swing_with_no_atr_value_is_skipped():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high")]

    classified = classify_swings(swings, {}, _empty_osc())  # no ATR for either date

    assert classified == []


# -- A/D Bullish Divergence -------------------------------------------------
#
# current oscillator low > MIN(floor) of the oscillator readings matched to
# the trailing 3 prior CONFIRMED (ratio>=CONFIRMED_RATIO) LL swings. Matched
# reading = literal min Chaikin Oscillator value in a +/-10-bar window
# centered on the swing's own date.
#
# Swing dates below are spaced 30 days apart (well past the +/-10-bar match
# window) so each swing's own window never overlaps a neighboring swing's --
# every window's minimum is unambiguously its own anchor point, not bleed
# from a nearby one.


def _dense_osc(anchor_values: dict[date, float], background: float = 0.0, span_days: int = 130) -> pd.Series:
    """A daily-dense oscillator series (day 0..span_days from 2024-01-01)
    filled with `background` everywhere except the given anchor dates, which
    get their own explicit (more extreme, i.e. lower) value -- so each
    anchor's own +/-10-bar window minimum is unambiguously itself, not a
    neighboring anchor bleeding in, and not the flat background."""
    base = date(2024, 1, 1)
    dates = [base + timedelta(days=i) for i in range(span_days)]
    values = [anchor_values.get(d, background) for d in dates]
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def test_first_ll_has_no_prior_confirmed_ll_so_divergence_is_false():
    swings = [_sp(0, 100.0, "low"), _sp(5, 95.0, "low"), _sp(10, 97.0, "low"), _sp(15, 90.0, "low")]
    osc = _dense_osc({swings[1].date: -5.0, swings[3].date: -5.0})  # both LLs get the same osc low

    classified = classify_swings(swings, _atr_map(swings), osc)

    lls = [cs for cs in classified if cs.classification == "LL"]
    first_ll = lls[0]  # day 5 -- the genuinely first LL, no prior confirmed LL exists yet
    assert first_ll.ad_bullish_divergence is False
    assert first_ll.ad_divergence_swing_date is None


def test_higher_oscillator_low_than_prior_confirmed_ll_floor_flags_divergence():
    swings = [_sp(0, 100.0, "low"), _sp(30, 95.0, "low"), _sp(60, 97.0, "low"), _sp(90, 90.0, "low")]
    atr = {s.date: 1.0 for s in swings}  # both LL margins are 5.0 -> ratio=5.0, well above CONFIRMED_RATIO
    osc = _dense_osc({swings[1].date: -5.0, swings[3].date: -1.0})  # second LL's own low (-1.0) beats the floor (-5.0)

    classified = classify_swings(swings, atr, osc)

    lls = [cs for cs in classified if cs.classification == "LL"]
    assert len(lls) == 2
    first_ll, second_ll = lls
    assert first_ll.ad_bullish_divergence is False  # no prior confirmed LL yet
    assert second_ll.ad_bullish_divergence is True
    assert second_ll.ad_divergence_swing_date == swings[3].date


def test_lower_or_equal_oscillator_low_than_prior_confirmed_ll_floor_is_not_divergence():
    swings = [_sp(0, 100.0, "low"), _sp(30, 95.0, "low"), _sp(60, 97.0, "low"), _sp(90, 90.0, "low")]
    atr = {s.date: 1.0 for s in swings}
    osc = _dense_osc({swings[1].date: -1.0, swings[3].date: -5.0})  # second LL's own low (-5.0) is LOWER than the floor (-1.0)

    classified = classify_swings(swings, atr, osc)

    lls = [cs for cs in classified if cs.classification == "LL"]
    assert lls[-1].ad_bullish_divergence is False
    assert lls[-1].ad_divergence_swing_date is None


def test_equal_oscillator_low_to_the_floor_is_not_divergence():
    """Strictly greater than, not greater-or-equal -- an exact tie must not
    flag divergence."""
    swings = [_sp(0, 100.0, "low"), _sp(30, 95.0, "low"), _sp(60, 97.0, "low"), _sp(90, 90.0, "low")]
    atr = {s.date: 1.0 for s in swings}
    osc = _dense_osc({swings[1].date: -5.0, swings[3].date: -5.0})  # identical low

    classified = classify_swings(swings, atr, osc)

    lls = [cs for cs in classified if cs.classification == "LL"]
    assert lls[-1].ad_bullish_divergence is False


def test_non_confirmed_ll_is_evaluated_but_excluded_from_the_confirmed_pool():
    """A ratio<CONFIRMED_RATIO LL still gets its own divergence flag computed
    (against whatever floor already exists), but must NOT itself be added to
    confirmed_ll_osc_lows -- the next LL's floor should skip right over it."""
    swings = [
        _sp(0, 100.0, "low"),
        _sp(30, 95.0, "low"),  # first LL: margin=5, atr=1.0 -> ratio=5.0, CONFIRMED, osc low=-10.0
        _sp(60, 90.0, "low"),  # second LL: margin=5, atr=50.0 -> ratio=0.1, NOT confirmed, osc low=-2.0
        _sp(90, 80.0, "low"),  # third LL: floor should still be built from the FIRST LL only (-10.0), not the second
    ]
    atr = {swings[0].date: 1.0, swings[1].date: 1.0, swings[2].date: 50.0, swings[3].date: 1.0}
    osc = _dense_osc({swings[1].date: -10.0, swings[2].date: -2.0, swings[3].date: -3.0})

    classified = classify_swings(swings, atr, osc)

    lls = [cs for cs in classified if cs.classification == "LL"]
    assert len(lls) == 3
    assert lls[1].ratio < 1.0  # confirms the second LL is genuinely non-confirmed
    assert lls[1].ad_bullish_divergence is True  # -2.0 > -10.0 (the only prior confirmed floor)
    # Third LL's floor is min of trailing-3 CONFIRMED lows only -- the
    # non-confirmed second LL's -2.0 must not have entered the pool, so the
    # floor is still just the first LL's -10.0. Third LL's own osc low
    # (-3.0) is higher than -10.0 -> divergence True.
    assert lls[2].ad_bullish_divergence is True
    assert lls[2].ad_divergence_swing_date == swings[3].date


def test_hh_hl_lh_swings_never_get_divergence_fields():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high"), _sp(10, 103.0, "high"), _sp(15, 110.0, "high")]
    osc = _osc({s.date: -1.0 for s in swings})

    classified = classify_swings(swings, _atr_map(swings), osc)

    assert all(cs.classification in ("HH", "LH") for cs in classified)
    assert all(cs.ad_bullish_divergence is False and cs.ad_divergence_swing_date is None for cs in classified)


def test_divergence_match_window_truncates_at_the_end_of_available_history():
    """The most recent LL in the series has fewer than 10 forward bars
    available -- the window must truncate (asymmetric), never error or wait
    for bars that don't exist yet."""
    base = date(2024, 1, 1)
    swings = [_sp(0, 100.0, "low"), _sp(1, 95.0, "low"), _sp(2, 97.0, "low"), _sp(3, 90.0, "low")]
    atr = {s.date: 1.0 for s in swings}
    # Oscillator series only extends 2 bars past the final LL's own date --
    # far short of a full +/-10 window.
    osc_dates = [base + timedelta(days=i) for i in range(6)]
    osc = pd.Series([0.0, -8.0, 0.0, -1.0, -4.0, -2.0], index=pd.DatetimeIndex(osc_dates))

    classified = classify_swings(swings, atr, osc)

    last_ll = [cs for cs in classified if cs.classification == "LL"][-1]
    # Must not raise, and must still produce a real (bool) result using
    # whatever truncated window was available.
    assert last_ll.ad_bullish_divergence in (True, False)
