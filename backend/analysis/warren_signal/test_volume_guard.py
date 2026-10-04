"""The candle-level volume guard (volume_guard.py): per-day ratio of summed 2h-candle volume to EOD volume,
fail-closed, NaN through compute_blue, and non-profiled tickers untouched."""

import numpy as np
import pandas as pd
import pytest

from analysis.warren_signal.indicators import compute_blue
from analysis.warren_signal.profiles import QQQ, SPY, TECL, TQQQ
from analysis.warren_signal.state_machine import replay
from analysis.warren_signal.test_profiles import _frame
from analysis.warren_signal.types import ANY_TICKER
from analysis.warren_signal.volume_guard import DAILY_VOLUME_RATIO_LIMIT, guard_candle_volume, guard_for_profile

NY = "America/New_York"


def _day(date: str, vols: list[float], starts=("09:30", "11:30", "13:30", "15:30"), tz=True) -> pd.DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp(f"{date} {s}") for s in starts[: len(vols)]])
    if tz:
        idx = idx.tz_localize(NY)
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": vols}, index=idx)


def _eod(**by_date) -> pd.Series:
    return pd.Series({pd.Timestamp(k.replace("_", "-")): v for k, v in by_date.items()})


def _nan_days(out: pd.DataFrame) -> set[str]:
    nan = out["volume"].isna()
    return {d for d, g in nan.groupby(out.index.strftime("%Y-%m-%d")) if g.all()}


def test_limit_is_a_named_constant_of_1_5():
    assert DAILY_VOLUME_RATIO_LIMIT == 1.5


def test_ratio_just_under_exactly_at_and_just_over_the_limit():
    candles = pd.concat([_day("2026-01-05", [37.0, 37.0, 37.0, 37.0]), _day("2026-01-06", [37.5] * 4), _day("2026-01-07", [37.6] * 4)])
    # sums 148, 150, 150.4 against an EOD of 100
    out = guard_candle_volume(candles, _eod(**{"2026_01_05": 100.0, "2026_01_06": 100.0, "2026_01_07": 100.0}))
    assert _nan_days(out) == {"2026-01-07"}  # 1.48 and exactly 1.50 kept; 1.504 flagged
    assert out.loc["2026-01-06"]["volume"].tolist() == [37.5] * 4


def test_a_flagged_day_blanks_all_of_its_candles_and_only_its_own():
    candles = pd.concat([_day("2026-01-05", [10.0, 10.0, 10.0, 10.0]), _day("2026-01-06", [100.0, 5.0, 5.0, 5.0])])
    out = guard_candle_volume(candles, _eod(**{"2026_01_05": 40.0, "2026_01_06": 40.0}))
    assert out.loc["2026-01-05"]["volume"].tolist() == [10.0] * 4
    assert out.loc["2026-01-06"]["volume"].isna().all()  # ratio 2.9: the whole day, not just the big candle


def test_missing_eod_day_fails_closed():
    candles = pd.concat([_day("2026-01-05", [10.0] * 4), _day("2026-01-06", [10.0] * 4)])
    out = guard_candle_volume(candles, _eod(**{"2026_01_05": 40.0}))  # no 2026-01-06 (e.g. the current session)
    assert _nan_days(out) == {"2026-01-06"}


@pytest.mark.parametrize("bad", [0.0, np.nan, -5.0])
def test_zero_nan_or_negative_eod_fails_closed(bad):
    candles = _day("2026-01-05", [10.0] * 4)
    assert _nan_days(guard_candle_volume(candles, _eod(**{"2026_01_05": bad}))) == {"2026-01-05"}


@pytest.mark.parametrize("none", [None, pd.Series(dtype=float)])
def test_no_daily_volume_at_all_blanks_every_day(none):
    candles = pd.concat([_day("2026-01-05", [10.0] * 4), _day("2026-01-06", [10.0] * 4)])
    assert _nan_days(guard_candle_volume(candles, none)) == {"2026-01-05", "2026-01-06"}


def test_half_day_session_uses_its_own_two_candles_against_its_own_eod():
    half = _day("2025-11-28", [3.0, 3.0], starts=("09:30", "11:30"))  # 1:00pm close: two windows
    assert guard_candle_volume(half, _eod(**{"2025_11_28": 8.0}))["volume"].tolist() == [3.0, 3.0]  # 6/8 = 0.75
    assert guard_candle_volume(half, _eod(**{"2025_11_28": 3.0}))["volume"].isna().all()  # 6/3 = 2.0
    assert guard_candle_volume(half, _eod(**{"2025_11_28": 4.0}))["volume"].tolist() == [3.0, 3.0]  # 6/4 = exactly 1.5


def test_day_with_partial_candles_is_judged_on_the_candles_present():
    partial = _day("2026-01-05", [10.0, 10.0], starts=("09:30", "13:30"))  # two of four candles, one window missing
    assert guard_candle_volume(partial, _eod(**{"2026_01_05": 100.0}))["volume"].tolist() == [10.0, 10.0]  # 0.2: low side, not flagged
    assert guard_candle_volume(partial, _eod(**{"2026_01_05": 10.0}))["volume"].isna().all()  # 2.0: flagged even partial
    # a day whose candles are already NaN sums to 0 and stays NaN
    nan_day = _day("2026-01-05", [np.nan] * 4)
    assert guard_candle_volume(nan_day, _eod(**{"2026_01_05": 10.0}))["volume"].isna().all()


