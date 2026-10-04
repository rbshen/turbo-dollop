"""Per-branch tests of the four per-ticker Blue Up profiles at exact threshold edges. `blue_at` drives
compute_blue directly with hand-set series (RSI[1], RSI, ADX, WVF, volume, close/high for paraDrop), so every
operator (<= vs <, inclusive Between, RSI[1] vs the current bar's RSI) is pinned independently of the real
indicator pipeline. The final bar is the one evaluated; every other bar is neutral."""

import dataclasses

import numpy as np
import pandas as pd
import pytest

from analysis.warren_signal.indicators import compute_blue
from analysis.warren_signal.profiles import QQQ, SPY, TECL, TQQQ
from analysis.warren_signal.state_machine import replay
from analysis.warren_signal.types import WarrenProfile

N = 40  # > the 35-bar paraDrop window
NEUTRAL = dict(rsi1=50.0, rsi=50.0, adx=20.0, wvf=0.0, volume=1_000_000.0, close=100.0, high=100.0)


def _frame(**v):
    """N bars, neutral everywhere, with the LAST bar's values overridden. `rsi1` is the previous bar's RSI (the
    series' second-to-last value), `rsi` the current bar's."""
    d = {**NEUTRAL, **v}
    idx = pd.date_range("2026-01-05 09:30", periods=N, freq="2h", tz="America/New_York")
    rsi = pd.Series(NEUTRAL["rsi"], index=idx)
    rsi.iloc[-2], rsi.iloc[-1] = d["rsi1"], d["rsi"]
    adx = pd.Series(NEUTRAL["adx"], index=idx)
    adx.iloc[-1] = d["adx"]
    wvf = pd.Series(NEUTRAL["wvf"], index=idx)
    wvf.iloc[-1] = d["wvf"]
    candles = pd.DataFrame(
        {"open": NEUTRAL["close"], "high": NEUTRAL["high"], "low": NEUTRAL["close"], "close": NEUTRAL["close"], "volume": NEUTRAL["volume"]},
        index=idx,
    )
    candles.iloc[-1, candles.columns.get_loc("volume")] = d["volume"]
    candles.iloc[-1, candles.columns.get_loc("close")] = d["close"]
    candles.iloc[-1, candles.columns.get_loc("high")] = d["high"]
    return candles, rsi, adx, wvf


def blue_at(profile: WarrenProfile, **v) -> bool:
    candles, rsi, adx, wvf = _frame(**v)
    return bool(compute_blue(candles, rsi, adx, wvf, profile).iloc[-1])


def test_neutral_bar_fires_nothing_for_every_profile():
    for p in (SPY, QQQ, TQQQ, TECL):
        assert blue_at(p) is False, p.name


# --- transcription pins: every number from the .ts files --------------------------------------------------------

def test_profiles_carry_the_thinkscript_numbers():
    s, q, t, c = (p.rules for p in (SPY, QQQ, TQQQ, TECL))
    assert (s.adx_lo, s.adx_hi, s.volume_num, s.sos2_rsi_b) == (43.0, 46.0, 70_000_000, 14.0)
    assert [(b.rsi1_max, b.wvf_min, b.volume_max) for b in s.quiet_branches] == [(18.0, 10.0, 24_000_000), (21.034, None, 24_000_000)]
    assert (q.adx_lo, q.adx_hi, q.volume_num, q.sos2_rsi_b) == (43.0, 46.0, 70_000_000, 16.1)
    assert [(b.rsi1_max, b.wvf_min, b.volume_max) for b in q.quiet_branches] == [(18.0, 10.0, 24_000_000), (18.0, None, 10_000_000)]
    assert (q.ungated_rsi1_lt, q.ungated_wvf_min) == (16.3, 17.0)
    for r, vol in ((t, 300_000_000), (c, 4_000_000)):
        assert (r.adx_lo, r.adx_hi, r.volume_num, r.sos2_rsi_b) == (39.2, 46.0, vol, 16.61)
        assert [(b.rsi1_max, b.wvf_min, b.volume_max) for b in r.quiet_branches] == [(21.0, 13.9, 692_200), (21.034, None, 692_200)]
        assert (r.ungated_rsi1_lt, r.ungated_wvf_min) == (None, None)
    for r in (s, q, t, c):  # the literals shared by all four scripts
        assert (r.sos2_adx_max, r.sos2_rsi_a_max, r.para_drop_max) == (29.66, 40.0, 0.70)
    assert (s.ungated_rsi1_lt, s.ungated_wvf_min) == (None, None)
    # TQQQ and TECL differ in Volume_Num only
    assert dataclasses.replace(t, volume_num=c.volume_num) == c


# --- scanOverSold1 (quiet bar) ---------------------------------------------------------------------------------

