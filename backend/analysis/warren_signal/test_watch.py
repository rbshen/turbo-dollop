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


def _run(lows, events, lp=None, first_yellow=(), state=None, after=None, closes=None, profile="any", trail=False, log=None, rules=w.CURRENT_RULES):
    """The arrow rules are pinned with trailing OFF (the default here); the trailing tests below pass trail=True."""
    lp = lp or Lp()
    out = w.advance(state, _candles(lows, closes), events, [_ts(i) for i in first_yellow], profile, after, lp, trail, log, rules)
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
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 4)  # the text follows the pill: "FIRST YELLOW UP ... NO ACTION"
    assert s.instruction_text == "FIRST YELLOW UP ARROW AFTER BLUE ENTRY - NO ACTION"
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("yellow_up", _ts(4), _ts(4))
    assert lp.asked == []
    old, _ = _run(FLAT, [_ev("blue_up", 1), _ev("yellow_up", 4)], Lp({4: 70.0}), first_yellow=[4], rules=w.PRE_RAISE_ONLY_RULES)
    assert old.instruction_type == 2  # the previous rules left the Blue Up text under the Yellow pill


def test_gray_up_with_a_row_is_no_action():
    lows = [100, 100, 80, 100, 100, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 2), _ev("gray_up", 5)])
    assert (s.stop_price, s.stop_basis, s.instruction_type, s.entry_kind) == (pytest.approx(72.0), "10%", 1, "yellow")  # the text follows the Gray pill
    assert (s.latest_arrow_kind, s.last_signal_at) == ("gray_up", _ts(5))
    assert lp.asked == []


def test_previous_rules_a_gray_up_on_a_breached_row_moved_the_latest_arrow_but_froze_last_signal_at():
    lows = [100, 100, 100, 85, 100, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 5)], rules=w.LEGACY_RULES)
    assert (s.status, s.breached_at) == ("breached", _ts(3))
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("gray_up", _ts(5), _ts(1))
    assert (s.stop_price, s.instruction_type, s.entry_at) == (pytest.approx(90.0), 3, _ts(1))
    assert lp.asked == []


def test_gray_up_on_an_active_row_with_an_entry_moves_only_the_arrow_and_the_dates():
    s, lp = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_up", 4)])
    assert (s.status, s.latest_arrow_kind, s.last_signal_at) == ("active", "gray_up", _ts(4))
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("yellow", _ts(1), 101.0)  # entry unchanged
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.instruction_type) == (pytest.approx(90.0), "10%", _ts(1), 1)  # stop unchanged; the instruction follows the pill (Gray Up)
    assert s.instruction_text == "GRAY UP - NO ACTION. Stopped out twice."
    s, _ = _run(FLAT, [_ev("blue_up", 1), _ev("gray_up", 4)])  # a blue entry (no stop) is an open trade too
    assert (s.entry_kind, s.entry_at, s.stop_price, s.last_signal_at) == ("blue", _ts(1), None, _ts(4))
    assert lp.asked == []


def test_previous_rules_a_gray_born_row_has_no_entry_and_a_later_gray_up_only_moves_the_dates():
    s, _ = _run(FLAT, [_ev("gray_up", 2)], rules=w.LEGACY_RULES)
    assert (s.entry_kind, s.entry_at, s.entry_price, s.stop_price, s.stop_basis) == (None, None, None, None, "none")
    assert s.instruction_type == 1 and s.status == "active"
    s, lp = _run(FLAT, [_ev("gray_up", 2), _ev("yellow_up", 5)], Lp({5: 50.0}), rules=w.LEGACY_RULES)
    assert (s.entry_kind, s.entry_at) == ("yellow", _ts(5))
    assert (s.stop_price, s.stop_basis) == (pytest.approx(90.0), "10%")
    assert lp.asked == []
    s, _ = _run(FLAT, [_ev("gray_up", 1), _ev("gray_up", 4)], rules=w.LEGACY_RULES)
    assert (s.entry_kind, s.last_signal_at) == (None, _ts(4))


# --- Gray Up as an entry (2026-10-17) ----------------------------------------------------------------------------


def test_gray_up_with_no_row_is_a_gray_entry_at_the_close_with_a_ten_percent_stop_under_the_low():
    lows = [100, 100, 80, 100, 100, 100, 100]
    s, lp = _run(lows, [_ev("gray_up", 2)], closes=[101, 101, 95, 101, 101, 101, 101])
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("gray", _ts(2), 95.0)
    assert (s.stop_price, s.stop_basis, s.status, s.breached_at) == (pytest.approx(72.0), "10%", "active", None)
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(2), "gray_up_entry")
    assert (s.instruction_type, s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == (1, "gray_up", _ts(2), _ts(2))
    assert lp.asked == []  # no 2nd LP is needed for a fresh entry


def test_gray_up_on_a_breached_row_restarts_it_as_a_gray_entry():
    lows = [100, 100, 100, 85, 100, 70, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 5)], closes=[101] * 5 + [88.0] + [101] * 2)
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("gray", _ts(5), 88.0)  # the yellow trade is gone
    assert (s.status, s.breached_at) == ("active", None)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (pytest.approx(63.0), "10%", _ts(5), "gray_up_entry")
    assert (s.last_signal_at, s.latest_arrow_kind, s.instruction_type) == (_ts(5), "gray_up", 1)
    assert lp.asked == []


def test_gray_up_on_a_row_that_has_no_entry_is_also_an_entry():
    legacy, _ = _run(FLAT, [_ev("gray_up", 1)], rules=w.LEGACY_RULES)  # an entry-less stored row
    s, _ = _run(FLAT, [_ev("gray_up", 4)], state=legacy, after=_ts(2))
    assert (s.entry_kind, s.entry_at, s.entry_price, s.stop_price) == ("gray", _ts(4), 101.0, pytest.approx(90.0))


