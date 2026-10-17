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
    assert (s.stop_price, s.stop_basis, s.instruction_type) == (None, "none", 2)
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at) == ("yellow_up", _ts(4), _ts(4))
    assert lp.asked == []


def test_gray_up_with_a_row_is_no_action():
    lows = [100, 100, 80, 100, 100, 100, 100]
    s, lp = _run(lows, [_ev("yellow_up", 2), _ev("gray_up", 5)])
    assert (s.stop_price, s.stop_basis, s.instruction_type, s.entry_kind) == (pytest.approx(72.0), "10%", 3, "yellow")
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
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.instruction_type) == (pytest.approx(90.0), "10%", _ts(1), 3)  # stop and instruction unchanged
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


def _gray_row(lows, extra, lp=None, closes=None, trail=False):
    """A gray entry on candle 1, then `extra` events."""
    return _run(lows, [_ev("gray_up", 1), *extra], lp, closes=closes, trail=trail)


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
def test_yellow_down_and_blue_down_on_a_gray_entry_move_the_stop_to_the_2nd_lp(kind, instruction, moved_by):
    s, lp = _gray_row(FLAT, [_ev(kind, 4)], Lp({4: 88.0}))
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.instruction_type, s.entry_kind) == (88.0, "LP", moved_by, instruction, "gray")
    assert lp.asked == [4]


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
    assert (s.latest_arrow_kind, s.latest_arrow_at, s.last_signal_at, s.instruction_type, s.status) == ("blue_up", _ts(4), _ts(4), 2, "active")
    assert lp.asked == []


def test_a_blue_up_on_an_active_yellow_row_still_replaces_the_entry_and_clears_the_stop():
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_up", 4)])
    assert (s.entry_kind, s.entry_at, s.entry_price, s.stop_price, s.stop_basis, s.status) == ("blue", _ts(4), 101.0, None, "none", "active")


def test_the_gray_entry_kind_stays_through_a_breach_free_trade_with_trailing():
    s, lp = _gray_row(FLAT, [_ev("blue_down", 3)], Lp({3: 80.0, 5: 85.0, 7: 84.0}), trail=True)
    assert (s.entry_kind, s.stop_price, s.stop_basis, s.stop_moved_by) == ("gray", 85.0, "LP", "trail")  # an LP stop trails up, never down
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
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("gray_down", 4), _ev("yellow_down", 4), _ev("blue_down", 4)], Lp({4: 88.0}))
    assert s.instruction_type == 20 and s.latest_arrow_kind == "yellow_down" and s.stop_price == 88.0


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
    s, _ = _run(RALLY, [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("gray_down", 5)], Lp({3: 110.0}), closes=RALLY_CLOSES, rules=w.PREVIOUS_RULES)
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


def test_a_gray_down_raise_is_the_only_difference_between_the_current_and_the_previous_rules_here():
    lows_events = [_ev("yellow_up", 1), _ev("blue_down", 3), _ev("gray_down", 5)]
    new, _ = _run(RALLY, lows_events, Lp({3: 110.0}), closes=RALLY_CLOSES)
    old, _ = _run(RALLY, lows_events, Lp({3: 110.0}), closes=RALLY_CLOSES, rules=w.PREVIOUS_RULES)
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
    assert (s.entry_kind, s.status, s.latest_arrow_kind, s.stop_basis, s.stop_price) == ("gray", "active", "blue_down", "LP", 70.0)


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
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("yellow_down", 4)], Lp({4: 88.0}))
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
    s, _ = _run(FLAT, [_ev("yellow_up", 1), _ev("blue_up", 4)])
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
