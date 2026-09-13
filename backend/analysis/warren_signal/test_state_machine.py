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


def _active_state_candles() -> pd.DataFrame:
    """A real OHLC series (run through the actual RSI/DMI/WVF indicator
    pipeline, not hand-picked booleans) engineered to walk the state
    machine through several distinct active states: a deep crash drives RSI
    through several Blue Up (scanOverSold4) triggers, a partial recovery
    then a second oversold dip produce two Yellow Up (scanOverSold3)
    triggers with no Blue in between -- arming yellowCountSinceBlue on the
    second one -- and a sharp drop right after breaches the resulting
    yellow stop, incrementing stopCount. Verified against the real
    indicator pipeline (not just asserted here): 7 blue_up events, 2
    yellow_up events, and stop_count == 1, gray_suppressed == False."""
    closes = [100.0] * 15  # RSI(14) warmup -- flat, produces no signal
    for _ in range(6):
        closes.append(closes[-1] * 0.90)  # deep crash -> RSI to ~0, several Blue Up triggers
    for _ in range(3):
        closes.append(closes[-1] * 1.05)  # partial recovery -> RSI climbs back above 12, Blue stops firing
    closes.append(closes[-1] * 1.0)
    closes.append(closes[-1] * 1.10)  # jump above 30 -> 1st Yellow Up (yellowCountSinceBlue -> 1)
    for _ in range(4):
        closes.append(closes[-1] * 0.95)  # 2nd oversold dip, stays above the Blue threshold (12)
    closes.append(closes[-1] * 1.12)  # jump above 30 again -> 2nd Yellow Up, now armed (count -> 2)
    closes.append(closes[-1] * 0.80)  # sharp drop -> breaches the armed yellow stop, stop_count -> 1

    n = len(closes)
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    base = datetime(2026, 1, 5, 9, 30)
    idx = pd.DatetimeIndex([base + timedelta(hours=2 * i) for i in range(n)])
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def _quiet_candles() -> pd.DataFrame:
    """A genuinely quiet series -- a small, unchanging oscillation that
    never sends RSI/ADX/WVF anywhere near a threshold (RSI stays in
    ~47-57, well clear of both 30 and 70; ADX stays near 5-6, well clear of
    40). No arrow ever fires and every counter stays at its fresh-start
    value."""
    n = 40
    base_price = 100.0
    closes = [base_price + (i % 4) * 0.3 for i in range(n)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    base = datetime(2026, 1, 5, 9, 30)
    idx = pd.DatetimeIndex([base + timedelta(hours=2 * i) for i in range(n)])
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes}, index=idx)


def test_active_state_fixture_reaches_armed_yellow_and_a_stop_event():
    # Documents the shape of _active_state_candles() itself, independent of
    # the isolation tests below -- if this ever stops holding, the
    # isolation tests downstream are no longer exercising an "active"
    # ticker and would need re-tuning.
    result = replay(_active_state_candles())
    kinds = [e.kind for e in result.events]
    assert kinds == ["blue_up"] * 7 + ["yellow_up", "yellow_up"]
    assert result.stop_count == 1
    assert result.gray_suppressed is False


def test_quiet_fixture_fires_nothing():
    result = replay(_quiet_candles())
    assert result.events == []
    assert result.stop_count == 0
    assert result.gray_suppressed is False
    assert result.live_stop_price is None


def test_replay_has_no_cross_ticker_leakage_active_ticker_then_quiet_ticker():
    # The "isolation" gap flagged in review: replay() must not carry any
    # state (via a shared/global variable, an unreset counter, or anything
    # else) from one ticker's call into the next one. Running the active
    # fixture first -- which pushes stop_count to 1 and arms
    # yellowCountSinceBlue -- must have zero effect on a subsequent call
    # for a completely different (quiet) ticker.
    quiet_in_isolation = replay(_quiet_candles())

    replay(_active_state_candles())
    quiet_after_active = replay(_quiet_candles())

    assert quiet_after_active == quiet_in_isolation
    assert quiet_after_active.events == []
    assert quiet_after_active.stop_count == 0
    assert quiet_after_active.gray_suppressed is False


def test_replay_has_no_cross_ticker_leakage_quiet_ticker_then_active_ticker():
    # The reverse order -- a "boring" ticker run first must not suppress or
    # otherwise alter a subsequent, genuinely active ticker's own result.
    active_in_isolation = replay(_active_state_candles())

    replay(_quiet_candles())
    active_after_quiet = replay(_active_state_candles())

    assert active_after_quiet == active_in_isolation
    assert active_after_quiet.stop_count == 1
    assert len(active_after_quiet.events) == 9


def test_replay_does_not_accumulate_state_across_repeated_calls_for_the_same_ticker():
    # Simulates the same ticker being replayed on two separate nightly
    # runs (see data/warren_signal_data.py -- every run replays from
    # scratch against the full available history, nothing is persisted
    # into the next run's inputs). Calling replay() twice in a row against
    # identical input must produce byte-identical output both times, not
    # an accumulating stop_count/yellowCountSinceBlue/gray_suppressed
    # carried over from the first call.
    candles = _active_state_candles()
    first_run = replay(candles)
    second_run = replay(candles)

    assert second_run == first_run
    assert second_run.stop_count == 1
    assert second_run.gray_suppressed is False


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