# (profile, quiet-branch RSI[1] cutoff that fires with no WVF term, volume cap, ADX_Between lo)
SOS1_B = [(SPY, 21.034, 24_000_000, 43.0), (TQQQ, 21.034, 692_200, 39.2), (TECL, 21.034, 692_200, 39.2)]


@pytest.mark.parametrize("p,rsi1,cap,adx_lo", SOS1_B)
def test_sos1_branch_b_edges(p, rsi1, cap, adx_lo):
    ok = dict(rsi1=rsi1, volume=cap, adx=adx_lo)
    assert blue_at(p, **ok) is True  # all three edges at once: <=, <=, ADX_Between lower edge inclusive
    assert blue_at(p, **{**ok, "rsi1": rsi1 + 0.001}) is False  # RSI[1] <= cutoff, not <
    assert blue_at(p, **{**ok, "volume": cap + 1}) is False  # volume <= cap
    assert blue_at(p, **{**ok, "adx": adx_lo - 0.01}) is False
    assert blue_at(p, **{**ok, "adx": 46.0}) is True  # ADX_Between upper edge inclusive
    assert blue_at(p, **{**ok, "adx": 46.01}) is False


@pytest.mark.parametrize("p", [SPY, TQQQ, TECL])
def test_sos1_reads_rsi_of_the_previous_bar_not_the_current(p):
    r = p.rules
    ok = dict(rsi1=18.0, volume=r.quiet_branches[0].volume_max, adx=r.adx_lo)
    assert blue_at(p, **{**ok, "rsi": 50.0}) is True
    assert blue_at(p, **{**ok, "rsi1": 50.0, "rsi": 18.0}) is False  # only the CURRENT bar is low


def test_sos1_branch_a_wvf_is_inclusive_and_matters_where_branch_b_does_not_cover_it_qqq():
    # QQQ: branch a = RSI[1]<=18, WVF>=10, ADX_Between, vol<=24M; branch b = RSI[1]<=18, vol<=10M, ADX_Between.
    # Volume 24M is above b's 10M cap, so only branch a can fire.
    ok = dict(rsi1=18.0, wvf=10.0, volume=24_000_000, adx=43.0)
    assert blue_at(QQQ, **ok) is True
    assert blue_at(QQQ, **{**ok, "wvf": 9.99}) is False  # WVF >= 10, inclusive
    assert blue_at(QQQ, **{**ok, "volume": 24_000_001}) is False
    assert blue_at(QQQ, **{**ok, "rsi1": 18.01}) is False
    assert blue_at(QQQ, **{**ok, "adx": 42.99}) is False


def test_sos1_branch_b_needs_no_wvf_and_has_the_tighter_volume_cap_qqq():
    ok = dict(rsi1=18.0, wvf=0.0, volume=10_000_000, adx=43.0)
    assert blue_at(QQQ, **ok) is True
    assert blue_at(QQQ, **{**ok, "volume": 10_000_001}) is False  # no WVF to rescue it
    assert blue_at(QQQ, **{**ok, "adx": 46.0}) is True
    assert blue_at(QQQ, **{**ok, "adx": 46.01}) is False


def test_sos1_branch_a_wvf_edge_where_it_is_the_only_branch_nothing_for_nested_profiles():
    # TQQQ/TECL branch a (RSI[1]<=21, WVF>=13.9) is covered by branch b (RSI[1]<=21.034, no WVF): a bar passing a
    # also passes b, and removing branch a changes nothing anywhere (the redundancy the script itself has).
    rng = np.random.default_rng(5)
    for p in (SPY, TQQQ, TECL):
        only_b = dataclasses.replace(p, rules=dataclasses.replace(p.rules, quiet_branches=p.rules.quiet_branches[1:]))
        for _ in range(400):
            v = dict(
                rsi1=float(rng.uniform(5, 30)), rsi=float(rng.uniform(5, 60)), adx=float(rng.uniform(30, 50)),
                wvf=float(rng.uniform(0, 30)), volume=float(rng.choice([1e5, 6.9e5, 6.93e5, 5e6, 2e7, 2.5e7])),
            )
            assert blue_at(p, **v) == blue_at(only_b, **v), (p.name, v)


# --- scanOverSold2 (panic bar) ---------------------------------------------------------------------------------

V = {"spy": 70_000_000, "qqq": 70_000_000, "tqqq": 300_000_000, "tecl": 4_000_000}
X = {"spy": 14.0, "qqq": 16.1, "tqqq": 16.61, "tecl": 16.61}
PROFILES = {"spy": SPY, "qqq": QQQ, "tqqq": TQQQ, "tecl": TECL}


