"""The Technical Ideas table's derived instruction texts (watch_text.py, 2026-10-19)."""

from datetime import datetime, timedelta

import pytest

from analysis.warren_signal import instructions as ins
from analysis.warren_signal import watch as w
from analysis.warren_signal import watch_text as wt
from analysis.warren_signal.profiles import QQQ, SPY, TECL, TQQQ
from analysis.warren_signal.types import ANY_TICKER

T = datetime(2026, 10, 15, 13, 30)
EARLIER = T - timedelta(days=3)
LATER = T + timedelta(hours=2)
ANY = ANY_TICKER.name


def text(itype, *, entry_kind="yellow", entry_at=EARLIER, moved_at=None, moved_by=None, profile=ANY, arrow_at=T):
    return wt.watch_instruction_text(profile, itype, arrow_at, entry_kind, entry_at, moved_at, moved_by)


# --- the generic set: every row of the decided table -------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (dict(itype=3, entry_at=T, moved_at=T, moved_by="yellow_up_entry"), "YELLOW UP - New entry. Stop set 10% below the candle low."),
        (dict(itype=3, moved_at=T, moved_by="yellow_up_repeat"), "YELLOW UP (repeat) - Stop raised."),
        (dict(itype=3, moved_at=EARLIER, moved_by="yellow_up_repeat"), "YELLOW UP (repeat) - Stop unchanged, the new level is not higher."),
        (dict(itype=4), "FIRST YELLOW UP AFTER BLUE ENTRY - No action."),
        (dict(itype=2, entry_kind="blue", entry_at=T), "BLUE UP - New entry, no stop."),
        (dict(itype=5), "BLUE UP - No change to the open trade."),
        (dict(itype=1, entry_kind="gray", entry_at=T, moved_at=T, moved_by="gray_up_entry"),
         "GRAY UP - New entry (stopped out twice before, SPECULATIVE). Stop 10% below the candle low."),
        (dict(itype=1), "GRAY UP - No change to the open trade."),
        (dict(itype=10, moved_at=T, moved_by="blue_down"), "BLUE DOWN - Stop raised to the LP support."),
        (dict(itype=10), "BLUE DOWN - Stop unchanged."),
        (dict(itype=20, moved_at=T, moved_by="yellow_down"), "YELLOW DOWN - Stop raised to the LP support."),
        (dict(itype=20), "YELLOW DOWN - Stop unchanged."),
        (dict(itype=20, entry_kind="blue"), "YELLOW DOWN - No action (blue entry)."),
        (dict(itype=30, moved_at=T, moved_by="gray_down"), "GRAY DOWN - Stop raised to entry + 1%."),
        (dict(itype=30), "GRAY DOWN - Stop unchanged."),
        (dict(itype=30, entry_kind="blue"), "GRAY DOWN - No action (blue entry)."),
    ],
)
def test_every_generic_text(kwargs, expected):
    assert text(**kwargs) == expected


def test_gray_up_new_entry_is_labelled_speculative_and_a_gray_entry_is_required():
    assert "SPECULATIVE" in text(1, entry_kind="gray", entry_at=T)
    assert text(1, entry_kind="gray", entry_at=EARLIER) == wt.GRAY_UP_OPEN  # a Gray Up on an old gray entry changes nothing
    assert text(1, entry_kind=None, entry_at=None) == ins.GENERIC_TEXTS[1]  # no entry recorded (legacy row): the chart's text


# --- raised vs unchanged, from stored fields only -----------------------------------------------------------------------

def test_a_no_op_repeat_yellow_reads_unchanged_even_though_the_stop_was_moved_earlier():
    assert text(3, moved_at=EARLIER, moved_by="yellow_up_repeat") == wt.YELLOW_UP_UNCHANGED
    assert text(3, moved_at=None, moved_by=None) == wt.YELLOW_UP_UNCHANGED


def test_a_blue_entry_first_stop_reads_raised_because_the_old_stop_is_not_stored():
    # Limit: first stop and a later raise look identical (both stamp yellow_up_repeat on the arrow's candle); "raised" is true of both.
    assert text(3, entry_kind="blue", moved_at=T, moved_by="yellow_up_repeat") == wt.YELLOW_UP_RAISED
    assert text(3, entry_kind="blue", moved_at=T, moved_by="yellow_up_entry") == wt.YELLOW_UP_RAISED


@pytest.mark.parametrize("itype, wrong_mover", [(3, "trail"), (10, "trail"), (20, "trail"), (30, "trail"), (10, "yellow_down"), (20, "blue_down"), (30, "blue_down"), (3, "gray_down")])
def test_a_trail_or_another_rule_on_the_arrows_candle_does_not_read_as_raised(itype, wrong_mover):
    """stop_moved_at == the arrow's candle, but the mover is not the arrow's own rule: the arrow did not move the stop."""
    for raised in (wt.YELLOW_UP_RAISED, wt.BLUE_DOWN_RAISED, wt.YELLOW_DOWN_RAISED, wt.GRAY_DOWN_RAISED):
        assert text(itype, moved_at=T, moved_by=wrong_mover) != raised


