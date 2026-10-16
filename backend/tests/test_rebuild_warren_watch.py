"""The one-time watch-row correction (pipeline/backfills/rebuild_warren_watch.py): only a row whose sole difference is
last_signal_at is corrected; anything else is reported and left alone."""

from dataclasses import replace
from datetime import datetime

from analysis.warren_signal.watch import WatchState
from pipeline.backfills.rebuild_warren_watch import diff

T = datetime(2026, 9, 16, 9, 30)
STORED = WatchState("any", "gray_up", datetime(2026, 10, 15, 15, 30), 3, "yellow", T, 425.0, 376.254, "10%", "breached",
                    datetime(2026, 10, 13, 9, 30), datetime(2026, 10, 15, 15, 30))


def test_an_identical_replay_has_no_differences():
    assert diff(STORED, replace(STORED)) == {}


def test_a_frozen_last_signal_at_is_the_only_difference():
    assert diff(STORED, replace(STORED, last_signal_at=T)) == {"last_signal_at": (STORED.last_signal_at, T)}


def test_any_other_field_is_reported_too():
    assert set(diff(STORED, replace(STORED, last_signal_at=T, stop_price=300.0))) == {"last_signal_at", "stop_price"}


def test_a_replay_that_builds_no_row_is_a_difference():
    assert set(diff(STORED, None)) == {"<replay>"}
