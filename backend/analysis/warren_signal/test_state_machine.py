from datetime import datetime, timedelta

import pandas as pd
import pytest

from analysis.warren_signal.state_machine import _replay_from_signals, replay


def _timestamps(n: int) -> list[datetime]:
    base = datetime(2026, 1, 5, 9, 30)
    return [base + timedelta(hours=2 * i) for i in range(n)]


def _all_false(n: int) -> list[bool]:
    return [False] * n


def test_gray_suppression_after_two_stop_outs_since_last_blue():
    # Hand-verified 8-bar sequence (see state_machine.py's own module
    # docstring for why this is driven via _replay_from_signals directly
    # rather than reverse-engineered from real RSI/price data):
    #   bar0: 1st yellow trigger (low=100 -> stop=90)
    #   bar1: quiet
    #   bar2: 2nd yellow trigger (low=95 -> stop=85.5, now armed since
    #         yellowCountSinceBlue=2 > 1)
    #   bar3: low=80 breaches 85.5 -> 1st stop (stop_count=1)
    #   bar4: low=80 again -- debounced, no 2nd stop yet (stop_count=1)
    #   bar5: 3rd yellow trigger (low=70 -> stop=63, resets stopLatched)
    #   bar6: low=60 breaches 63 -> 2nd stop (stop_count=2 -> gray-suppressed)
    #   bar7: 4th yellow trigger -- now renders GRAY, not yellow
    n = 8
    scan3 = _all_false(n)
    for i in (0, 2, 5, 7):
        scan3[i] = True
    lows = [100.0, 100.0, 95.0, 80.0, 80.0, 70.0, 60.0, 50.0]
    closes = [x + 5 for x in lows]

    result = _replay_from_signals(
        scan3=scan3,
        scan4=_all_false(n),
        bear1=_all_false(n),
        rsi_overbought=_all_false(n),
        yellow_cond=_all_false(n),
        rsi_vals=[50.0] * n,
        close_vals=closes,
        low_vals=lows,
        timestamps=_timestamps(n),
    )

    kinds_by_bar = {}
    for event in result.events:
        kinds_by_bar.setdefault(event.fired_at, []).append(event.kind)

    ts = _timestamps(n)
    assert kinds_by_bar[ts[0]] == ["yellow_up"]
    assert kinds_by_bar[ts[2]] == ["yellow_up"]
    assert ts[3] not in kinds_by_bar  # a stop-out is not itself an arrow
    assert ts[4] not in kinds_by_bar
    assert kinds_by_bar[ts[5]] == ["yellow_up"]  # still yellow -- only 1 stop so far
    assert ts[6] not in kinds_by_bar  # the 2nd stop-out is not itself an arrow
    assert kinds_by_bar[ts[7]] == ["gray_up"]  # 2 stops since last Blue -> suppressed to gray

    assert result.stop_count == 2
    assert result.gray_suppressed is True
    assert result.live_stop_price == pytest.approx(50.0 * 0.9)


def test_blue_and_yellow_can_co_fire_on_the_same_bar():
    n = 3
    scan3 = [False, True, False]
    scan4 = [False, True, False]  # co-fires with scan3 on bar1

    result = _replay_from_signals(
        scan3=scan3,
        scan4=scan4,
        bear1=_all_false(n),
        rsi_overbought=_all_false(n),
        yellow_cond=_all_false(n),
        rsi_vals=[50.0] * n,
        close_vals=[10.0] * n,
        low_vals=[9.0] * n,
        timestamps=_timestamps(n),
    )

    kinds = sorted(e.kind for e in result.events if e.fired_at == _timestamps(n)[1])
    assert kinds == ["blue_up", "yellow_up"]