def test_a_gray_up_and_a_breach_on_the_same_candle_restarts_the_row_as_a_gray_entry():
    # candle 4's low (85) breaches the 90 stop in force before the candle; its Gray Up then finds a breached row and restarts it
    lows = [100, 100, 100, 100, 85, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 4)], closes=[101, 101, 101, 101, 92.0, 101])
    assert (s.entry_kind, s.entry_at, s.entry_price, s.status, s.breached_at) == ("gray", _ts(4), 92.0, "active", None)
    assert s.stop_price == pytest.approx(76.5)


# --- a gray-entry row follows the yellow-entry rules afterwards --------------------------------------------------


def _gray_row(lows, extra, lp=None, closes=None, trail=False, rules=w.CURRENT_RULES):
    """A gray entry on candle 1, then `extra` events."""
    return _run(lows, [_ev("gray_up", 1), *extra], lp, closes=closes, trail=trail, rules=rules)


def test_gray_down_on_a_gray_entry_moves_the_stop_to_the_entry_price_when_the_entry_is_below_the_close():
    rally = [100.0] * 4 + [120.0] * 8
    s, lp = _gray_row(rally, [_ev("gray_down", 4)], closes=[101.0] * 4 + [121.0] * 8)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.entry_kind, s.instruction_type) == (101.0, "entry", "gray_down", "gray", 30)
    assert lp.asked == []


def test_gray_down_on_a_gray_entry_leaves_the_stop_when_the_entry_is_at_or_above_the_close():
    s, _ = _gray_row(FLAT, [_ev("gray_down", 4)], closes=CLOSES_FALLING)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.instruction_type, s.latest_arrow_kind) == (pytest.approx(90.0), "10%", "gray_up_entry", 30, "gray_down")
    s, _ = _gray_row(FLAT, [_ev("gray_down", 4)], closes=[101.0] * 12)  # equal
    assert (s.stop_price, s.stop_basis) == (pytest.approx(90.0), "10%")


@pytest.mark.parametrize("kind, instruction, moved_by", [("yellow_down", 20, "yellow_down"), ("blue_down", 10, "blue_down")])
def test_yellow_down_and_blue_down_on_a_gray_entry_raise_the_stop_to_a_higher_2nd_lp(kind, instruction, moved_by):
    s, lp = _gray_row(FLAT, [_ev(kind, 4)], Lp({4: 95.0}))  # the 10% stop is 90
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.instruction_type, s.entry_kind) == (95.0, "LP", moved_by, instruction, "gray")
    assert lp.asked == [4]
    s, _ = _gray_row(FLAT, [_ev(kind, 4)], Lp({4: 88.0}))  # a lower 2nd LP is not a cut: the stop, its basis and its age stay
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by, s.instruction_type) == (pytest.approx(90.0), "10%", _ts(1), "gray_up_entry", instruction)


def test_a_repeat_yellow_up_on_an_active_gray_entry_sets_min_2nd_lp_and_ten_percent_and_keeps_the_gray_entry():
    lows = [100] * 3 + [95] + [100] * 8  # the arrow candle's low (95) stays above the 90 stop, so the row is not breached
    s, lp = _gray_row(lows, [_ev("yellow_up", 3)], Lp({3: 50.0}))  # entry 101 @ candle 1; stop 90 -> min(50, 85.5) = 50
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("gray", _ts(1), 101.0)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.instruction_type) == (50.0, "LP", "yellow_up_repeat", 3)
    s, _ = _gray_row(lows, [_ev("yellow_up", 3)], Lp({3: 99.0}))
    assert (s.stop_price, s.stop_basis) == (pytest.approx(85.5), "10%") and s.entry_kind == "gray"


def test_a_first_yellow_after_a_blue_on_an_active_gray_entry_is_no_action():
    s, _ = _run(FLAT, [_ev("gray_up", 1), _ev("yellow_up", 4)], first_yellow=(4,))
    assert (s.entry_kind, s.entry_at, s.stop_price, s.stop_moved_by) == ("gray", _ts(1), pytest.approx(90.0), "gray_up_entry")
    assert (s.latest_arrow_kind, s.last_signal_at) == ("yellow_up", _ts(4))


def test_a_blue_up_on_an_active_gray_entry_keeps_the_entry_and_the_stop():
    s, lp = _gray_row(FLAT, [_ev("blue_up", 4)])
    assert (s.entry_kind, s.entry_at, s.entry_price) == ("gray", _ts(1), 101.0)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (pytest.approx(90.0), "10%", _ts(1), "gray_up_entry")
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at, s.instruction_type, s.status) == ("blue_up", _ts(4), _ts(4), 5, "active")
    assert lp.asked == []
    s, _ = _gray_row(FLAT, [_ev("blue_up", 4)], rules=w.PRE_RAISE_ONLY_RULES)  # the previous rules gave the same trade; only the text differed
    assert (s.entry_kind, s.entry_at, s.stop_price, s.instruction_type) == ("gray", _ts(1), pytest.approx(90.0), 2)


def test_the_gray_entry_kind_stays_through_a_breach_free_trade_with_trailing():
    s, lp = _gray_row(FLAT, [_ev("blue_down", 3)], Lp({3: 92.0, 5: 95.0, 7: 94.0}), trail=True)
    assert (s.entry_kind, s.stop_price, s.stop_basis, s.stop_moved_by) == ("gray", 95.0, "LP", "trail")  # an LP stop trails up, never down
    s, lp = _gray_row(FLAT, [], Lp({5: 99.0}), trail=True)
    assert (s.stop_price, s.stop_basis) == (pytest.approx(90.0), "10%") and lp.asked == []  # a 10% stop never trails


