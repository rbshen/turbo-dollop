"""The one-time watch-row rebuild (pipeline/backfills/rebuild_warren_watch.py): the field diff, the kinds of change, the old-rules
emulation the mismatch guard relies on, and that the 12-month start is the first seed's as_of minus SEED_MONTHS."""

from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd

from analysis.warren_signal import watch as watch_rules
from analysis.warren_signal.types import WarrenSignalEvent
from data.warren_watch_data import SEED_MONTHS
from pipeline.backfills import rebuild_warren_watch as rb
from pipeline.backfills.rebuild_warren_watch import WatchState, classify, diff

T = datetime(2026, 9, 16, 9, 30)
STORED = WatchState("any", "gray_up", datetime(2026, 10, 15, 15, 30), 3, "yellow", T, 425.0, 376.254, "10%", "breached",
                    datetime(2026, 10, 13, 9, 30), datetime(2026, 10, 15, 15, 30))


def test_an_identical_replay_has_no_differences():
    assert diff(STORED, replace(STORED)) == {}


def test_every_field_is_compared_not_just_last_signal_at():
    assert diff(STORED, replace(STORED, last_signal_at=T)) == {"last_signal_at": (STORED.last_signal_at, T)}
    assert set(diff(STORED, replace(STORED, last_signal_at=T, stop_price=300.0))) == {"last_signal_at", "stop_price"}


def test_a_replay_that_builds_no_row_is_a_difference():
    assert set(diff(STORED, None)) == {"<replay>"}


def test_the_new_replay_start_is_twelve_months_before_the_first_seeds_as_of():
    assert SEED_MONTHS == 12 and rb.REBUILD_START == datetime(2025, 10, 15, 15, 30) and rb.SEED_START == datetime(2026, 7, 15, 15, 30)


def test_classify_names_the_kinds_of_change():
    assert classify({"entry_price": (1, 2), "entry_at": (1, 2)}) == ["entry changed"]
    assert classify({"stop_price": (1, 2), "status": ("breached", "active"), "breached_at": (T, None)}) == ["stop changed", "status breached -> active"]
    assert classify({"instruction_type": (1, 3)}) == ["instruction/latest arrow changed"]
    assert classify({"last_signal_at": (T, T)}) == ["dates only"]


def _candles(closes, lows):
    index = pd.DatetimeIndex([datetime(2026, 1, 5, 9, 30) + timedelta(hours=2 * i) for i in range(len(closes))])
    return pd.DataFrame({"low": lows, "close": closes}, index=index)


def test_the_old_gray_down_rule_is_emulated_for_the_guard_and_restored_afterwards():
    candles = _candles([101.0] * 4 + [95.0] * 4, [100.0] * 8)  # a yellow entry at 101, then a gray down closing at 95 (under the entry)
    events = [WarrenSignalEvent(kind=k, fired_at=candles.index[i], close=0.0, rsi=None, stop_price=None) for k, i in (("yellow_up", 1), ("gray_down", 4))]

    def run():
        return watch_rules.advance(None, candles, events, [], "any", None, lambda pos: None)

    new = run()
    assert (new.stop_price, new.stop_basis) == (90.0, "10%")  # the new rule: entry 101 >= close 95, stop untouched
    with rb.old_gray_down_rule():
        old = run()
    assert (old.stop_price, old.stop_basis, old.status) == (101.0, "entry", "breached")  # the old rule: stop at the entry price
    assert run() == new  # the patch is undone