def test_sell_arrows_fire_once_per_cycle_until_a_buy_resets_them():
    n = 4
    bear1 = [True, True, False, False]
    # No buy arrows anywhere in this fixture -- seen_blue should latch
    # after bar0 and suppress bar1's otherwise-identical bear1 condition.
    result = _replay_from_signals(
        scan3=_all_false(n),
        scan4=_all_false(n),
        bear1=bear1,
        rsi_overbought=_all_false(n),
        yellow_cond=_all_false(n),
        rsi_vals=[50.0] * n,
        close_vals=[10.0] * n,
        low_vals=[9.0] * n,
        timestamps=_timestamps(n),
    )

    kinds_by_bar = {e.fired_at: e.kind for e in result.events}
    ts = _timestamps(n)
    assert kinds_by_bar[ts[0]] == "blue_down"
    assert ts[1] not in kinds_by_bar  # same condition, but already seen -- gated


def test_a_buy_resets_the_sell_gate_so_the_next_bear1_fires_again():
    n = 4
    bear1 = [True, False, False, True]
    scan3 = [False, True, False, False]  # a buy in between, resetting seen_blue

    result = _replay_from_signals(
        scan3=scan3,
        scan4=_all_false(n),
        bear1=bear1,
        rsi_overbought=_all_false(n),
        yellow_cond=_all_false(n),
        rsi_vals=[50.0] * n,
        close_vals=[10.0] * n,
        low_vals=[9.0] * n,
        timestamps=_timestamps(n),
    )

    kinds_by_bar = {}
    for e in result.events:
        kinds_by_bar.setdefault(e.fired_at, []).append(e.kind)
    ts = _timestamps(n)
    assert "blue_down" in kinds_by_bar[ts[0]]
    assert "yellow_up" in kinds_by_bar[ts[1]]
    assert "blue_down" in kinds_by_bar[ts[3]]  # re-armed by the intervening buy


def test_replay_is_deterministic_and_causal_across_reruns():
    # Replaying a prefix of the series must reproduce identical events to
    # replaying the full series, for every bar within that shared prefix --
    # the whole point of "full nightly replay, discard state" being safe
    # (see state_machine.py's own module docstring).
    n = 8
    scan3 = [False] * n
    for i in (0, 2, 5, 7):
        scan3[i] = True
    lows = [100.0, 100.0, 95.0, 80.0, 80.0, 70.0, 60.0, 50.0]
    closes = [x + 5 for x in lows]
    ts = _timestamps(n)

    full = _replay_from_signals(
        scan3=scan3,
        scan4=_all_false(n),
        bear1=_all_false(n),
        rsi_overbought=_all_false(n),
        yellow_cond=_all_false(n),
        rsi_vals=[50.0] * n,
        close_vals=closes,
        low_vals=lows,
        timestamps=ts,
    )
    prefix_n = 6
    prefix = _replay_from_signals(
        scan3=scan3[:prefix_n],
        scan4=_all_false(prefix_n),
        bear1=_all_false(prefix_n),
        rsi_overbought=_all_false(prefix_n),
        yellow_cond=_all_false(prefix_n),
        rsi_vals=[50.0] * prefix_n,
        close_vals=closes[:prefix_n],
        low_vals=lows[:prefix_n],
        timestamps=ts[:prefix_n],
    )

    full_events_in_prefix_window = [e for e in full.events if e.fired_at < ts[prefix_n]]
    assert full_events_in_prefix_window == prefix.events


def test_replay_raises_on_empty_candles():
    with pytest.raises(ValueError):
        replay(pd.DataFrame(columns=["open", "high", "low", "close"]))


def test_replay_end_to_end_smoke_test_runs_against_real_indicator_pipeline():
    # Not asserting exact arrow correctness (covered by the hand-verified
    # _replay_from_signals tests above and by test_indicators.py) -- just
    # confirms replay() wires the vectorized indicator pipeline into the
    # sequential loop without error, on a long-enough synthetic series for
    # every indicator's warmup (RSI/DMI/ADX(14), WVF(22)) to clear.
    n = 60
    base = 100.0
    closes = [base + (i % 5) - 2 for i in range(n)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    idx = pd.date_range("2026-01-05 09:30", periods=n, freq="2h", tz="America/New_York")
    candles = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)

    result = replay(candles)

    assert result.as_of is not None
    assert isinstance(result.events, list)
    assert result.stop_count >= 0