def test_a_gray_entry_that_is_breached_then_restarts_by_any_up_arrow():
    lows = [100, 100, 100, 85, 100, 100, 100]
    for up, kind in (("gray_up", "gray"), ("yellow_up", "yellow"), ("blue_up", "blue")):
        s, _ = _run(lows, [_ev("gray_up", 1), _ev(up, 5)])
        assert (s.entry_kind, s.entry_at, s.status, s.breached_at) == (kind, _ts(5), "active", None)


def test_a_blue_beats_a_yellow_on_the_same_candle():
    s, _ = _run(FLAT, [_ev("yellow_up", 3), _ev("blue_up", 3)])
    assert s.entry_kind == "blue" and s.stop_price is None and s.instruction_type == 2


# --- down arrows -----------------------------------------------------------------------------------------------


def test_blue_down_sets_the_2nd_lp_on_a_blue_entry_with_no_stop_and_raises_a_lower_stop_on_a_yellow_entry():
    s, lp = _run(FLAT, [_ev("blue_up", 1), _ev("blue_down", 4)], Lp({4: 88.0}))  # no stop yet: the 2nd LP, wherever it is
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (88.0, "LP", 10)
    assert (s.latest_arrow_kind, s.latest_arrow_at) == ("blue_down", _ts(4))
    assert s.last_signal_at == _ts(1)  # a down arrow is not an up signal
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(4), "blue_down") and lp.asked == [4]
    s, lp = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_down", 4)], Lp({4: 95.0}))  # the 10% stop (90) is lower: raised
    assert (s.stop_price, s.stop_basis, s.instruction_type, s.stop_moved_at, s.stop_moved_by) == (95.0, "LP", 10, _ts(4), "blue_down")
    assert lp.asked == [4]


@pytest.mark.parametrize("down, text_type, entry", [("blue_down", 10, "yellow_up"), ("yellow_down", 20, "yellow_up"), ("blue_down", 10, "gray_up")])
def test_a_down_arrow_with_a_2nd_lp_at_or_below_the_stop_is_text_only(down, text_type, entry):
    # stop 90 (10% basis). 2nd LP below (88) or equal (90): no stop move, no stop-age update, basis unchanged.
    for lp_value in (88.0, 90.0):
        s, lp = _run(FLAT, [_ev(entry, 1), _ev(down, 4)], Lp({4: lp_value}))
        assert (s.stop_price, s.stop_basis, s.stop_moved_at) == (pytest.approx(90.0), "10%", _ts(1))
        assert s.stop_moved_by == ("yellow_up_entry" if entry == "yellow_up" else "gray_up_entry")
        assert (s.instruction_type, s.latest_arrow_kind, s.latest_arrow_at) == (text_type, down, _ts(4)) and lp.asked == [4]
        old, _ = _run(FLAT, [_ev(entry, 1), _ev(down, 4)], Lp({4: lp_value}), rules=w.PRE_RAISE_ONLY_RULES)
        assert old.stop_price == lp_value and old.stop_basis == "LP"  # what the previous rule did (cut the stop to the 2nd LP)


def test_a_down_arrow_never_lowers_an_lp_or_entry_basis_stop_either():
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("yellow_down", 5)], Lp({3: 110.0, 5: 105.0}), closes=RALLY_CLOSES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (110.0, "LP", _ts(3), "blue_down")
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("blue_down", 6)], Lp({6: 99.0}), closes=RALLY_CLOSES)  # stop 101 (entry basis)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (101.0, "entry", _ts(4), "gray_down")
    assert s.instruction_type == 10  # the text still follows the arrow


def test_a_higher_2nd_lp_from_a_down_arrow_lifts_an_entry_basis_stop_and_trailing_resumes():
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("yellow_down", 6)], Lp({6: 105.0, 8: 108.0}), closes=RALLY_CLOSES, trail=True)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (108.0, "LP", _ts(8), "trail")
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("yellow_down", 6)], Lp({6: 105.0}), closes=RALLY_CLOSES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (105.0, "LP", "yellow_down")


def test_yellow_down_is_the_2nd_lp_for_a_yellow_entry_and_unchanged_for_a_blue_entry():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("yellow_down", 4)], Lp({4: 95.0}))
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (95.0, "LP", 20)
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


def test_a_gray_down_on_a_breached_row_is_ignored_entirely():
    lows = [100, 100, 100, 100, 100, 85, 100, 100, 100, 100, 100, 100]  # the 10% stop (90) breaks on candle 5, gray down on 7
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 7)], closes=[101.0] * 7 + [95.0] * 5)
    assert (s.status, s.breached_at, s.stop_price, s.stop_basis) == ("breached", _ts(5), pytest.approx(90.0), "10%")
    assert (s.instruction_type, s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == (3, "yellow_up", _ts(1), _ts(1))  # nothing moved
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 7)], closes=[101.0] * 7 + [95.0] * 5, rules=w.LEGACY_RULES)
    assert (s.instruction_type, s.latest_arrow_kind, s.latest_arrow_at) == (30, "gray_down", _ts(7))  # the previous rule moved the text


def test_gray_down_on_a_row_with_no_entry_changes_only_the_text():
    s, lp = _run(FLAT, [_ev("gray_up", 1), _ev("gray_down", 4)], closes=CLOSES_FALLING, rules=w.LEGACY_RULES)  # an entry-less (stored) row
    assert (s.entry_kind, s.stop_price, s.stop_basis, s.instruction_type) == (None, None, "none", 30) and lp.asked == []


def test_a_down_arrow_with_no_2nd_lp_leaves_the_stop_but_updates_the_text():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_down", 4)], Lp())
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (pytest.approx(90.0), "10%", 10)


def test_the_dominant_down_arrow_wins_on_one_candle():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("yellow_down", 4), _ev("blue_down", 4)], Lp({4: 95.0}))
    assert s.instruction_type == 20 and s.latest_arrow_kind == "yellow_down" and s.stop_price == 95.0


