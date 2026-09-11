"""Sequential replay of the Warren RSI/ADX/WVF state machine -- unlike
analysis/entry_signal/engine.py::check_buy_signal (a stateless per-bar
condition), this genuinely needs to walk the full candle series bar-by-bar
in order: yellowEntryHeld/stopCount/the gray-suppression latch all carry
state forward across bars. There is no persisted state between runs (see
data/warren_signal_data.py's own docstring) -- replay() is called fresh
against the full available history every nightly run, and every field on
WarrenReplayResult is recomputed from scratch each time. This is safe
because every input this state machine reads (rsiValue[1..3], the current
bar's own low/high/close, and the vectorized RSI/ADX/WVF series feeding
those) only ever looks backward -- a strictly causal system, so replaying
the same history twice reproduces identical events for the shared prefix
(see test_state_machine.py::test_replay_is_deterministic_across_reruns).

The bar-by-bar loop (_replay_from_signals) is split out from indicator
computation (replay) specifically so tests can drive the state machine
with hand-picked boolean arrays directly -- reverse-engineering real
price/RSI series that hit an exact multi-bar sequence (e.g. "two yellow
triggers, then a stop, then a second stop") is unnecessary busywork when
the thing actually worth testing is the sequencing logic itself, not
whether compute_pivot_low_major fires on some contrived price series
(already covered by test_indicators.py)."""

from datetime import datetime

import pandas as pd

from .indicators import compute_dmi_adx, compute_pivot_high, compute_pivot_low_major, compute_rsi_wilder, compute_scan_blue, compute_wvf_buy
from .types import WarrenReplayResult, WarrenSignalEvent

STOP_PERCENT = 10.0
BEAR1_RSI_THRESHOLD = 80.81
YELLOW_SELL_RSI_THRESHOLD = 84.75
YELLOW_SELL_WVF_THRESHOLD = 0.40
YELLOW_SELL_ADX_THRESHOLD = 40.0

UP_KINDS = frozenset({"blue_up", "yellow_up", "gray_up"})


def _replay_from_signals(
    scan3: list[bool],
    scan4: list[bool],
    bear1: list[bool],
    rsi_overbought: list[bool],
    yellow_cond: list[bool],
    rsi_vals: list[float | None],
    close_vals: list[float],
    low_vals: list[float],
    timestamps: list[datetime],
) -> WarrenReplayResult:
    n = len(scan3)
    yellow_entry_held: float | None = None
    bars_since_yellow = 0
    yellow_count_since_blue = 0
    stop_latched_prev = 0
    stop_count = 0
    yellow_is_gray = False
    seen_blue = seen_yellow = seen_gray = 0

    events: list[WarrenSignalEvent] = []

    for i in range(n):
        is_scan3 = bool(scan3[i])
        is_scan4 = bool(scan4[i])
        is_bear1 = bool(bear1[i])
        is_overbought = bool(rsi_overbought[i])
        is_yellow_cond = bool(yellow_cond[i])

        # yellowEntryHeld/barsSinceYellow -- a `var`-style Pine value:
        # only ever overwritten on a scanOverSold3 bar, otherwise persists.
        if is_scan3:
            yellow_entry_held = float(low_vals[i])
            bars_since_yellow = 0
        else:
            bars_since_yellow += 1

        yellow_counter_reset = is_scan4
        stop_counter_reset = is_scan4 or is_bear1

        if yellow_counter_reset:
            yellow_count_since_blue = 0
        elif is_scan3:
            yellow_count_since_blue += 1
        yellow_armed = yellow_count_since_blue > 1

        yellow_stop_price = yellow_entry_held * (1 - STOP_PERCENT / 100) if yellow_entry_held is not None else None

        raw_stop_hit = (
            yellow_armed
            and yellow_stop_price is not None
            and low_vals[i] <= yellow_stop_price
            and bars_since_yellow > 0
        )
        # stopEvent/stopLatched: stopLatched debounces raw_stop_hit so a
        # multi-bar stop breach only counts once -- "previous-bar
        # stopLatched==0" is why stop_latched_prev is read here, BEFORE
        # this bar's own stop_latched (below) overwrites it.
        stop_event = raw_stop_hit and stop_latched_prev == 0
        stop_latched = 0 if is_scan3 else (1 if raw_stop_hit else stop_latched_prev)

        if stop_counter_reset:
            stop_count = 0
        elif stop_event:
            stop_count += 1
        yellow_is_gray = stop_count >= 2

        yellow_up = is_scan3 and not yellow_is_gray
        gray_up = is_scan3 and yellow_is_gray
        blue_up = is_scan4
        any_buy = yellow_up or blue_up

        # Down arrows are gated on the PREVIOUS bar's seen_* latches --
        # read here, before this bar's own update (below) overwrites them,
        # mirroring stop_latched_prev's own same-shaped debounce above.
        blue_down = is_bear1 and seen_blue == 0
        yellow_down = is_yellow_cond and seen_yellow == 0
        gray_down = is_overbought and seen_gray == 0

        if any_buy:
            seen_blue = seen_yellow = seen_gray = 0
        else:
            if is_bear1:
                seen_blue = 1
            if is_yellow_cond:
                seen_yellow = 1
            if is_overbought:
                seen_gray = 1

        fired_at = timestamps[i]
        rsi_i = rsi_vals[i]
        close_i = float(close_vals[i])

        for fired, kind in (
            (blue_up, "blue_up"),
            (yellow_up, "yellow_up"),
            (gray_up, "gray_up"),
            (blue_down, "blue_down"),
            (yellow_down, "yellow_down"),
            (gray_down, "gray_down"),
        ):
            if fired:
                events.append(WarrenSignalEvent(kind=kind, fired_at=fired_at, close=close_i, rsi=rsi_i, stop_price=yellow_stop_price))

        stop_latched_prev = stop_latched

    live_stop_price = yellow_entry_held * (1 - STOP_PERCENT / 100) if yellow_entry_held is not None else None
    return WarrenReplayResult(
        as_of=timestamps[-1],
        events=events,
        gray_suppressed=yellow_is_gray,
        stop_count=stop_count,
        live_stop_price=live_stop_price,
    )


