"""The Warren action-text chain (instructions.py): priority, type 4, expiry and the countdown restart."""

import pytest

from analysis.warren_signal import instructions as ins
from analysis.warren_signal.profiles import QQQ
from analysis.warren_signal.test_state_machine import _all_false, _replay_from_signals, _timestamps
from analysis.warren_signal.types import ANY_TICKER

ALL_TYPES = [100, 30, 20, 10, 4, 3, 2, 1]


def _run(n, *, scan3=(), scan4=(), bear1=(), overbought=(), yellow_cond=(), lows=None):
    def flags(idx):
        return [i in idx for i in range(n)]

    lows = lows or [100.0] * n
    result = _replay_from_signals(
        scan3=flags(scan3),
        scan4=flags(scan4),
        bear1=flags(bear1),
        rsi_overbought=flags(overbought),
        yellow_cond=flags(yellow_cond),
        rsi_vals=[50.0] * n,
        close_vals=[x + 5 for x in lows],
        low_vals=lows,
        timestamps=_timestamps(n),
    )
    return result, _timestamps(n)


def _current(n, profile=ANY_TICKER.name, **kw):
    result, times = _run(n, **kw)
    return ins.current_instruction(result, times, profile)


def test_the_profiled_texts_are_exactly_the_decided_strings():
    assert ins.PROFILED_TEXTS == {
        100: "STOP HIT = EXIT OR RESET",
        30: "GRAY DOWN: yellow entry = stop to entry; blue entry = no action",
        20: "YELLOW DOWN: yellow entry = stop to 2nd LP; blue entry = no action",
        10: "BLUE DOWN = stop to 2nd LP",
        4: "FIRST YELLOW UP AFTER BLUE = NO ACTION",
        3: "YELLOW UP: new entry = 10% stop; already in trade = stop to 2nd LP or 10% below candle low, whichever is lower",
        2: "BLUE UP = ENTRY, NO STOP",
        1: "GRAY UP = NO ACTION (stopped out twice); stay out until BLUE UP",
    }


def test_the_generic_texts_are_the_any_ticker_tos_strings_except_type_4():
    assert ins.GENERIC_TEXTS == {
        100: "STOP HIT = EXIT OR RESET",
        30: "GRAY DOWN - Adjust stop accordingly.",
        20: "YELLOW DOWN - Adjust stop accordingly.",
        10: "BLUE DOWN - Adjust stop accordingly.",
        4: "FIRST YELLOW UP ARROW AFTER BLUE ENTRY - NO ACTION",
        3: "YELLOW UP INITIAL ENTRY - Use appropriate stop.",
        2: "BLUE UP - Use appropriate stop.",
        1: "GRAY UP - NO ACTION. Stopped out twice.",
    }
    assert set(ins.PROFILED_TEXTS) == set(ins.GENERIC_TEXTS) == set(ALL_TYPES)


def test_text_set_is_chosen_by_profile_name():
    assert ins.text_for(2, QQQ.name) == ins.PROFILED_TEXTS[2]
    assert ins.text_for(2, ANY_TICKER.name) == ins.GENERIC_TEXTS[2]
    assert ins.text_for(100, QQQ.name) == ins.text_for(100, ANY_TICKER.name)  # stop hit is shared


def test_tones_follow_the_tos_colours():
    assert {t: ins.TYPE_TONE[t] for t in ALL_TYPES} == {100: "red", 30: "gray", 1: "gray", 20: "yellow", 4: "yellow", 3: "yellow", 10: "blue", 2: "blue"}


@pytest.mark.parametrize(
    ("fired", "expected"),
    [
        # Every pair resolves by ToS order: 100, yellow-down 20, blue-down 10, gray-down 30, yellow-up 3/4, blue-up 2, gray-up 1.
        (dict(stop_hit=True, yellow_down=True, blue_down=True, gray_down=True, yellow_up=True, blue_up=True, gray_up=True), 100),
        (dict(yellow_down=True, blue_down=True, gray_down=True, yellow_up=True, blue_up=True), 20),
        (dict(blue_down=True, gray_down=True, yellow_up=True, blue_up=True), 10),
        (dict(gray_down=True, yellow_up=True, blue_up=True), 30),
        (dict(yellow_up=True, blue_up=True, gray_up=True), 3),
        (dict(yellow_up=True, first_yellow_up=True, blue_up=True), 4),  # type 4 takes type 3's slot, not a higher one
        (dict(blue_up=True, gray_up=True), 2),
        (dict(gray_up=True), 1),
        (dict(first_yellow_up=True), None),  # the flag alone, without its arrow, is nothing
        ({}, None),
    ],
)
def test_same_bar_priority(fired, expected):
    flags = dict(stop_hit=False, yellow_down=False, blue_down=False, gray_down=False, yellow_up=False, first_yellow_up=False, blue_up=False, gray_up=False)
    flags.update(fired)
    assert ins.instruction_type_for_bar(**flags) == expected