def test_a_down_arrow_with_no_row_creates_nothing_and_never_asks_for_the_lp():
    for kind in ("blue_down", "yellow_down", "gray_down"):
        s, lp = _run(FLAT, [_ev(kind, 3)], Lp({3: 50.0}))
        assert s is None and lp.asked == []


def test_a_row_with_no_entry_takes_no_stop_from_a_down_arrow():
    s, lp = _run(FLAT, [_ev("gray_up", 1), _ev("blue_down", 4)], Lp({4: 88.0}), rules=w.LEGACY_RULES)  # an entry-less (stored) row
    assert (s.stop_price, s.instruction_type) == (None, 10) and lp.asked == []


# --- Gray Down is raise-only (2026-10-17) ----------------------------------------------------------------------

RALLY = [100.0] * 4 + [120.0] * 8  # lows: the market is well above the 101 entry from candle 4 on
RALLY_CLOSES = [101.0] * 4 + [121.0] * 8


def test_gray_down_raises_a_ten_percent_stop_to_the_entry_price_on_yellow_and_gray_entries():
    for first, kind in (("yellow_up", "yellow"), ("gray_up", "gray")):
        s, lp = _run(RALLY, [_ev(first, 1), _ev("gray_down", 4)], closes=RALLY_CLOSES)
        assert (s.entry_kind, s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (kind, 101.0, "entry", _ts(4), "gray_down")
        assert (s.instruction_type, s.latest_arrow_kind) == (30, "gray_down") and lp.asked == []


def test_gray_down_does_not_lower_a_stop_already_above_the_entry_price_lp_stop():
    # blue_down at 3 sets an LP stop of 110 (above the 101 entry); the gray_down at 5 would have put it back at 101
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("gray_down", 5)], Lp({3: 110.0}), closes=RALLY_CLOSES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (110.0, "LP", _ts(3), "blue_down")  # no move, no stop-age change
    assert (s.instruction_type, s.latest_arrow_kind, s.latest_arrow_at) == (30, "gray_down", _ts(5))  # the text and the pill still update
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("gray_down", 5)], Lp({3: 110.0}), closes=RALLY_CLOSES, rules=w.PRE_GRAY_RAISE_ONLY_RULES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (101.0, "entry", "gray_down")  # what the previous rule did


def test_gray_down_does_not_lower_a_repeat_yellow_stop_above_the_entry_price():
    lows = [100, 100, 100, 100, 125, 125, 125, 125, 125, 125, 125, 125]
    closes = [101.0] * 4 + [130.0] * 8
    # repeat Yellow at 4: stop = min(2nd LP 118, 0.9 x 125 = 112.5) = 112.5 > the 101 entry; the gray_down at 6 must not lower it
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("yellow_up", 4), _ev("gray_down", 6)], Lp({4: 118.0}), closes=closes)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (pytest.approx(112.5), "10%", _ts(4), "yellow_up_repeat")


def test_gray_down_at_exactly_the_entry_price_stop_changes_nothing():
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("gray_down", 5), _ev("gray_down", 7)], Lp({3: 101.0}), closes=RALLY_CLOSES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (101.0, "LP", "blue_down")  # stop == entry: already not below it


def test_a_second_gray_down_after_a_raise_changes_no_stop_age():
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("gray_down", 6)], closes=RALLY_CLOSES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (101.0, "entry", _ts(4), "gray_down")


def test_gray_down_on_a_blue_entry_takes_no_stop_and_leaves_stop_and_entry_alone():
    # the scripts: "GRAY DOWN on BLUE ENTRY = No Action"; only the instruction text and the latest arrow update
    s, lp = _run(RALLY, [_ev("blue_up", 1), _ev("gray_down", 4)], closes=RALLY_CLOSES)
    assert (s.entry_kind, s.entry_price, s.stop_price, s.stop_basis, s.stop_moved_at) == ("blue", 101.0, None, "none", None)
    assert (s.instruction_type, s.latest_arrow_kind) == (30, "gray_down") and lp.asked == []
    # a blue entry that already holds an LP stop (from a Blue Down) keeps it, above or below the entry
    s, _ = _run(RALLY, [_ev("blue_up", 1), _ev("blue_down", 3), _ev("gray_down", 5)], Lp({3: 95.0}), closes=RALLY_CLOSES)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (95.0, "LP", "blue_down")


def test_gray_down_with_the_entry_at_or_above_the_close_is_still_text_only_and_breached_rows_still_ignore_it():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_down", 4)], closes=CLOSES_FALLING)
    assert (s.stop_price, s.stop_basis) == (pytest.approx(90.0), "10%")
    lows = [100, 100, 100, 85, 100, 100, 100]
    base, _ = _run(lows, [_ev("yellow_up", 1)], closes=[101.0] * 3 + [101.0] * 4)
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 5)], closes=[101.0] * 5 + [130.0] * 2)
    assert s == base and s.status == "breached"


def test_a_gray_down_raise_is_the_only_difference_between_the_current_and_the_pre_raise_only_rules_here():
    lows_events = [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("gray_down", 5)]
    new, _ = _run(RALLY, lows_events, Lp({3: 110.0}), closes=RALLY_CLOSES)
    old, _ = _run(RALLY, lows_events, Lp({3: 110.0}), closes=RALLY_CLOSES, rules=w.PRE_GRAY_RAISE_ONLY_RULES)
    assert {f for f in new.__dataclass_fields__ if getattr(new, f) != getattr(old, f)} == {"stop_price", "stop_basis", "stop_moved_at", "stop_moved_by"}


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
    lows[5] = 94.0  # 94 <= the raised stop 95, but above the 10% stop 90
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("blue_down", 3)], Lp({3: 95.0}))
    assert s.status == "breached" and s.breached_at == _ts(5) and s.stop_price == 95.0  # 94 <= 95, not <= 90


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