def test_a_trail_after_the_arrow_candle_reads_unchanged_and_so_does_a_trail_on_it():
    assert text(10, moved_at=LATER, moved_by="trail") == wt.BLUE_DOWN_UNCHANGED
    assert text(10, moved_at=T, moved_by="trail") == wt.BLUE_DOWN_UNCHANGED


def test_an_arrow_move_older_than_the_latest_arrow_is_not_raised():
    assert text(10, moved_at=EARLIER, moved_by="blue_down") == wt.BLUE_DOWN_UNCHANGED
    assert text(30, moved_at=EARLIER, moved_by="gray_down") == wt.GRAY_DOWN_UNCHANGED


def test_a_down_arrow_on_a_row_with_no_stop_age_reads_unchanged():
    assert text(20, moved_at=None, moved_by=None) == wt.YELLOW_DOWN_UNCHANGED


# --- the 1% is the rule's constant ---------------------------------------------------------------------------------------

def test_the_gray_down_percentage_is_built_from_the_constant():
    assert wt.GRAY_DOWN_RAISED == f"GRAY DOWN - Stop raised to entry + {w.GRAY_DOWN_ENTRY_BUFFER * 100:g}%."
    assert wt.PROFILED_WATCH_TEXTS[ins.GRAY_DOWN] == f"GRAY DOWN: yellow entry = stop to entry + {w.GRAY_DOWN_ENTRY_BUFFER * 100:g}%; blue entry = no action"
    assert w.GRAY_DOWN_ENTRY_BUFFER == 0.01 and "1%" in wt.GRAY_DOWN_RAISED  # the one place the decided wording is pinned


# --- the profiled set -----------------------------------------------------------------------------------------------------

def test_the_profiled_set_has_exactly_two_corrections_and_the_rest_is_verbatim():
    assert wt.PROFILED_WATCH_TEXTS[30] == "GRAY DOWN: yellow entry = stop to entry + 1%; blue entry = no action"
    assert wt.PROFILED_WATCH_TEXTS[3] == (
        "YELLOW UP: new entry = 10% stop; already in trade = stop to 2nd LP or 10% below candle low, whichever is lower; "
        "the stop is never lowered below the current stop"
    )
    changed = {k for k in ins.PROFILED_TEXTS if wt.PROFILED_WATCH_TEXTS[k] != ins.PROFILED_TEXTS[k]}
    assert changed == {30, 3}
    assert wt.PROFILED_WATCH_TEXTS[20] == "YELLOW DOWN: yellow entry = stop to 2nd LP; blue entry = no action"
    assert wt.PROFILED_WATCH_TEXTS[10] == "BLUE DOWN = stop to 2nd LP"
    assert wt.PROFILED_WATCH_TEXTS[4] == "FIRST YELLOW UP AFTER BLUE = NO ACTION"
    assert wt.PROFILED_WATCH_TEXTS[2] == "BLUE UP = ENTRY, NO STOP"
    assert wt.PROFILED_WATCH_TEXTS[1] == "GRAY UP = NO ACTION (stopped out twice); stay out until BLUE UP"


@pytest.mark.parametrize("profile", [SPY.name, QQQ.name, TQQQ.name, TECL.name])
def test_the_four_profiled_tickers_get_arrow_type_only_text_whatever_the_stop_did(profile):
    for itype in (1, 2, 3, 4, 10, 20, 30):
        a = text(itype, profile=profile, moved_at=T, moved_by="blue_down")
        b = text(itype, profile=profile, moved_at=None, moved_by=None, entry_kind="blue", entry_at=T)
        assert a == b == wt.PROFILED_WATCH_TEXTS[itype]
    assert text(5, profile=profile) == "BLUE UP - no change to an open trade"  # the shared watch-only text, verbatim


def test_the_chart_texts_are_untouched():
    assert ins.PROFILED_TEXTS[30] == "GRAY DOWN: yellow entry = stop to entry; blue entry = no action"
    assert ins.GENERIC_TEXTS[3] == "YELLOW UP INITIAL ENTRY - Use appropriate stop."
    assert ins.text_for(30, QQQ.name) == ins.PROFILED_TEXTS[30]


def test_every_type_the_table_can_hold_gets_a_text_for_both_sets():
    for profile in (ANY, QQQ.name):
        for itype in (1, 2, 3, 4, 5, 10, 20, 30):
            assert text(itype, profile=profile)