def test_a_down_arrow_beats_a_same_bar_up_arrow_end_to_end():
    # Bar 5: blue up AND bear1 (blue down) -- the engine fires both arrows; the down arrow's text wins.
    got = _current(6, scan4=(5,), bear1=(5,))
    assert got.type == 10 and got.kind == "blue_down"


def test_no_signal_gives_none():
    assert _current(10) is None


def test_the_latest_signal_wins_and_reports_its_age():
    got = _current(10, scan4=(2,), bear1=(6,))  # blue up, then blue down 3 candles before the end
    assert (got.type, got.kind, got.tone, got.bars_since, got.bars_left) == (10, "blue_down", "blue", 3, 27)
    assert got.time == _timestamps(10)[6]


def test_type_4_is_shown_on_the_first_yellow_arrow_bar_itself():
    got = _current(8, scan4=(1,), scan3=(7,))  # the yellow is the very last candle
    assert (got.type, got.kind, got.bars_since) == (4, "first_yellow_up", 0)
    assert got.text == ins.GENERIC_TEXTS[4] and got.tone == "yellow"


def test_type_4_never_arrives_a_bar_late():
    # ToS would show it from the bar AFTER the arrow; here the arrow bar is the signal and the next bar adds nothing.
    got = _current(9, scan4=(1,), scan3=(7,))
    assert (got.type, got.bars_since) == (4, 1)  # still the arrow bar, one candle older


def test_a_second_yellow_is_type_3_not_4():
    got = _current(12, scan4=(1,), scan3=(5, 10))
    assert (got.type, got.kind) == (3, "yellow_up")


def test_a_yellow_without_a_recent_blue_is_type_3():
    assert _current(30, scan4=(0,), scan3=(25,)).type == 3  # blue 25 bars back: outside the 20-bar window
    assert _current(8, scan3=(7,)).type == 3  # no blue ever


def test_type_4_does_not_overwrite_a_later_down_arrow():
    got = _current(10, scan4=(1,), scan3=(4,), bear1=(8,))
    assert (got.type, got.bars_since) == (10, 1)  # the later blue down is the text, and stays it afterwards
    assert _current(12, scan4=(1,), scan3=(4,), bear1=(8,)).type == 10


def test_a_stop_hit_is_a_signal_with_no_arrow():
    lows = [100.0, 100.0, 95.0, 80.0, 80.0]
    result, times = _run(5, scan3=(0, 2), lows=lows)
    assert [e.kind for e in result.events] == ["yellow_up", "yellow_up"]  # the stop hit has no event
    got = ins.current_instruction(result, times, ANY_TICKER.name)
    assert (got.type, got.kind, got.tone, got.text) == (100, "stop_hit", "red", "STOP HIT = EXIT OR RESET")
    assert got.time == times[3] and got.bars_since == 1  # bar 4 is debounced and adds nothing


def test_a_stop_hit_restarts_the_countdown():
    # Yellows on bars 0 and 2 (armed), stop hit on bar 3. At 34 candles the stop bar has age 30 (still shown) while
    # the last arrow (bar 2) would be age 31 -- so the text is alive only because the stop hit restarted it.
    lows = [100.0, 100.0, 95.0] + [80.0] * 31
    result, times = _run(34, scan3=(0, 2), lows=lows)
    got = ins.current_instruction(result, times)
    assert (got.type, got.bars_since, got.bars_left) == (100, 30, 0)
    result, times = _run(35, scan3=(0, 2), lows=[100.0, 100.0, 95.0] + [80.0] * 32)
    assert ins.current_instruction(result, times) is None  # now the stop bar is age 31 too


@pytest.mark.parametrize(("age", "visible"), [(0, True), (29, True), (30, True), (31, False), (60, False)])
def test_expiry_the_signal_bar_is_age_zero_visible_through_age_30(age, visible):
    got = _current(age + 1, scan4=(0,))
    if visible:
        assert got is not None and got.bars_since == age and got.bars_left == 30 - age
    else:
        assert got is None


def test_a_new_signal_restarts_the_countdown():
    got = _current(40, scan4=(0,), bear1=(25,))  # the blue up (age 39) is long gone; the blue down (age 14) is live
    assert (got.type, got.bars_since, got.bars_left) == (10, 14, 16)


def test_text_follows_the_profile_name():
    assert _current(3, profile=QQQ.name, scan4=(2,)).text == ins.PROFILED_TEXTS[2]
    assert _current(3, profile=ANY_TICKER.name, scan4=(2,)).text == ins.GENERIC_TEXTS[2]


def test_empty_candle_list_gives_none():
    result, _ = _run(3, scan4=(1,))
    assert ins.current_instruction(result, [], ANY_TICKER.name) is None