def _without_ungated_ors(p: WarrenProfile) -> WarrenProfile:
    """QQQ minus its two trailing ORs, to exercise the gated branches in isolation (they are tested on their own
    below). A no-op for the other three."""
    return dataclasses.replace(p, rules=dataclasses.replace(p.rules, ungated_rsi1_lt=None, ungated_wvf_min=None))


@pytest.mark.parametrize("name", PROFILES)
def test_sos2_branch_a_edges(name):
    p, v = PROFILES[name], V[name]
    ok = dict(volume=v + 1, adx=29.66, rsi=39.99)
    assert blue_at(p, **ok) is True
    assert blue_at(p, **{**ok, "volume": v}) is False  # volume > Volume_Num, strict
    assert blue_at(p, **{**ok, "adx": 29.67}) is False  # ADX <= 29.66, inclusive
    assert blue_at(p, **{**ok, "rsi": 40.0}) is False  # RSI_Num < 40, strict
    assert blue_at(p, **{**ok, "rsi": 40.0, "rsi1": 39.0}) is False  # still the CURRENT bar's RSI that counts
    assert blue_at(p, **{**ok, "rsi1": 99.0}) is True  # ...and RSI[1] is irrelevant here


@pytest.mark.parametrize("name", PROFILES)
def test_sos2_branch_b_edges(name):
    p, v, x = PROFILES[name], V[name], X[name]
    ok = dict(volume=v + 1, adx=35.0, rsi=x - 0.01)  # adx 35 > 29.66 switches branch a off
    assert blue_at(p, **ok) is True
    assert blue_at(p, **{**ok, "rsi": x}) is False  # RSI_Num < X, strict
    assert blue_at(p, **{**ok, "volume": v}) is False  # volume > Volume_Num, strict
    assert blue_at(p, **{**ok, "rsi": x - 0.01, "rsi1": 99.0}) is True  # current bar's RSI, not RSI[1]


@pytest.mark.parametrize("name", PROFILES)
def test_sos2_branch_c_edges_need_all_three_terms_and_no_volume(name):
    p = _without_ungated_ors(PROFILES[name])  # QQQ's `WVF >= 17` OR would otherwise cover WVF 25-27 outright
    # paraDrop = close / Highest(high, 35): 70/100 = 0.70 exactly. pivotLow: RSI[1]<30, RSI[1]<RSI, RSI<50.
    ok = dict(close=70.0, high=100.0, rsi1=25.0, rsi=40.0, wvf=26.0, volume=1_000_000.0, adx=35.0)
    assert blue_at(p, **ok) is True  # nothing here depends on volume or ADX
    assert blue_at(p, **{**ok, "close": 70.01}) is False  # paraDrop <= .70, inclusive at .70
    assert blue_at(p, **{**ok, "rsi1": 30.0}) is False  # pivotLow needs RSI[1] < 30
    assert blue_at(p, **{**ok, "rsi": 25.0}) is False  # ...and RSI[1] < RSI
    assert blue_at(p, **{**ok, "rsi": 50.0}) is False  # ...and RSI < 50
    assert blue_at(p, **{**ok, "wvf": 25.0}) is True  # WVF_Between inclusive
    assert blue_at(p, **{**ok, "wvf": 27.0}) is True
    assert blue_at(p, **{**ok, "wvf": 24.99}) is False
    assert blue_at(p, **{**ok, "wvf": 27.01}) is False
    assert blue_at(p, **{**ok, "volume": 1.0}) is True  # volume-independent


# --- QQQ's trailing, ungated ORs -----------------------------------------------------------------------------

def test_qqq_ungated_rsi_prev_below_16_3_fires_with_no_volume_or_adx_gate():
    assert blue_at(QQQ, rsi1=16.29, volume=1.0, adx=5.0) is True
    assert blue_at(QQQ, rsi1=16.29, volume=9e9, adx=90.0) is True
    assert blue_at(QQQ, rsi1=16.3) is False  # strict <
    assert blue_at(QQQ, rsi1=16.29, rsi=90.0) is True  # RSI[1], not the current bar


def test_qqq_ungated_wvf_at_least_17_fires_with_no_other_gate():
    assert blue_at(QQQ, wvf=17.0, volume=1.0, adx=5.0, rsi1=80.0, rsi=80.0) is True  # >=, inclusive
    assert blue_at(QQQ, wvf=16.99) is False
    assert blue_at(QQQ, wvf=60.0, rsi1=99.0, rsi=99.0, volume=9e9, adx=90.0) is True


@pytest.mark.parametrize("p", [SPY, TQQQ, TECL])
def test_only_qqq_has_the_ungated_ors(p):
    assert blue_at(p, rsi1=16.29, volume=1.0, adx=5.0) is False
    assert blue_at(p, wvf=60.0) is False


