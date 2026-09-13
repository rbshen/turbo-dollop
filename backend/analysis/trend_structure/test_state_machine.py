from datetime import date, timedelta

from analysis.trend_structure.classification import ClassifiedSwing
from analysis.trend_structure.state_machine import run_state_machine
from analysis.trend_structure.types import SwingPoint


def _cs(
    day_offset: int, classification: str, ratio: float, ad_bullish_divergence: bool = False, ad_divergence_swing_date: date | None = None
) -> ClassifiedSwing:
    kind = "high" if classification in ("HH", "LH") else "low"
    d = date(2024, 1, 1) + timedelta(days=day_offset)
    atr = 1.0
    margin = ratio * atr
    return ClassifiedSwing(
        swing=SwingPoint(date=d, price=100.0, kind=kind),
        classification=classification,
        margin=margin,
        atr=atr,
        ratio=ratio,
        ad_bullish_divergence=ad_bullish_divergence,
        ad_divergence_swing_date=ad_divergence_swing_date,
    )


def test_empty_classified_list_returns_documented_bootstrap_default():
    state = run_state_machine([])

    assert state.trend_state == "uptrend"
    assert state.magnitude_tier is None
    assert state.persistence_count == 0
    assert state.warning_flag is False
    assert state.pullback_occurred_since_flip is False


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
    # warning_flag clears, but the pullback still genuinely happened within
    # this trend -- pullback_occurred_since_flip must stay True so a caller
    # can tell "resolved" apart from "never occurred."
    assert state.pullback_occurred_since_flip is True


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
    # The flip starts a brand-new trend -- the prior trend's pullback is no
    # longer relevant to it.
    assert state.pullback_occurred_since_flip is False


def test_pullback_occurred_since_flip_is_false_immediately_after_establishing_a_trend():
    """No warning has ever fired yet -- the "no pullback at all" case this
    field exists to distinguish from a resolved one."""
    classified = [_cs(0, "HH", 1.2), _cs(5, "HL", 0.8)]  # establish uptrend  # same-direction confirming swing, no warning involved

    state = run_state_machine(classified)

    assert state.warning_flag is False
    assert state.pullback_occurred_since_flip is False


def test_pullback_occurred_since_flip_set_by_warning_even_at_tentative_ratio():
    """Mirrors warning_flag's own "regardless of ratio" rule -- a tentative
    LH still counts as a real pullback having occurred."""
    classified = [_cs(0, "HH", 1.2), _cs(5, "LH", 0.2)]

    state = run_state_machine(classified)

    assert state.warning_flag is True
    assert state.pullback_occurred_since_flip is True


def test_pullback_occurred_since_flip_persists_across_a_second_later_warning():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # first warning
        _cs(10, "HL", 0.6),  # clears warning_flag, pullback_occurred_since_flip stays True
        _cs(15, "LH", 0.7),  # second warning, same trend
    ]

    state = run_state_machine(classified)

    assert state.warning_flag is True
    assert state.pullback_occurred_since_flip is True


def test_bootstrap_sets_flip_swing_as_a_lower_bound_when_no_real_flip_ever_occurs():
    """No genuine flip anywhere in this classified history -- the current
    trend covers the ticker's entire available history, so flip_swing falls
    back to the very first classified swing, flagged as a lower bound (the
    true start may predate the cached data) rather than left null."""
    classified = [_cs(0, "HH", 1.2), _cs(5, "HL", 0.8), _cs(10, "HH", 1.1)]

    state = run_state_machine(classified)

    assert state.flip_swing is not None
    assert state.flip_swing.date == classified[0].swing.date
    assert state.flip_swing_is_lower_bound is True


