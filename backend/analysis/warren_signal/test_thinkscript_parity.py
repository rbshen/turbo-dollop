"""Arrow parity with the ANY-TICKER ThinkScript (~/warren-thinkscripts/rp_RSI_WVF_Any_TickerSTUDY.ts, the source of
truth): a bar-by-bar transcription of the script's state section, written independently of state_machine.py (the
script's CompoundValue defaults, its `[1]` references and its plot conditions, line for line), run over the same
indicator series on random 2h-like walks, must fire exactly the arrows replay() fires. The Warren Signals watch table
acts only on replay()'s arrows, so this pins that the table sees the script's arrows."""

import math

import numpy as np
import pandas as pd
import pytest

from .indicators import compute_dmi_adx, compute_pivot_high, compute_pivot_low_major, compute_rsi_wilder, compute_wvf_buy
from .state_machine import replay


# (drift, volatility, selloffs-and-squeezes): the first is a calm uptrend broken by sharp selloffs and squeezes, so RSI
# visits <12, <30 and >84 repeatedly; the others are choppy downtrends, which stop out yellow entries (Gray Up).
SCENARIOS = [(0.0004, 0.006, True), (-0.001, 0.01, False), (-0.002, 0.006, False)]
CASES = [(scenario, seed) for scenario in range(len(SCENARIOS)) for seed in range(4)]


def _walk(scenario: int, seed: int, n: int = 1200) -> pd.DataFrame:
    drift, vol, shocks = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, vol, n)
    if shocks:
        for start in rng.integers(40, n - 40, 14):
            steps[start : start + 14] += rng.choice([-0.018, 0.02])
    close = 100 * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.003, n)))
    idx = pd.date_range("2025-01-02 09:30", periods=n, freq="2h")
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


def _thinkscript_arrows(df: pd.DataFrame) -> set[tuple[int, str]]:
    close, high, low = df["close"], df["high"], df["low"]
    rsi = compute_rsi_wilder(close).to_numpy()
    _, _, adx_s = compute_dmi_adx(high, low, close)
    adx = adx_s.to_numpy()
    wvf = compute_wvf_buy(close, low).to_numpy()
    lo = low.to_numpy()
    n = len(df)
    nan = math.nan

    def R(i, k=0):
        return rsi[i - k] if i - k >= 0 else nan

    pivot_high = compute_pivot_high(pd.Series(rsi)).to_numpy()  # pivotHigh: same definition as the script's line 18
    pivot_low_major = compute_pivot_low_major(pd.Series(rsi)).to_numpy()

    out: set[tuple[int, str]] = set()
    yellow_entry_held = [nan] * n
    bars_since_yellow = [0] * n
    yellow_count = [0] * n
    stop_latched = [0] * n
    stop_count = [0] * n
    entry_is_gray = [0] * n
    seen_blue = [0] * n
    seen_yellow = [0] * n
    seen_gray = [0] * n
    for i in range(n):
        scan4 = R(i, 1) <= 12  # scanOverSold4
        scan3 = bool(pivot_low_major[i])  # scanOverSold3 = pivotLowMajor
        scan_overbought = bool(pivot_high[i])
        bear1 = R(i, 1) >= 80.81
        if i == 0:
            yellow_entry_held[i], bars_since_yellow[i] = lo[i], 0  # CompoundValue defaults: low, 0
        else:
            yellow_entry_held[i] = lo[i] if scan3 else yellow_entry_held[i - 1]
            bars_since_yellow[i] = 0 if scan3 else bars_since_yellow[i - 1] + 1
        stop_price = yellow_entry_held[i] * (1 - 10.0 / 100)
        if i > 0:
            yellow_count[i] = 0 if scan4 else (yellow_count[i - 1] + 1 if scan3 else yellow_count[i - 1])
        yellow_armed = yellow_count[i] > 1
        raw_stop_hit = yellow_armed and not math.isnan(yellow_entry_held[i]) and lo[i] <= stop_price and bars_since_yellow[i] > 0
        if i > 0:
            stop_latched[i] = 0 if scan3 else (1 if raw_stop_hit else stop_latched[i - 1])
        stop_event = raw_stop_hit and not (stop_latched[i - 1] if i > 0 else 0)
        reset_stops = scan4 or R(i, 1) >= 80.81
        if i > 0:
            stop_count[i] = 0 if reset_stops else (stop_count[i - 1] + 1 if stop_event else stop_count[i - 1])
        yellow_is_gray = stop_count[i] >= 2
        if i > 0:
            entry_is_gray[i] = int(yellow_is_gray) if scan3 else entry_is_gray[i - 1]

        yellow_plot = scan3 and not yellow_is_gray
        gray_plot = scan3 and yellow_is_gray
        any_buy = yellow_plot or scan4
        yellow_sell = (wvf[i] <= 0.40 and scan_overbought and adx[i] < 40) or R(i) >= 84.75
        if i > 0:
            if any_buy:
                seen_blue[i] = seen_yellow[i] = seen_gray[i] = 0
            else:
                seen_blue[i] = 1 if bear1 else seen_blue[i - 1]
                seen_yellow[i] = 1 if yellow_sell else seen_yellow[i - 1]
                seen_gray[i] = 1 if scan_overbought else seen_gray[i - 1]
        if i == 0:
            continue  # the script's [1] references are undefined on the first bar
        if scan4:
            out.add((i, "blue_up"))
        if yellow_plot:
            out.add((i, "yellow_up"))
        if gray_plot:
            out.add((i, "gray_up"))
        if bear1 and not seen_blue[i - 1]:
            out.add((i, "blue_down"))
        if yellow_sell and not seen_yellow[i - 1]:
            out.add((i, "yellow_down"))
        if scan_overbought and not seen_gray[i - 1]:
            out.add((i, "gray_down"))
    return out


@pytest.mark.parametrize(("scenario", "seed"), CASES)
def test_replay_fires_exactly_the_thinkscripts_arrows(scenario, seed):
    df = _walk(scenario, seed)
    result = replay(df)
    position = {ts.to_pydatetime(): i for i, ts in enumerate(df.index)}
    got = {(position[e.fired_at], e.kind) for e in result.events if position[e.fired_at] > 0}
    assert got == _thinkscript_arrows(df)


def test_the_walks_are_rich_enough_to_exercise_every_arrow_kind():
    kinds = set()
    for scenario, seed in CASES:
        kinds |= {k for _, k in _thinkscript_arrows(_walk(scenario, seed))}
    assert kinds == {"blue_up", "yellow_up", "gray_up", "blue_down", "yellow_down", "gray_down"}