@pytest.mark.parametrize("down, text_type", [("yellow_down", 20), ("blue_down", 10), ("gray_down", 30)])
def test_down_arrows_on_a_breached_row_change_nothing_and_ask_for_no_lp(down, text_type):
    lows = [100, 100, 100, 85, 100, 100, 100]
    base, _ = _run(lows, [_ev("yellow_up", 1)])
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev(down, 5)], Lp({5: 70.0}))
    assert s == base and s.status == "breached" and lp.asked == []  # the whole state is unchanged, latest arrow and instruction included
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev(down, 5)], Lp({5: 70.0}), rules=w.LEGACY_RULES)
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.instruction_type) == (down, _ts(5), text_type)  # what the previous rule did


def test_a_down_arrow_on_a_breached_row_keeps_the_sort_key_the_latest_arrow_time():
    lows = [100, 100, 100, 85, 100, 100, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("blue_down", 5), _ev("gray_down", 6)])
    assert (s.latest_arrow_at, s.latest_arrow_kind) == (_ts(1), "yellow_up")


def test_a_down_arrow_on_the_candle_that_breaches_the_row_is_ignored_and_one_after_an_up_restart_applies():
    lows = [100, 100, 100, 85, 100, 100, 100]  # candle 3 breaches the 90 stop in force
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("blue_down", 3)], Lp({3: 70.0}))
    assert (s.status, s.latest_arrow_kind, s.instruction_type) == ("breached", "yellow_up", 3)
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 5), _ev("blue_down", 5)], Lp({5: 70.0}))  # up restarts, then the down applies
    assert (s.entry_kind, s.status, s.latest_arrow_kind, s.stop_basis, s.stop_price) == ("gray", "active", "blue_down", "10%", pytest.approx(90.0))  # 70 is no raise
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 5), _ev("blue_down", 5)], Lp({5: 95.0}))
    assert (s.entry_kind, s.status, s.latest_arrow_kind, s.stop_basis, s.stop_price) == ("gray", "active", "blue_down", "LP", 95.0)


def test_up_arrows_restart_a_breached_row_and_the_new_entry_clears_the_breach():
    lows = [100, 100, 100, 85, 100, 100, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_up", 4)])
    assert (s.status, s.breached_at, s.entry_kind) == ("active", None, "gray")


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


# --- trailing stop (2026-10-16) --------------------------------------------------------------------------------

# A yellow entry on candle 1 (10% stop 90), a second yellow on candle 6 whose 2nd LP 75 is below its 10% stop (99 x 0.9 = 89.1 would be
# 90 at low 100): the row holds an LP stop of 75 from candle 6, with nothing but trailing after it.
TRAIL_EVENTS = [_ev("yellow_up", 1), _ev("yellow_up", 6)]
TRAIL_LOWS = [100.0] * 14


def _trail_run(lp_by_pos, lows=None, events=None, **kw):
    return _run(lows or TRAIL_LOWS, events or TRAIL_EVENTS, Lp({6: 75.0, **lp_by_pos}), trail=True, **kw)


def test_trailing_raises_an_lp_stop_when_a_higher_2nd_lp_appears_on_a_candle_with_no_arrow():
    log = []
    s, _ = _trail_run({8: 80.0, 10: 85.0}, log=log)
    assert (s.stop_price, s.stop_basis) == (85.0, "LP")
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(10), "trail")
    assert log == [(_ts(8), 75.0, 80.0), (_ts(10), 80.0, 85.0)]
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at, s.instruction_type) == ("yellow_up", _ts(6), _ts(6), 3)  # the arrow fields do not move


def test_trailing_never_lowers_a_stop():
    s, _ = _trail_run({8: 70.0, 9: None, 10: 75.0})
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (75.0, "LP", _ts(6), "yellow_up_repeat")


def test_ten_percent_and_entry_stops_never_trail_and_never_ask_for_the_lp():
    everywhere_high = Lp({i: 500.0 for i in range(14)})
    s, _ = w.advance(None, _candles(TRAIL_LOWS), [_ev("yellow_up", 1)], [], "any", None, everywhere_high, True), None
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (pytest.approx(90.0), "10%", "yellow_up_entry") and everywhere_high.asked == []
    rally = [100.0] * 4 + [120.0] * 10
    lp = Lp({i: 500.0 for i in range(14)})
    s = w.advance(None, _candles(rally, [101.0] * 4 + [121.0] * 10), [_ev("yellow_up", 1), _ev("gray_down", 4)], [], "any", None, lp, True)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (101.0, "entry", "gray_down") and lp.asked == []


def test_lp_is_asked_each_candle_only_while_the_row_is_active_with_an_lp_stop():
    _, lp = _trail_run({})
    assert sorted(set(lp.asked)) == list(range(6, 14))  # the arrow candle, then every later candle; none before the LP stop exists (the real lookup caches by position)
    lows = TRAIL_LOWS[:9] + [70.0] + TRAIL_LOWS[10:]  # breached on candle 9: no LP after it
    _, lp = _trail_run({}, lows=lows)
    assert sorted(set(lp.asked)) == [6, 7, 8]


def test_a_trailed_stop_is_tested_against_the_stop_before_the_candle_and_hit_on_the_next_candle():
    # Candle 8 trails 75 -> 80 but trades at 78 (above the old 75): no breach on 8. Candle 9 trades at 79 <= 80: breached there.
    lows = list(TRAIL_LOWS)
    lows[8], lows[9] = 78.0, 79.0
    s, _ = _trail_run({8: 80.0}, lows=lows)
    assert (s.status, s.breached_at, s.stop_price) == ("breached", _ts(9), 80.0)
    # Candle 8 trades at 74 (<= the old 75): breached on 8 against the OLD stop, and the breached row does not trail.
    lows = list(TRAIL_LOWS)
    lows[8] = 74.0
    s, _ = _trail_run({8: 80.0, 9: 90.0}, lows=lows)
    assert (s.status, s.breached_at, s.stop_price, s.stop_moved_by) == ("breached", _ts(8), 75.0, "yellow_up_repeat")