# --- and-before-or precedence pin ----------------------------------------------------------------------------

@pytest.mark.parametrize("name", PROFILES)
def test_a_lone_true_operand_of_an_and_chain_never_fires(name):
    """`A and B and C or D and E or F and G and H`: with `and` binding tighter than `or`, one true operand does
    nothing. (An or-before-and or left-to-right reading would let these through.)"""
    p, v, x = _without_ungated_ors(PROFILES[name]), V[name], X[name]
    r = p.rules
    cap = r.quiet_branches[0].volume_max
    # SOS1: ADX_Between + volume <= cap hold, RSI[1] too high
    assert blue_at(p, rsi1=30.0, adx=r.adx_lo, volume=cap) is False
    # SOS1: RSI[1] low and volume <= cap hold, ADX outside the band
    assert blue_at(p, rsi1=10.0, adx=r.adx_lo - 1, volume=cap) is False
    # SOS1: RSI[1] low and ADX_Between hold, volume over the cap
    assert blue_at(p, rsi1=10.0, adx=r.adx_lo, volume=cap + 1) is False
    # SOS2 a: only the volume term
    assert blue_at(p, volume=v + 1, adx=35.0, rsi=60.0) is False
    # SOS2 a: only the ADX term / only the RSI term
    assert blue_at(p, volume=1.0, adx=20.0, rsi=60.0) is False
    assert blue_at(p, volume=1.0, adx=35.0, rsi=30.0) is False
    # SOS2 b: only the RSI term (volume low), and only the volume term
    assert blue_at(p, volume=v, adx=35.0, rsi=x - 1) is False
    assert blue_at(p, volume=v + 1, adx=35.0, rsi=x + 1, rsi1=60.0) is False
    # SOS2 c: each of its three terms alone
    assert blue_at(p, close=70.0, high=100.0) is False
    assert blue_at(p, rsi1=25.0, rsi=40.0) is False
    assert blue_at(p, wvf=26.0) is False
    # ...and two of three
    assert blue_at(p, close=70.0, high=100.0, wvf=26.0) is False
    assert blue_at(p, close=70.0, high=100.0, rsi1=25.0, rsi=40.0) is False
    assert blue_at(p, rsi1=25.0, rsi=40.0, wvf=26.0) is False


@pytest.mark.parametrize("name", PROFILES)
def test_the_two_sos1_branches_do_not_mix_operands(name):
    """Branch a's WVF term must not leak into branch b and vice versa (QQQ is where the branches differ)."""
    p = _without_ungated_ors(PROFILES[name])
    r = p.rules
    a, b = r.quiet_branches
    if name == "qqq":
        # a's volume (24M) with b's missing WVF: neither branch holds
        assert blue_at(p, rsi1=18.0, wvf=9.99, volume=a.volume_max, adx=43.0) is False
        # b's volume (10M) with no WVF: b holds on its own
        assert blue_at(p, rsi1=18.0, wvf=0.0, volume=b.volume_max, adx=43.0) is True
    else:
        # b needs no WVF
        assert blue_at(p, rsi1=b.rsi1_max, wvf=0.0, volume=b.volume_max, adx=r.adx_lo) is True


def test_qqq_branch_c_is_covered_by_the_ungated_wvf_or():
    # WVF_Between(25, 27) implies WVF >= 17, so on QQQ branch c can never fire on its own -- a property of the script.
    assert blue_at(QQQ, close=70.0, high=100.0, rsi1=25.0, rsi=40.0, wvf=26.0, volume=1.0) is True
    assert blue_at(QQQ, wvf=26.0) is True  # ...even with none of branch c's other terms


# --- through the full replay ---------------------------------------------------------------------------------

def test_replay_with_the_qqq_profile_fires_blue_up_on_the_bar_after_rsi_drops_under_16_3():
    n = 120
    closes = np.concatenate([np.full(40, 100.0), 100.0 - np.arange(1, 41) * 1.5, np.full(n - 80, 40.0) + np.arange(n - 80) * 0.5])
    idx = pd.date_range("2026-01-05 09:30", periods=n, freq="2h", tz="America/New_York")
    candles = pd.DataFrame(
        {"open": closes, "high": closes + 0.5, "low": closes - 0.5, "close": closes, "volume": 1000.0}, index=idx
    )
    from analysis.warren_signal import indicators as wi

    rsi = wi.compute_rsi_wilder(candles["close"])
    first_low = int(np.argmax((rsi.shift(1) < 16.3).to_numpy()))
    assert first_low > 0
    events = [e for e in replay(candles, QQQ).events if e.kind == "blue_up"]
    assert events and events[0].fired_at == idx[first_low].to_pydatetime().replace(tzinfo=None)
