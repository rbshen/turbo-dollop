from datetime import date, timedelta

import pytest

from scoring.good_undervalued import good_and_undervalued_since, is_good_and_undervalued

MON = date(2026, 10, 5)  # a Monday


def run(pattern: str, start: date = MON, **kwargs):
    """'+' = in state, '-' = out, one char per calendar day from `start`. Unless a calendar is passed, every character is a trading day."""
    days = [(start + timedelta(days=i), c == "+") for i, c in enumerate(pattern)]
    kwargs.setdefault("trading_days", {d for d, _ in days})
    return good_and_undervalued_since(days, kwargs.pop("smoothing_days", 3), **kwargs)


def test_state_needs_a_pass_family_overall_and_an_undervalued_valuation():
    for overall in ("Strong Pass", "Pass", "Pass with caution"):
        assert is_good_and_undervalued(overall, "undervalued")
    assert not is_good_and_undervalued("Fail", "undervalued")
    assert not is_good_and_undervalued("Pass", "fair")
    assert not is_good_and_undervalued("Pass", "overvalued")
    assert not is_good_and_undervalued(None, "undervalued")
    assert not is_good_and_undervalued("Pass", None)


def test_never_in_state_is_none():
    assert run("-----") is None
    assert good_and_undervalued_since([], 5) is None


def test_since_is_the_first_in_state_trading_day():
    assert run("--+++") == MON + timedelta(days=2)
    assert run("+++++") == MON


def test_a_blip_shorter_than_the_smoothing_window_does_not_reset():
    assert run("++-++", smoothing_days=3) == MON
    assert run("++--++", smoothing_days=3) == MON  # two out-days, window is three


def test_the_nth_consecutive_out_day_resets_and_re_entry_restarts_the_clock():
    assert run("++---+", smoothing_days=3) == MON + timedelta(days=5)
    assert run("++---", smoothing_days=3) is None
    assert run("+--+--+", smoothing_days=3) == MON  # the in-state day in between restarts the out count


def test_still_counted_while_out_for_fewer_than_n_days():
    assert run("+++--", smoothing_days=3) == MON


def test_smoothing_of_one_resets_on_the_first_out_day():
    assert run("++-+", smoothing_days=1) == MON + timedelta(days=3)


def test_weekend_and_holiday_snapshots_are_neither_in_nor_out_evidence():
    # Mon..Thu in; Fri, Sat, Sun out. Without a calendar only Monday-Friday count, so that is ONE out trading day.
    week = "++++---"
    assert run(week, smoothing_days=2, trading_days=None) == MON
    assert run(week, smoothing_days=1, trading_days=None) is None
    # An out-of-state weekend snapshot that precedes Monday's entry does not start the run either.
    sat = MON - timedelta(days=2)
    assert good_and_undervalued_since([(sat, True), (MON, False)], 1) is None
    # An explicit calendar: Wednesday is a holiday, so it is not one of the three out days (Tue, Thu, Fri).
    holiday = {MON, MON + timedelta(days=1), MON + timedelta(days=3), MON + timedelta(days=4)}
    assert run("+-", smoothing_days=1, trading_days=holiday) is None
    assert run("+----", smoothing_days=4, trading_days=holiday) == MON  # only Tue, Thu, Fri count: 3 out days, window 4
    assert run("+----", smoothing_days=3, trading_days=holiday) is None


def test_a_missing_snapshot_is_not_an_out_day():
    days = [(MON, True), (MON + timedelta(days=4), False)]  # Tue-Thu absent
    assert good_and_undervalued_since(days, 2) == MON


def test_input_order_and_duplicate_dates():
    days = [(MON + timedelta(days=2), True), (MON, True), (MON + timedelta(days=1), False)]
    assert good_and_undervalued_since(days, 2) == MON
    assert good_and_undervalued_since([(MON, False), (MON, True)], 2) == MON  # the last value for a date wins


def test_rejects_a_non_positive_window():
    with pytest.raises(ValueError):
        good_and_undervalued_since([(MON, True)], 0)