def test_genuine_flip_sets_flip_swing_and_clears_the_lower_bound_flag():
    classified = [
        _cs(0, "HH", 1.2),  # bootstraps uptrend -- flip_swing is a lower bound here
        _cs(5, "HL", 0.8),
        _cs(10, "LL", 1.3),  # genuine confirmed flip to downtrend
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert state.flip_swing is not None
    assert state.flip_swing.date == classified[2].swing.date  # the actual flip trigger, not the bootstrap swing
    assert state.flip_swing.classification == "LL"
    assert state.flip_swing_is_lower_bound is False


def test_flip_swing_stays_at_the_most_recent_flip_across_further_confirming_moves():
    """flip_swing must not drift to the latest confirming swing the way
    last_confirmed_swing does -- it's pinned to the flip itself."""
    classified = [
        _cs(0, "LL", 1.2),  # bootstraps downtrend
        _cs(5, "HH", 1.4),  # genuine flip to uptrend
        _cs(10, "HL", 0.9),  # ordinary confirming move -- must not move flip_swing
        _cs(15, "HH", 1.6),  # another confirming move
    ]

    state = run_state_machine(classified)

    assert state.persistence_count == 3
    assert state.last_confirmed_swing.date == classified[3].swing.date
    assert state.flip_swing.date == classified[1].swing.date
    assert state.flip_swing_is_lower_bound is False


def test_empty_classified_list_leaves_flip_swing_unset():
    state = run_state_machine([])

    assert state.flip_swing is None
    assert state.flip_swing_is_lower_bound is False


def test_pullback_history_is_empty_when_no_warning_has_ever_resolved():
    classified = [_cs(0, "HH", 1.2), _cs(5, "HL", 0.8)]  # establish uptrend  # ordinary confirming move, no warning involved

    state = run_state_machine(classified)

    assert state.pullback_history == []


def test_pullback_history_does_not_record_a_still_pending_warning():
    classified = [_cs(0, "HH", 1.2), _cs(5, "LH", 0.8)]  # establish uptrend  # sets warning, never resolved

    state = run_state_machine(classified)

    assert state.warning_flag is True
    assert state.pullback_history == []


def test_pullback_history_records_a_resolved_cycle_with_both_swings():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # warning
        _cs(10, "HL", 0.6),  # clears it -- a completed cycle
    ]

    state = run_state_machine(classified)

    assert len(state.pullback_history) == 1
    cycle = state.pullback_history[0]
    assert cycle.warning_swing.date == classified[1].swing.date
    assert cycle.warning_swing.classification == "LH"
    assert cycle.resolving_swing.date == classified[2].swing.date
    assert cycle.resolving_swing.classification == "HL"


def test_pullback_history_accumulates_multiple_resolved_cycles_within_the_same_trend():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # warning 1
        _cs(10, "HL", 0.6),  # resolves cycle 1
        _cs(15, "HH", 1.3),  # ordinary confirming move, no warning involved
        _cs(20, "LH", 0.7),  # warning 2
        _cs(25, "HL", 0.9),  # resolves cycle 2
    ]

    state = run_state_machine(classified)

    assert len(state.pullback_history) == 2
    assert state.pullback_history[0].warning_swing.date == classified[1].swing.date
    assert state.pullback_history[0].resolving_swing.date == classified[2].swing.date
    assert state.pullback_history[1].warning_swing.date == classified[4].swing.date
    assert state.pullback_history[1].resolving_swing.date == classified[5].swing.date


def test_pullback_history_resets_on_a_genuine_flip():
    """A resolved cycle from the PRIOR trend must not leak into the new
    trend's history -- pullback_history is scoped to the current trend only,
    same lifecycle as pullback_occurred_since_flip/flip_swing."""
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # warning
        _cs(10, "HL", 0.6),  # resolves cycle 1 -- this uptrend's own history
        _cs(15, "LL", 1.4),  # genuine flip to downtrend
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert state.pullback_history == []


