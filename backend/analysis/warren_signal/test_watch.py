"""The Warren Signals watch table's update rules (watch.py): each instruction type's stop result, the no-action arrows,
breach and the fresh-entry reset, down arrows with no row, the `after` cut, and that LP is asked for only where a rule
needs it."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from analysis.warren_signal import watch as w
from analysis.warren_signal.types import WarrenSignalEvent

T0 = datetime(2026, 1, 5, 9, 30)


def _ts(i: int) -> datetime:
    return T0 + timedelta(hours=2 * i)


def _candles(lows, closes=None) -> pd.DataFrame:
    closes = closes or [x + 1.0 for x in lows]
    return pd.DataFrame({"low": lows, "close": closes}, index=pd.DatetimeIndex([_ts(i) for i in range(len(lows))]))


def _ev(kind: str, i: int) -> WarrenSignalEvent:
    return WarrenSignalEvent(kind=kind, fired_at=_ts(i), close=0.0, rsi=None, stop_price=None)


class Lp:
    """A canned 2nd LP by candle position; counts the calls."""

    def __init__(self, by_pos=None):
        self.by_pos = by_pos or {}
        self.asked: list[int] = []

    def __call__(self, pos):
        self.asked.append(pos)
        return self.by_pos.get(pos)


def _run(lows, events, lp=None, first_yellow=(), state=None, after=None, closes=None, profile="any"):
    lp = lp or Lp()
    out = w.advance(state, _candles(lows, closes), events, [_ts(i) for i in first_yellow], profile, after, lp)
    return out, lp


FLAT = [100.0] * 12


def test_blue_up_is_an_entry_with_no_stop():
    s, lp = _run(FLAT, [_ev("blue_up", 2)])
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("blue", _ts(2), 101.0)
    assert (s.stop_price, s.stop_basis, s.status) == (None, "none", "active")
    assert s.instruction_type == 2 and s.instruction_text == "BLUE UP - Use appropriate stop."
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("blue_up", _ts(2), _ts(2))
    assert lp.asked == []


def test_fresh_yellow_up_is_a_ten_percent_stop_under_the_arrow_candle_low():
    s, lp = _run([100, 100, 80, 100, 100, 100], [_ev("yellow_up", 2)])
    assert (s.entry_kind, s.entry_price) == ("yellow", 81.0)
    assert s.stop_price == pytest.approx(72.0) and s.stop_basis == "10%"
    assert s.instruction_type == 3 and s.status == "active"
    assert lp.asked == []  # a fresh entry never needs the LP


def test_yellow_up_on_an_active_row_takes_the_lower_of_2nd_lp_and_ten_percent():
    lows = [100, 100, 80, 100, 100, 100, 90, 100, 100]
    # 10% stops: 72.0 (first yellow), 81.0 (second, low 90). LP 75 is below 81 -> LP wins.
    s, lp = _run(lows, [_ev("yellow_up", 2), _ev("yellow_up", 6)], Lp({6: 75.0}))
    assert s.stop_price == 75.0 and s.stop_basis == "LP"
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("yellow", _ts(2), 81.0)  # the entry is not moved
    assert s.last_signal_at == _ts(6) and lp.asked == [6]
    # LP 85 is above 81 -> 10% wins.
    s, _ = _run(lows, [_ev("yellow_up", 2), _ev("yellow_up", 6)], Lp({6: 85.0}))
    assert (s.stop_price, s.stop_basis) == (pytest.approx(81.0), "10%")
    # No 2nd LP at all -> 10%.
    s, _ = _run(lows, [_ev("yellow_up", 2), _ev("yellow_up", 6)], Lp())
    assert (s.stop_price, s.stop_basis) == (pytest.approx(81.0), "10%")


def test_a_second_yellow_may_move_the_stop_down_there_is_no_tighten_only_rule():
    lows = [100, 100, 100, 100, 100, 100, 60, 100]
    s, _ = _run(lows, [_ev("yellow_up", 2), _ev("yellow_up", 6)], Lp())
    assert s.stop_price == pytest.approx(54.0)  # first stop was 90.0


def test_yellow_up_on_an_active_blue_row_sets_a_stop_and_keeps_the_blue_entry():
    s, _ = _run(FLAT, [_ev("blue_up", 1), _ev("yellow_up", 5)], Lp({5: 70.0}))
    assert (s.entry_kind, s.entry_at) == ("blue", _ts(1))
    assert (s.stop_price, s.stop_basis) == (70.0, "LP")  # 10% would be 90.0
    assert s.instruction_type == 3


def test_first_yellow_after_blue_is_no_action_only_dates_move():
    s, lp = _run(FLAT, [_ev("blue_up", 1), _ev("yellow_up", 4)], Lp({4: 70.0}), first_yellow=[4])
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 2)
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("yellow_up", _ts(4), _ts(4))
    assert lp.asked == []


def test_gray_up_with_a_row_is_no_action():
    lows = [100, 100, 80, 100, 100, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 2), _ev("gray_up", 5)])
    assert (s.stop_price, s.stop_basis, s.instruction_type, s.entry_kind) == (pytest.approx(72.0), "10%", 3, "yellow")
    assert (s.latest_arrow_kind, s.last_signal_at) == ("gray_up", _ts(5))
    assert lp.asked == []


def test_gray_up_on_a_breached_row_moves_the_latest_arrow_but_freezes_last_signal_at():
    lows = [100, 100, 100, 85, 100, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 5)])
    assert (s.status, s.breached_at) == ("breached", _ts(3))
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("gray_up", _ts(5), _ts(1))
    assert (s.stop_price, s.instruction_type, s.entry_at) == (pytest.approx(90.0), 3, _ts(1))
    assert lp.asked == []


def test_gray_up_on_an_active_row_still_advances_last_signal_at():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_up", 4)])
    assert (s.status, s.latest_arrow_kind, s.last_signal_at) == ("active", "gray_up", _ts(4))
    s, _ = _run(FLAT, [_ev("gray_up", 1), _ev("gray_up", 4)])  # a gray-born row (no entry) is active too
    assert (s.entry_kind, s.last_signal_at) == (None, _ts(4))


def test_gray_up_with_no_row_creates_a_row_with_no_entry_and_no_stop_and_a_later_yellow_is_a_fresh_entry():
    s, _ = _run(FLAT, [_ev("gray_up", 2)])
    assert (s.entry_kind, s.entry_at, s.entry_price, s.stop_price, s.stop_basis) == (None, None, None, None, "none")
    assert s.instruction_type == 1 and s.status == "active"
    s, lp = _run(FLAT, [_ev("gray_up", 2), _ev("yellow_up", 5)], Lp({5: 50.0}))
    assert (s.entry_kind, s.entry_at) == ("yellow", _ts(5))
    assert (s.stop_price, s.stop_basis) == (pytest.approx(90.0), "10%")
    assert lp.asked == []


def test_a_blue_beats_a_yellow_on_the_same_candle():
    s, _ = _run(FLAT, [_ev("yellow_up", 3), _ev("blue_up", 3)])
    assert s.entry_kind == "blue" and s.stop_price is None and s.instruction_type == 2


# --- down arrows -----------------------------------------------------------------------------------------------


def test_blue_down_moves_the_stop_to_the_2nd_lp_for_either_entry_kind():
    for entry in ("blue_up", "yellow_up"):
        s, lp = _run(FLAT, [_ev(entry, 1), _ev("blue_down", 4)], Lp({4: 88.0}))
        assert (s.stop_price, s.stop_basis, s.instruction_type) == (88.0, "LP", 10)
        assert (s.latest_arrow_kind, s.latest_arrow_at) == ("blue_down", _ts(4))
        assert s.last_signal_at == _ts(1)  # a down arrow is not an up signal
        assert lp.asked == [4]


def test_yellow_down_is_the_2nd_lp_for_a_yellow_entry_and_unchanged_for_a_blue_entry():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("yellow_down", 4)], Lp({4: 88.0}))
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (88.0, "LP", 20)
    s, lp = _run(FLAT, [_ev("blue_up", 1), _ev("yellow_down", 4)], Lp({4: 88.0}))
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 20)  # text updates, stop does not
    assert lp.asked == []


def test_gray_down_is_the_entry_price_for_a_yellow_entry_below_the_close_and_unchanged_for_a_blue_entry():
    # entry price 101 (the yellow candle's close); the gray-down candle closes at 121
    rally = [100.0] * 4 + [120.0] * 8  # the market is well above the entry from the gray-down candle on
    s, lp = _run(rally, [_ev("yellow_up", 1), _ev("gray_down", 4)], closes=[101.0] * 4 + [121.0] * 8)
    assert (s.stop_price, s.stop_basis, s.instruction_type, s.status) == (101.0, "entry", 30, "active")
    assert lp.asked == []
    s, _ = _run(FLAT, [_ev("blue_up", 1), _ev("gray_down", 4)])
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 30)


CLOSES_FALLING = [101.0, 101.0, 101.0, 101.0, 95.0] + [101.0] * 7  # the gray-down candle (4) closes under the 101 entry


def test_gray_down_with_the_entry_above_the_close_leaves_the_stop_alone_and_updates_only_the_arrow_and_text():
    s, lp = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_down", 4)], closes=CLOSES_FALLING)
    assert (s.stop_price, s.stop_basis, s.status, s.breached_at) == (pytest.approx(90.0), "10%", "active", None)  # the 10% stop stays
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("yellow", _ts(1), 101.0)
    assert (s.instruction_type, s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == (30, "gray_down", _ts(4), _ts(1))
    assert lp.asked == []


def test_gray_down_with_the_entry_equal_to_the_close_also_leaves_the_stop_alone():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_down", 4)], closes=[101.0] * 12)
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (pytest.approx(90.0), "10%", 30)


def test_gray_down_with_the_entry_above_the_close_keeps_a_breached_row_breached():
    lows = [100, 100, 100, 100, 100, 85, 100, 100, 100, 100, 100, 100]  # the 10% stop (90) breaks on candle 5, gray down on 7
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 7)], closes=[101.0] * 7 + [95.0] * 5)
    assert (s.status, s.breached_at, s.stop_price, s.stop_basis) == ("breached", _ts(5), pytest.approx(90.0), "10%")
    assert (s.instruction_type, s.latest_arrow_kind) == (30, "gray_down")


def test_gray_down_on_a_row_with_no_entry_changes_only_the_text():
    s, lp = _run(FLAT, [_ev("gray_up", 1), _ev("gray_down", 4)], closes=CLOSES_FALLING)
    assert (s.entry_kind, s.stop_price, s.stop_basis, s.instruction_type) == (None, None, "none", 30) and lp.asked == []


def test_a_down_arrow_with_no_2nd_lp_leaves_the_stop_but_updates_the_text():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_down", 4)], Lp())
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (pytest.approx(90.0), "10%", 10)


def test_the_dominant_down_arrow_wins_on_one_candle():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("yellow_down", 4), _ev("blue_down", 4)], Lp({4: 88.0}))
    assert s.instruction_type == 20 and s.latest_arrow_kind == "yellow_down" and s.stop_price == 88.0


def test_a_down_arrow_with_no_row_creates_nothing_and_never_asks_for_the_lp():
    for kind in ("blue_down", "yellow_down", "gray_down"):
        s, lp = _run(FLAT, [_ev(kind, 3)], Lp({3: 50.0}))
        assert s is None and lp.asked == []


def test_a_row_with_no_entry_takes_no_stop_from_a_down_arrow():
    s, lp = _run(FLAT, [_ev("gray_up", 1), _ev("blue_down", 4)], Lp({4: 88.0}))
    assert (s.stop_price, s.instruction_type) == (None, 10) and lp.asked == []


# --- breach ----------------------------------------------------------------------------------------------------


def test_breach_marks_the_row_keeps_the_stop_and_the_last_instruction():
    lows = [100, 100, 100, 100, 85, 100, 100]  # 10% stop 90 set on candle 1; candle 4 trades 85
    s, _ = _run(lows, [_ev("yellow_up", 1)])
    assert (s.status, s.breached_at) == ("breached", _ts(4))
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (pytest.approx(90.0), "10%", 3)


def test_the_entry_candle_itself_is_not_tested_against_its_own_stop():
    s, _ = _run([100, 100, 80, 100], [_ev("yellow_up", 2)])  # low 80 <= no stop yet; stop is 72
    assert s.status == "active"
    s, _ = _run([100, 100, 100, 90.0], [_ev("yellow_up", 1)])  # stop 90.0, low 90.0 on a later candle: <= breaches
    assert s.status == "breached" and s.breached_at == _ts(3)


def test_a_row_with_no_stop_cannot_breach():
    s, _ = _run([100, 100, 1.0, 1.0], [_ev("blue_up", 1)])
    assert s.status == "active"


def test_a_stop_moved_by_a_down_arrow_is_what_later_candles_are_tested_against():
    lows = [100, 100, 100, 100, 100, 87, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("blue_down", 3)], Lp({3: 88.0}))
    assert s.status == "breached" and s.breached_at == _ts(5) and s.stop_price == 88.0  # 87 <= 88, not <= 90


def test_a_fresh_yellow_after_a_breach_resets_the_row():
    lows = [100, 100, 100, 85, 100, 100, 110, 100]
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("yellow_up", 6)], Lp({6: 1.0}))
    assert s.status == "active" and s.breached_at is None
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("yellow", _ts(6), 111.0)
    assert (s.stop_price, s.stop_basis) == (pytest.approx(99.0), "10%")  # a fresh entry: no LP, despite the cheap 2nd LP
    assert lp.asked == []


def test_a_type_4_yellow_on_a_breached_row_is_a_fresh_entry():
    # Practically unreachable (a type 4 follows a Blue, which clears the stop, so the row cannot be breached), but the
    # order of the rules is pinned: "breached -> fresh entry" is checked before the type 4 exemption.
    lows = [100, 100, 100, 85, 100, 100, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("yellow_up", 4)], first_yellow=[4])
    assert (s.status, s.entry_at, s.instruction_type) == ("active", _ts(4), 3)


def test_a_blue_after_a_breach_resets_the_row():
    lows = [100, 100, 100, 85, 100, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("blue_up", 4)])
    assert (s.status, s.breached_at, s.entry_kind, s.stop_price, s.stop_basis) == ("active", None, "blue", None, "none")


def test_gray_up_does_not_reset_a_breached_row_and_down_arrows_leave_its_stop():
    lows = [100, 100, 100, 85, 100, 100, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 4)])
    assert s.status == "breached"
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("blue_down", 5)], Lp({5: 70.0}))
    assert (s.status, s.stop_price, s.instruction_type, s.latest_arrow_kind) == ("breached", pytest.approx(90.0), 10, "blue_down")
    assert lp.asked == []


# --- the `after` cut and incremental reads ----------------------------------------------------------------------


def test_candles_and_arrows_at_or_before_after_are_not_read():
    events = [_ev("yellow_up", 2), _ev("blue_up", 5)]
    s, _ = _run(FLAT, events, after=_ts(2))
    assert s.entry_kind == "blue"  # the yellow at candle 2 is at `after`: ignored
    s, _ = _run(FLAT, events, after=_ts(5))
    assert s is None


def test_reading_in_two_steps_equals_reading_once():
    lows = [100, 100, 80, 100, 100, 100, 90, 100, 85, 100, 100, 100]
    events = [_ev("blue_up", 1), _ev("yellow_up", 2), _ev("yellow_up", 6), _ev("blue_down", 7), _ev("gray_down", 9)]
    lp = Lp({6: 75.0, 7: 80.0})
    once, _ = _run(lows, events, lp, first_yellow=[2])
    for cut in range(1, 11):
        first, _ = _run(lows[: cut + 1], [e for e in events if e.fired_at <= _ts(cut)], Lp({6: 75.0, 7: 80.0}), first_yellow=[2])
        second, _ = _run(lows, events, Lp({6: 75.0, 7: 80.0}), first_yellow=[2], state=first, after=_ts(cut))
        assert second == once, cut


def test_the_instruction_text_follows_the_profile():
    s, _ = _run(FLAT, [_ev("yellow_up", 1)], profile="tecl")
    assert s.instruction_text.startswith("YELLOW UP: new entry = 10% stop")
    s, _ = _run(FLAT, [_ev("yellow_up", 1)], profile="any")
    assert s.instruction_text == "YELLOW UP INITIAL ENTRY - Use appropriate stop."