def replay(candles: pd.DataFrame) -> WarrenReplayResult:
    """candles must already be the 2h session candles (see
    analysis/entry_signal/resample.py::build_2h_session_candles, reused
    directly -- this state machine doesn't care how its bars were built,
    only that they're the app's own "2h" convention), with high/low/close
    columns and a datetime index. Computes every indicator vectorized, then
    delegates the sequential part to _replay_from_signals above."""
    if candles.empty:
        raise ValueError("No candles given to replay against")

    close = candles["close"]
    high = candles["high"]
    low = candles["low"]

    rsi = compute_rsi_wilder(close)
    _, _, adx = compute_dmi_adx(high, low, close)
    wvf_buy = compute_wvf_buy(close, low)

    scan3 = compute_pivot_low_major(rsi)
    scan4 = compute_scan_blue(rsi)
    rsi_overbought = compute_pivot_high(rsi)
    bear1 = (rsi.shift(1) >= BEAR1_RSI_THRESHOLD).fillna(False)
    # "the wvf/rsi84.75 condition" gating Yellow Down -- two of anySell's
    # disjuncts grouped together, per the request's own phrasing.
    yellow_cond = ((wvf_buy <= YELLOW_SELL_WVF_THRESHOLD) & rsi_overbought & (adx < YELLOW_SELL_ADX_THRESHOLD)) | (rsi >= YELLOW_SELL_RSI_THRESHOLD)
    yellow_cond = yellow_cond.fillna(False)

    timestamps = [ts.to_pydatetime().replace(tzinfo=None) if isinstance(ts, pd.Timestamp) else ts for ts in candles.index]
    rsi_vals = [float(v) if v == v else None for v in rsi.to_numpy()]  # NaN check without a numpy import here

    return _replay_from_signals(
        scan3=scan3.to_numpy(),
        scan4=scan4.to_numpy(),
        bear1=bear1.to_numpy(),
        rsi_overbought=rsi_overbought.to_numpy(),
        yellow_cond=yellow_cond.to_numpy(),
        rsi_vals=rsi_vals,
        close_vals=close.to_numpy(),
        low_vals=low.to_numpy(),
        timestamps=timestamps,
    )