def test_pullback_history_discards_a_still_pending_warning_superseded_by_a_flip():
    """A warning that never resolved bullishly -- the trend reversed instead
    -- is never recorded as a completed cycle, even though it's the same
    warning_swing a caller could otherwise see via TrendContinuationCard's
    own "Invalidated" reading."""
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LH", 0.8),  # warning, still pending
        _cs(10, "LL", 1.5),  # flip -- warning superseded, not resolved
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert state.pullback_history == []


def test_reversal_history_is_empty_while_still_uptrend():
    classified = [_cs(0, "HH", 1.2), _cs(5, "HL", 0.8)]  # establish uptrend  # ordinary confirming move

    state = run_state_machine(classified)

    assert state.trend_state == "uptrend"
    assert state.reversal_history == []


def test_reversal_history_seeds_with_the_flip_triggering_ll_unlike_pullback_history():
    """UNLIKE pullback_history (reset to [] on a flip), reversal_history is
    seeded with the flip-triggering LL itself -- a freshly-flipped
    downtrend's history must not be empty while last_confirmed_swing/
    ReversalCard's own "Confirmed" checklist item already reads true off
    this exact swing."""
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LL", 1.4, ad_bullish_divergence=True, ad_divergence_swing_date=date(2024, 1, 4)),  # genuine flip to downtrend
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert len(state.reversal_history) == 1
    candidate = state.reversal_history[0]
    assert candidate.swing.date == classified[1].swing.date
    assert candidate.swing.classification == "LL"
    assert candidate.ad_bullish_divergence is True
    assert candidate.ad_divergence_swing_date == date(2024, 1, 4)


def test_reversal_history_stays_empty_when_flipping_into_an_uptrend():
    classified = [
        _cs(0, "LL", 1.2),  # bootstrap/establish downtrend
        _cs(5, "HH", 1.0),  # genuine flip to uptrend
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "uptrend"
    assert state.reversal_history == []


def test_reversal_history_accumulates_further_confirmed_lls_within_the_same_downtrend():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LL", 1.4),  # genuine flip to downtrend -- seeds reversal_history[0]
        _cs(10, "HL", 0.8),  # warning against the downtrend, no effect on reversal_history
        _cs(15, "LH", 0.6),  # resolves the warning, no effect on reversal_history (not an LL)
        _cs(20, "LL", 1.1, ad_bullish_divergence=True, ad_divergence_swing_date=date(2024, 1, 19)),  # a further confirmed LL
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert len(state.reversal_history) == 2
    assert state.reversal_history[0].swing.date == classified[1].swing.date
    assert state.reversal_history[0].ad_bullish_divergence is False
    assert state.reversal_history[1].swing.date == classified[4].swing.date
    assert state.reversal_history[1].ad_bullish_divergence is True
    assert state.reversal_history[1].ad_divergence_swing_date == date(2024, 1, 19)


def test_reversal_history_excludes_a_weak_below_confirmed_ratio_ll():
    """A same-direction LL below CONFIRMED_RATIO still updates
    last_confirmed_swing (ratio>=WEAK_RATIO), but is not a "confirmed" LL
    -- ReversalCard's own gate requires magnitude_tier confirmed/strong,
    so reversal_history must not include it either."""
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LL", 1.4),  # genuine flip to downtrend -- seeds reversal_history[0]
        _cs(10, "LL", 0.7),  # same-direction LL, weak-confirmed but below CONFIRMED_RATIO
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "downtrend"
    assert len(state.reversal_history) == 1
    assert state.reversal_history[0].swing.date == classified[1].swing.date


def test_reversal_history_resets_on_a_further_flip_back_to_uptrend():
    classified = [
        _cs(0, "HH", 1.2),  # establish uptrend
        _cs(5, "LL", 1.4),  # flip to downtrend -- seeds reversal_history[0]
        _cs(10, "LL", 1.1),  # a second confirmed LL within this downtrend
        _cs(15, "HH", 1.3),  # flip back to uptrend -- clears reversal_history
    ]

    state = run_state_machine(classified)

    assert state.trend_state == "uptrend"
    assert state.reversal_history == []
