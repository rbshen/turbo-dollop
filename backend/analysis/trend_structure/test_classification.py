from datetime import date, timedelta

from analysis.trend_structure.classification import classify_swings
from analysis.trend_structure.types import SwingPoint


def _sp(day_offset: int, price: float, kind: str) -> SwingPoint:
    return SwingPoint(date=date(2024, 1, 1) + timedelta(days=day_offset), price=price, kind=kind)


def _atr_map(swings: list[SwingPoint], atr: float = 1.0) -> dict:
    return {s.date: atr for s in swings}


def test_first_swing_of_a_type_is_unclassifiable_no_trailing_history():
    swings = [_sp(0, 100.0, "high")]

    classified = classify_swings(swings, _atr_map(swings))

    assert classified == []


def test_break_above_trailing_3_high_ceiling_classifies_hh():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high"), _sp(10, 103.0, "high"), _sp(15, 110.0, "high")]

    classified = classify_swings(swings, _atr_map(swings))

    assert len(classified) == 3  # the first has no trailing history
    last = classified[-1]
    assert last.classification == "HH"
    assert last.margin == 110.0 - 105.0  # ceiling = max(100, 105, 103) = 105
    assert last.ratio == last.margin / last.atr


def test_fail_to_exceed_trailing_3_high_ceiling_classifies_lh():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high"), _sp(10, 103.0, "high"), _sp(15, 104.0, "high")]

    classified = classify_swings(swings, _atr_map(swings))

    last = classified[-1]
    assert last.classification == "LH"
    assert last.margin == 105.0 - 104.0  # ceiling - price


def test_break_below_trailing_3_low_floor_classifies_ll():
    swings = [_sp(0, 100.0, "low"), _sp(5, 95.0, "low"), _sp(10, 97.0, "low"), _sp(15, 90.0, "low")]

    classified = classify_swings(swings, _atr_map(swings))

    last = classified[-1]
    assert last.classification == "LL"
    assert last.margin == 95.0 - 90.0  # floor = min(100, 95, 97) = 95


def test_fail_to_break_trailing_3_low_floor_classifies_hl():
    swings = [_sp(0, 100.0, "low"), _sp(5, 95.0, "low"), _sp(10, 97.0, "low"), _sp(15, 96.0, "low")]

    classified = classify_swings(swings, _atr_map(swings))

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

    classified = classify_swings(swings, _atr_map(swings))

    last = classified[-1]
    assert last.classification == "LH"  # not HH -- 95 < 110 (trailing-3 max), even though 95 > 90 (prior only)


def test_swing_with_no_atr_value_is_skipped():
    swings = [_sp(0, 100.0, "high"), _sp(5, 105.0, "high")]

    classified = classify_swings(swings, {})  # no ATR for either date

    assert classified == []
