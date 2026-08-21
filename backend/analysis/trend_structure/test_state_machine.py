from datetime import date, timedelta

from analysis.trend_structure.classification import ClassifiedSwing
from analysis.trend_structure.state_machine import run_state_machine
from analysis.trend_structure.types import SwingPoint


def _cs(day_offset: int, classification: str, ratio: float) -> ClassifiedSwing:
    kind = "high" if classification in ("HH", "LH") else "low"
    d = date(2024, 1, 1) + timedelta(days=day_offset)
    atr = 1.0
    margin = ratio * atr
    return ClassifiedSwing(swing=SwingPoint(date=d, price=100.0, kind=kind), classification=classification, margin=margin, atr=atr, ratio=ratio)


def test_empty_classified_list_returns_documented_bootstrap_default():
    state = run_state_machine([])

    assert state.trend_state == "uptrend"
    assert state.magnitude_tier is None
    assert state.persistence_count == 0
    assert state.warning_flag is False


def test_confirmed_hh_flips_to_uptrend_from_downtrend():
    classified = [_cs(0, "LL", 1.2), _cs(5, "HH", 1.0)]  # bootstrap/establish downtrend  # confirmed flip trigger, ratio>=1.0

    state = run_state_machine(classified)

    assert state.trend_state == "uptrend"
    assert state.persistence_count == 1  # reset -- first swing of the new trend
    assert state.warning_flag is False


def test_confirmed_ll_flips_to_downtrend_from_uptrend():
    classified = [_cs(0, "HH", 1.2), _cs(5, "LL", 1.0)]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert state.persistence_count == 1


def test_confirmed_lh_during_uptrend_never_flips_only_sets_warning():
    classified = [_cs(0, "HH", 1.2), _cs(5, "LH", 0.9)]  # establish uptrend  # bearish-secondary swing against the uptrend

    state = run_state_machine(classified)

    assert state.trend_state == "uptrend"  # never flips on LH, regardless of ratio
    assert state.warning_flag is True
    assert state.warning_swing is not None
    assert state.warning_swing.ratio == 0.9


def test_confirmed_hl_during_downtrend_never_flips_only_sets_warning():
    classified = [_cs(0, "LL", 1.2), _cs(5, "HL", 0.6)]  # establish downtrend  # bullish-secondary swing against the downtrend

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"  # never flips on HL, regardless of ratio
    assert state.warning_flag is True


def test_lh_sets_warning_even_at_tentative_ratio_below_weak_floor():
    """Spec: "A confirmed LH or HL -- regardless of ratio -- ... only sets
    warning_flag=true" -- even a ratio below the 0.5 weak-confirmed floor
    still sets the warning."""
    classified = [_cs(0, "HH", 1.2), _cs(5, "LH", 0.2)]

    state = run_state_machine(classified)

    assert state.warning_flag is True
    assert state.warning_swing.ratio == 0.2


def test_weak_hh_below_confirmed_ratio_while_downtrend_is_a_documented_noop():
    """A sub-1.0-ratio HH occurring against an established downtrend is
    neither a flip (needs ratio>=1.0) nor a named warning-setting event (the
    spec only names LH/HL for that) -- a deliberate no-op, not a missed case."""
    classified = [_cs(0, "LL", 1.2), _cs(5, "HH", 0.7)]  # establish downtrend  # primary-for-opposite-direction, ratio<1.0

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"  # not flipped
    assert state.warning_flag is False  # no warning set
    assert state.persistence_count == 1  # unaffected -- still just the bootstrap LL


def test_tentative_same_direction_swing_bumps_persistence_not_magnitude_tier():
    """The specific fix this feature's spec calls out by name: a tentative
    (<0.5 ratio) same-direction swing still increments persistence_count but
    must NOT change magnitude_tier."""
    classified = [
        _cs(0, "HH", 1.2),  # establishes uptrend, magnitude_tier="confirmed" (1.0<=1.2<1.5)
        _cs(5, "HL", 0.3),  # tentative (ratio<0.5), same direction (bullish, uptrend)
    ]

    state = run_state_machine(classified)

    assert state.persistence_count == 2  # both swings counted
    assert state.magnitude_tier == "confirmed"  # unchanged by the tentative swing


def test_warning_clears_on_next_same_direction_confirmed_swing():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # sets warning
        _cs(10, "HL", 0.6),  # same-direction (bullish) confirmed (>=0.5) swing -- clears warning
    ]

    state = run_state_machine(classified)

    assert state.warning_flag is False
    assert state.warning_swing is None
    assert state.trend_state == "uptrend"


def test_warning_converts_into_real_flip_when_opposite_extreme_confirms():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # warning set
        _cs(10, "LL", 1.1),  # genuine confirmed opposite extreme -- real flip
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert state.warning_flag is False
    assert state.warning_swing is None
    assert state.persistence_count == 1