def test_stop_moved_at_and_by_are_set_for_each_rule():
    s, _ = _run(FLAT, [_ev("yellow_up", 2)])
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(2), "yellow_up_entry")
    s, _ = _run(FLAT, [_ev("yellow_up", 2), _ev("yellow_up", 6)], Lp({6: 75.0}))
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(6), "yellow_up_repeat")
    s, _ = _run(FLAT, [_ev("blue_up", 1), _ev("blue_down", 4)], Lp({4: 88.0}))
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(4), "blue_down")
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("yellow_down", 4)], Lp({4: 95.0}))
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(4), "yellow_down")
    s, _ = _run([100.0] * 4 + [120.0] * 8, [_ev("yellow_up", 1), _ev("gray_down", 4)], closes=[101.0] * 4 + [121.0] * 8)
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(4), "gray_down")
    s, _ = _trail_run({8: 80.0})
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(8), "trail")


def test_a_fresh_entry_after_a_breach_restamps_the_stop_age():
    lows = [100, 100, 100, 85, 100, 100, 110, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("yellow_up", 6)])
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(6), "yellow_up_entry")


def test_re_setting_the_same_stop_value_is_not_a_move():
    # The repeat yellow leaves an LP stop at 75; a Blue Down whose 2nd LP is also 75 changes the text, not the stop age.
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("yellow_up", 4), _ev("blue_down", 7)], Lp({4: 75.0, 7: 75.0}))
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (75.0, "LP", 10)
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(4), "yellow_up_repeat")
    # A trail onto the same value is no move either (and is not logged).
    log = []
    s, _ = _trail_run({8: 75.0}, log=log)
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(6), "yellow_up_repeat") and log == []


def test_a_stop_that_becomes_none_clears_the_stop_age():
    lows = [100, 100, 100, 85, 100, 100]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("blue_up", 4)])  # a Blue Up on a BREACHED row: a new blue entry, no stop
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (None, "none", None, None)
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_up", 4)], rules=w.PRE_RAISE_ONLY_RULES)  # the previous rules: a Blue Up in a trade did the same
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (None, "none", None, None)
    # A row that never had a stop has none either.
    s, _ = _run(FLAT, [_ev("blue_up", 1)])
    assert (s.stop_moved_at, s.stop_moved_by) == (None, None)
    s, _ = _run(FLAT, [_ev("gray_up", 1)], rules=w.LEGACY_RULES)
    assert (s.stop_moved_at, s.stop_moved_by) == (None, None)
    s, _ = _run(FLAT, [_ev("gray_up", 1)])  # a gray entry has a stop, stamped at the entry
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(1), "gray_up_entry")


def test_a_down_arrow_that_leaves_the_stop_alone_leaves_the_stop_age_alone():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_down", 4)], Lp())  # no 2nd LP
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(1), "yellow_up_entry")


def test_reading_in_two_steps_equals_reading_once_with_trailing_on():
    lows = [100, 100, 80, 100, 100, 100, 90, 100, 85, 100, 100, 100, 100, 100]
    events = [_ev("yellow_up", 2), _ev("yellow_up", 6), _ev("blue_down", 7), _ev("gray_down", 11)]
    lp_by_pos = {6: 75.0, 7: 78.0, 8: 79.0, 9: 77.0, 10: 82.0, 12: 84.0}
    once, _ = _run(lows, events, Lp(lp_by_pos), trail=True)
    for cut in range(1, 13):
        first, _ = _run(lows[: cut + 1], [e for e in events if e.fired_at <= _ts(cut)], Lp(lp_by_pos), trail=True)
        second, _ = _run(lows, events, Lp(lp_by_pos), trail=True, state=first, after=_ts(cut))
        assert second == once, cut


def test_trail_false_replays_the_old_rules():
    s, lp = _run(TRAIL_LOWS, TRAIL_EVENTS, Lp({6: 75.0, 8: 80.0}), trail=False)
    assert (s.stop_price, s.stop_moved_by) == (75.0, "yellow_up_repeat") and lp.asked == [6]


# --- Blue Up is not an action while a trade is open; the armed repeat Yellow is the only lowering rule (2026-10-17) ------------

def _same_trade(a, b):
    return all(getattr(a, f) == getattr(b, f) for f in (
        "entry_kind", "entry_at", "entry_price", "stop_price", "stop_basis", "stop_moved_at", "stop_moved_by", "status", "breached_at"))


@pytest.mark.parametrize("first", ["yellow_up", "blue_up", "gray_up"])
def test_a_blue_up_on_an_active_row_changes_nothing_about_the_trade(first):
    before, _ = _run(FLAT, [_ev(first, 1)])
    s, lp = _run(FLAT, [_ev(first, 1), _ev("blue_up", 4)])
    assert _same_trade(s, before) and s.status == "active"
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("blue_up", _ts(4), _ts(4))
    assert s.instruction_type == 5 and s.instruction_text == "BLUE UP - no change to an open trade"
    assert lp.asked == []
    old, _ = _run(FLAT, [_ev(first, 1), _ev("blue_up", 4)], rules=w.PRE_RAISE_ONLY_RULES)
    assert (old.instruction_type, old.instruction_text) == (2, "BLUE UP - Use appropriate stop.")  # the previous text


def test_the_in_trade_blue_up_text_is_the_same_for_a_profiled_ticker():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_up", 4)], profile="qqq")
    assert s.instruction_text == "BLUE UP - no change to an open trade"