def test_naive_and_tz_aware_candle_indexes_give_the_same_answer():
    for tz in (True, False):
        candles = pd.concat([_day("2026-01-05", [10.0] * 4, tz=tz), _day("2026-01-06", [100.0] * 4, tz=tz)])
        out = guard_candle_volume(candles, _eod(**{"2026_01_05": 40.0, "2026_01_06": 40.0}))
        assert _nan_days(out) == {"2026-01-06"}, tz


def test_daily_volume_index_may_be_tz_aware_or_unnormalised():
    candles = _day("2026-01-05", [10.0] * 4)
    for idx in (pd.DatetimeIndex(["2026-01-05 16:00"]), pd.DatetimeIndex(["2026-01-05"]).tz_localize(NY)):
        assert guard_candle_volume(candles, pd.Series([40.0], index=idx))["volume"].tolist() == [10.0] * 4


def test_the_input_frame_is_never_modified():
    candles = pd.concat([_day("2026-01-05", [10.0] * 4), _day("2026-01-06", [100.0] * 4)])
    before = candles.copy()
    guard_candle_volume(candles, _eod(**{"2026_01_05": 40.0, "2026_01_06": 40.0}))
    pd.testing.assert_frame_equal(candles, before)


def test_frame_without_a_volume_column_or_empty_is_returned_as_is():
    no_vol = _day("2026-01-05", [1.0] * 4).drop(columns="volume")
    assert guard_candle_volume(no_vol, None) is no_vol
    empty = _day("2026-01-05", [1.0] * 4).iloc[:0]
    assert guard_candle_volume(empty, None) is empty


# --- NaN volume through compute_blue --------------------------------------------------------------------------

def _blue_with_volume(profile, volume, **v) -> bool:
    candles, rsi, adx, wvf = _frame(**v)
    candles = candles.copy()
    candles.iloc[-1, candles.columns.get_loc("volume")] = volume
    return bool(compute_blue(candles, rsi, adx, wvf, profile).iloc[-1])


@pytest.mark.parametrize("profile,vol_gate", [(SPY, 70_000_001), (QQQ, 70_000_001), (TQQQ, 300_000_001), (TECL, 4_000_001)])
def test_nan_volume_switches_off_every_volume_gated_branch(profile, vol_gate):
    r = profile.rules
    sos2a = dict(adx=29.66, rsi=39.99)
    sos2b = dict(adx=35.0, rsi=r.sos2_rsi_b - 0.01)
    sos1 = dict(rsi1=r.quiet_branches[-1].rsi1_max, adx=r.adx_lo)
    # with real volume each fires; with NaN none does (the QQQ ungated ORs are exercised separately below)
    assert _blue_with_volume(profile, vol_gate, **sos2a) is True
    assert _blue_with_volume(profile, vol_gate, **sos2b) is True
    assert _blue_with_volume(profile, r.quiet_branches[-1].volume_max, **sos1) is True
    for case in (sos2a, sos2b, sos1):
        assert _blue_with_volume(profile, np.nan, **case) is False


@pytest.mark.parametrize("profile", [SPY, QQQ, TQQQ, TECL])
def test_nan_volume_still_lets_the_ungated_branch_c_fire(profile):
    # paraDrop 0.70, pivotLow, WVF 26: branch c holds (on QQQ the WVF >= 17 OR would fire as well)
    assert _blue_with_volume(profile, np.nan, close=70.0, high=100.0, rsi1=25.0, rsi=40.0, wvf=26.0) is True


def test_nan_volume_still_lets_qqqs_ungated_ors_fire():
    assert _blue_with_volume(QQQ, np.nan, rsi1=16.29) is True
    assert _blue_with_volume(QQQ, np.nan, wvf=17.0) is True
    assert _blue_with_volume(QQQ, np.nan, rsi1=16.3) is False  # strict, as before
    for p in (SPY, TQQQ, TECL):
        assert _blue_with_volume(p, np.nan, rsi1=16.29) is False  # only QQQ has them


def test_end_to_end_flagged_day_loses_the_volume_blue_unflagged_day_keeps_it():
    # QQQ SOS2-a on the last candle: volume 80M > 70M, ADX 25 <= 29.66, RSI 35 < 40. The last day is 2026-01-08.
    candles, rsi, adx, wvf = _frame(volume=80_000_000.0, adx=25.0, rsi=35.0)
    assert bool(compute_blue(candles, rsi, adx, wvf, QQQ).iloc[-1]) is True
    day_sum = candles["volume"][candles.index.strftime("%Y-%m-%d") == "2026-01-08"].sum()
    for eod, expect in ((day_sum / 1.2, True), (day_sum / 2.1, False), (day_sum / 1.5, True), (None, False)):
        guarded = guard_candle_volume(candles, None if eod is None else _eod(**{"2026_01_08": eod}))
        assert bool(compute_blue(guarded, rsi, adx, wvf, QQQ).iloc[-1]) is expect, eod


# --- non-profiled tickers --------------------------------------------------------------------------------------

def test_any_ticker_candles_come_back_as_the_same_object_and_replay_is_identical():
    candles = _day("2026-01-05", [1.0e12] * 4)  # absurd volume would flag any day
    assert guard_for_profile(candles, None, ANY_TICKER) is candles
    for p in (SPY, QQQ, TQQQ, TECL):
        assert guard_for_profile(candles, None, p) is not candles
        assert guard_for_profile(candles, None, p)["volume"].isna().all()
    # the ANY-TICKER replay never reads volume, so guarded vs raw input can't differ
    wavy = _frame()[0].assign(volume=np.nan)
    assert replay(wavy, ANY_TICKER) == replay(_frame()[0], ANY_TICKER)