def test_a_blue_up_on_an_active_row_with_a_trailing_lp_stop_keeps_the_stop_and_the_trail():
    s, _ = _trail_run({8: 80.0}, events=[*TRAIL_EVENTS, _ev("blue_up", 9)])
    assert (s.entry_kind, s.entry_at, s.stop_price, s.stop_basis) == ("yellow", _ts(1), 80.0, "LP")
    assert (s.stop_moved_at, s.stop_moved_by) == (_ts(8), "trail")


def test_after_an_in_trade_blue_up_the_next_yellow_is_no_action_and_the_second_one_acts():
    lows = [100.0] * 14
    events = [_ev("yellow_up", 1), _ev("blue_up", 3), _ev("yellow_up", 5), _ev("yellow_up", 8)]
    lp = Lp({5: 70.0, 8: 60.0})
    # the arrow replay marks candle 5 as the first Yellow after the Blue (the counter reset on the in-trade Blue)
    s, lp = _run(lows, events[:3], lp, first_yellow=[5])
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.instruction_type) == (pytest.approx(90.0), "10%", "yellow_up_entry", 4)  # the pill is Yellow Up, so is the text
    assert (s.latest_arrow_kind, s.last_signal_at) == ("yellow_up", _ts(5)) and lp.asked == []
    s, lp = _run(lows, events, Lp({5: 70.0, 8: 60.0}), first_yellow=[5])  # the second Yellow after the Blue is armed: min(2nd LP 60, 90) = 60
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by, s.instruction_type) == (60.0, "LP", _ts(8), "yellow_up_repeat", 3)
    assert (s.entry_kind, s.entry_at) == ("yellow", _ts(1))


def test_a_blue_up_on_a_breached_row_or_no_row_is_a_new_blue_entry_with_no_stop():
    lows = [100, 100, 100, 85, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("blue_up", 4)])
    assert (s.status, s.breached_at, s.entry_kind, s.entry_at, s.entry_price, s.stop_price, s.stop_basis) == ("active", None, "blue", _ts(4), 101.0, None, "none")
    assert (s.instruction_type, s.instruction_text) == (2, "BLUE UP - Use appropriate stop.") and lp.asked == []
    s, _ = _run(FLAT, [_ev("blue_up", 2)])
    assert (s.entry_kind, s.entry_at, s.stop_price, s.instruction_type) == ("blue", _ts(2), None, 2)


def test_a_blue_up_and_a_blue_down_on_one_candle_apply_in_order_the_blue_does_nothing_the_down_raises():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_up", 4), _ev("blue_down", 4)], Lp({4: 95.0}))
    assert (s.entry_kind, s.entry_at, s.stop_price, s.stop_basis, s.instruction_type, s.latest_arrow_kind) == ("yellow", _ts(1), 95.0, "LP", 10, "blue_down")


def test_a_blue_entry_with_no_stop_takes_the_2nd_lp_from_a_blue_down_wherever_it_is():
    s, lp = _run(FLAT, [_ev("blue_up", 1), _ev("blue_down", 4)], Lp({4: 95.0}))
    assert (s.entry_kind, s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == ("blue", 95.0, "LP", _ts(4), "blue_down") and lp.asked == [4]
    s, _ = _run(FLAT, [_ev("blue_up", 1), _ev("blue_down", 4)], Lp())  # no 2nd LP: still no stop
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 10)


def test_a_yellow_down_on_a_blue_entry_is_no_action_even_with_a_2nd_lp():
    s, lp = _run(FLAT, [_ev("blue_up", 1), _ev("yellow_down", 4)], Lp({4: 95.0}))
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 20) and lp.asked == []


def test_only_an_armed_repeat_yellow_lowers_a_stop_and_a_later_gray_down_lifts_it_back_to_the_entry():
    # entry 100 (candle 1 close); a Gray Down at 2 (close 110) puts the stop at 100 (entry basis)
    lows = [100.0] * 3 + [108.0] * 7
    closes = [100.0, 100.0, 110.0] + [110.0] * 3 + [112.0] * 4
    s, lp = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 2)], closes=closes)
    assert (s.entry_price, s.stop_price, s.stop_basis) == (100.0, 100.0, "entry")
    # the armed repeat Yellow at 4 (low 108, 2nd LP 104): min(104, 97.2) = 97.2 -- below the entry, basis 10%
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 2), _ev("yellow_up", 4)], Lp({4: 104.0}), closes=closes, trail=True)
    assert (s.entry_price, s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (100.0, pytest.approx(97.2), "10%", _ts(4), "yellow_up_repeat")
    # a 10% stop never trails, and a later Gray Down closing above the entry lifts the stop back to 100
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 2), _ev("yellow_up", 4), _ev("gray_down", 6)], Lp({4: 104.0}), closes=closes, trail=True)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (100.0, "entry", _ts(6), "gray_down")


def test_a_breach_and_a_gray_down_on_one_candle_breach_first_and_the_gray_down_is_ignored():
    # entry 100, stop 100 (entry basis); candle 4 trades 99.5 (<= 100) and closes 118 with a Gray Down
    lows = [100.0, 100.0, 100.0, 105.0, 99.5, 120.0]
    closes = [100.0, 100.0, 110.0, 110.0, 118.0, 120.0]
    s, _ = _run(lows, [_ev("yellow_up", 1), _ev("gray_down", 2), _ev("gray_down", 4)], closes=closes)
    assert (s.status, s.breached_at, s.stop_price, s.stop_basis) == ("breached", _ts(4), 100.0, "entry")
    assert (s.latest_arrow_at, s.latest_arrow_kind, s.instruction_type) == (_ts(2), "gray_down", 30)  # the second Gray Down changed nothing, not even the pill


# --- the instruction text follows the pill (2026-10-17) ----------------------------------------------------------------

# pill -> the instruction types it may carry: Blue Up is 2 (new entry) or 5 (in an open trade), Yellow Up is 3 or 4 (first Yellow after a Blue), the rest one each
PILL_TYPES = {"blue_up": {2, 5}, "yellow_up": {3, 4}, "gray_up": {1}, "blue_down": {10}, "yellow_down": {20}, "gray_down": {30}}
RISE = [100.0] * 4 + [120.0] * 12
RISE_CLOSES = [101.0] * 4 + [121.0] * 12


def _situations():
    """(name, lows, closes, events, lp, first_yellow): every arrow type on each kind of row, active and breached, restarts, and first Yellows."""
    out = []
    low_breach = [100, 100, 100, 85, 100, 100, 100, 100, 100, 100]
    for entry in ("yellow_up", "blue_up", "gray_up"):
        for arrow in PILL_TYPES:
            out.append((f"{arrow} on active {entry}", RISE, RISE_CLOSES, [_ev(entry, 1), _ev(arrow, 6)], {6: 105.0}, ()))
            out.append((f"{arrow} on breached {entry}", low_breach, None, [_ev(entry, 1), _ev(arrow, 6)], {6: 95.0}, ()))
            out.append((f"{arrow} on the breaching candle of {entry}", low_breach, None, [_ev(entry, 1), _ev(arrow, 3)], {3: 95.0}, ()))
            out.append((f"{arrow} then a down arrow, same candle, on {entry}", RISE, RISE_CLOSES, [_ev(entry, 1), _ev(arrow, 6), _ev("blue_down", 6)], {6: 105.0}, ()))
    out.append(("first Yellow after a Blue entry", RISE, RISE_CLOSES, [_ev("blue_up", 1), _ev("yellow_up", 6)], {6: 105.0}, (6,)))
    out.append(("first Yellow after an in-trade Blue Up on a yellow entry", RISE, RISE_CLOSES, [_ev("yellow_up", 1), _ev("blue_up", 4), _ev("yellow_up", 6)], {6: 105.0}, (6,)))
    out.append(("first Yellow with no row", RISE, RISE_CLOSES, [_ev("yellow_up", 6)], {}, (6,)))
    out.append(("second Yellow after a Blue", RISE, RISE_CLOSES, [_ev("blue_up", 1), _ev("yellow_up", 5), _ev("yellow_up", 8)], {8: 105.0}, (5,)))
    for arrow in PILL_TYPES:
        out.append((f"{arrow} with no row", RISE, RISE_CLOSES, [_ev(arrow, 6)], {6: 105.0}, ()))
    return out


@pytest.mark.parametrize("name, lows, closes, events, lp, first", _situations(), ids=[x[0] for x in _situations()])
def test_the_instruction_type_is_always_one_the_arrow_in_the_pill_can_carry(name, lows, closes, events, lp, first):
    s, _ = _run(lows, events, Lp(lp), closes=closes, first_yellow=first)
    if s is None:
        return  # a down arrow with no row creates nothing
    assert s.instruction_type in PILL_TYPES[s.latest_arrow_kind], (name, s.latest_arrow_kind, s.instruction_type)


def test_the_invariant_has_teeth_the_previous_rules_break_it():
    broken = [x for x in _situations() if (lambda s: s is not None and s.instruction_type not in PILL_TYPES[s.latest_arrow_kind])(
        _run(x[1], x[3], Lp(x[4]), closes=x[2], first_yellow=x[5], rules=w.PRE_RAISE_ONLY_RULES)[0])]
    assert broken  # first Yellow after a Blue and Gray Up on an open trade
    assert all(("first Yellow" in x[0] or "gray_up" in x[0]) for x in broken)


def test_the_exact_texts_for_the_two_known_mismatches_and_the_gray_entry_row():
    # (a) BKNG / DASH: an in-trade Blue Up, then the first Yellow after the Blue
    s, _ = _run(RISE, [_ev("yellow_up", 1), _ev("blue_up", 4), _ev("yellow_up", 6)], Lp({6: 105.0}), closes=RISE_CLOSES, first_yellow=(6,))
    assert (s.latest_arrow_kind, s.instruction_type, s.instruction_text) == ("yellow_up", 4, "FIRST YELLOW UP ARROW AFTER BLUE ENTRY - NO ACTION")
    s, _ = _run(RISE, [_ev("yellow_up", 1), _ev("blue_up", 4), _ev("yellow_up", 6)], Lp({6: 105.0}), closes=RISE_CLOSES, first_yellow=(6,), profile="qqq")
    assert s.instruction_text == "FIRST YELLOW UP AFTER BLUE = NO ACTION"
    # (b) a Gray Up on an open trade: pill, text and dates move; entry and stop do not
    s, _ = _run(RISE, [_ev("yellow_up", 1), _ev("gray_up", 6)], closes=RISE_CLOSES)
    assert (s.latest_arrow_kind, s.instruction_type, s.instruction_text) == ("gray_up", 1, "GRAY UP - NO ACTION. Stopped out twice.")
    assert (s.entry_kind, s.entry_price, s.stop_price, s.stop_basis) == ("yellow", 101.0, pytest.approx(90.0), "10%")
    # a gray-entry row (the trade a Gray Up opened) carries the same text
    s, _ = _run(RISE, [_ev("gray_up", 1)], closes=RISE_CLOSES)
    assert (s.entry_kind, s.instruction_type, s.instruction_text) == ("gray", 1, "GRAY UP - NO ACTION. Stopped out twice.")


def test_a_breached_row_freezes_the_pill_and_the_text_together():
    lows = [100, 100, 100, 85, 100, 100, 100, 100]
    base, _ = _run(lows, [_ev("yellow_up", 1)])
    for down in ("blue_down", "yellow_down", "gray_down"):
        s, _ = _run(lows, [_ev("yellow_up", 1), _ev(down, 6)], Lp({6: 95.0}))
        assert s == base and (s.latest_arrow_kind, s.instruction_type) == ("yellow_up", 3)
