"""The LP gate (2026-10-18, docs/specs/warren-signals-page.md, "Rules at a glance"): the support the Warren watch table's stop may use must sit at least one
daily ATR(14) below the candle close. R1: the 2nd-nearest support if it is eligible, else the first lower kept support that is, else None; the 1st
is never used. One definition serves the repeat Yellow, Yellow Down, Blue Down and the trailing stop. The daily ATR is as of the last completed session
strictly before the candle's date; where it does not exist the gate is off for that use."""

import logging
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import data.warren_watch_data as wwd
import pipeline.backfills.rebuild_warren_watch as rb
import pipeline.nightly_warren_signal_calculation as nightly
from analysis.warren_signal import watch as w
from analysis.warren_signal.indicators import compute_atr_wilder
from analysis.warren_signal.types import WarrenSignalEvent
from data.warren_watch_data import WatchUpdate, daily_atr_for_candles

T0 = datetime(2026, 1, 5, 9, 30)


def ts(i: int) -> datetime:
    return T0 + timedelta(hours=2 * i)


def ev(kind: str, i: int) -> WarrenSignalEvent:
    return WarrenSignalEvent(kind=kind, fired_at=ts(i), close=0.0, rsi=None, stop_price=None)


def candles(lows, closes=None) -> pd.DataFrame:
    closes = closes or [x + 1.0 for x in lows]
    return pd.DataFrame({"low": lows, "close": closes}, index=pd.DatetimeIndex([ts(i) for i in range(len(lows))]))


@pytest.fixture
def make_lookup(monkeypatch):
    """A real SecondSupportLookup whose LP engine is stubbed: `supports` = {candle position: (nearest, 2nd, 3rd)}; `atr` = one value for all
    candles (or a list)."""

    def build(c, supports, atr):
        def fake(cs, settings):
            return SimpleNamespace(support=[SimpleNamespace(price=p) for p in supports.get(len(cs) - 1, ())])

        monkeypatch.setattr(wwd, "compute_liquidity_zones_2h", fake)
        arr = None if atr is None else (np.full(len(c), atr, dtype=float) if np.isscalar(atr) else np.array(atr, dtype=float))
        return wwd.SecondSupportLookup(c, None, arr)

    return build


# ---- pick_support: the selection ----------------------------------------------------------------------------------------------------

def test_the_2nd_lp_is_used_when_it_is_eligible():
    pick = w.pick_support((99.0, 95.0, 90.0), close=100.0, atr=3.0)  # limit 97
    assert (pick.value, pick.status) == (95.0, "eligible")


def test_a_too_close_2nd_lp_walks_down_to_the_3rd():
    pick = w.pick_support((99.0, 98.0, 90.0), close=100.0, atr=3.0)  # limit 97: 98 is too close, 90 passes
    assert (pick.value, pick.status) == (90.0, "walked")


def test_when_the_2nd_and_3rd_are_both_too_close_there_is_no_eligible_support():
    pick = w.pick_support((99.0, 98.0, 97.5), close=100.0, atr=3.0)
    assert (pick.value, pick.status) == (None, "none")


def test_a_too_close_1st_lp_is_irrelevant_and_a_far_1st_lp_is_never_used():
    assert w.pick_support((99.9, 90.0, 80.0), close=100.0, atr=3.0).value == 90.0  # the 1st (99.9) is too close and is not looked at
    assert w.pick_support((96.0, 95.0, 80.0), close=100.0, atr=3.0).value == 95.0  # the 1st is eligible too, and still not taken


def test_a_support_exactly_one_atr_below_the_close_is_eligible():
    assert w.pick_support((99.0, 97.5, 90.0), close=100.0, atr=2.5).value == 97.5  # 97.5 == 100 - 2.5
    assert w.pick_support((99.0, 97.75, 90.0), close=100.0, atr=2.5).value == 90.0  # a hair above the limit is not


@pytest.mark.parametrize("atr", [None, float("nan"), 0.0, -1.0])
def test_without_a_usable_atr_the_gate_is_off_and_the_plain_2nd_lp_is_used(atr):
    pick = w.pick_support((99.0, 98.0, 90.0), close=100.0, atr=atr)
    assert (pick.value, pick.status) == (98.0, "off")


def test_fewer_than_two_supports_give_none_as_before():
    assert w.pick_support((99.0,), 100.0, 3.0) == w.LpPick(None, "short")
    assert w.pick_support((), 100.0, None) == w.LpPick(None, "short")


# ---- the daily ATR ------------------------------------------------------------------------------------------------------------------

def daily_frame(sessions: int, start="2026-01-02", rng=4.0) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=sessions)
    return pd.DataFrame({"open": 100.0, "high": 100.0 + rng / 2, "low": 100.0 - rng / 2, "close": 100.0, "volume": 1000}, index=idx)


def cidx(*stamps: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([pd.Timestamp(x) for x in stamps])


def test_the_daily_atr_is_wilder_smoothing_of_the_true_range_with_the_gap():
    d = daily_frame(30)
    d.loc[d.index[20], ["open", "high", "low", "close"]] = [110.0, 112.0, 108.0, 110.0]  # a gap up on session 20: the true range includes the gap
    atr = compute_atr_wilder(d["high"], d["low"], d["close"])
    assert atr.iloc[20] > atr.iloc[19]  # (high - previous close = 12 > high - low = 4)
    out = daily_atr_for_candles(cidx(f"{d.index[25].date()} 09:30"), d)
    assert out[0] == pytest.approx(atr.iloc[24])  # the session before the candle's date


def test_the_atr_is_as_of_the_last_session_strictly_before_the_candle_date():
    d = daily_frame(30)
    atr = compute_atr_wilder(d["high"], d["low"], d["close"])
    day = d.index[20]
    out = daily_atr_for_candles(cidx(f"{day.date()} 09:30", f"{day.date()} 15:30", f"{d.index[21].date()} 09:30"), d)
    assert out[0] == pytest.approx(atr.iloc[19]) and out[1] == pytest.approx(atr.iloc[19])  # the candle's own session is not used, even at 15:30
    assert out[2] == pytest.approx(atr.iloc[20])


def test_a_later_daily_bar_never_changes_an_earlier_candle():
    d = daily_frame(40)
    early = cidx(f"{d.index[22].date()} 11:30")
    before = daily_atr_for_candles(early, d)[0]
    changed = d.copy()
    changed.loc[changed.index[30:], ["high", "low", "close"]] = [300.0, 10.0, 150.0]  # later sessions rewritten wildly
    assert daily_atr_for_candles(early, changed)[0] == before
    assert daily_atr_for_candles(early, d.iloc[:25])[0] == before  # and cut off entirely


def test_the_atr_needs_14_completed_sessions_before_the_candle_date():
    d = daily_frame(30)
    out = daily_atr_for_candles(cidx(f"{d.index[13].date()} 09:30", f"{d.index[14].date()} 09:30", f"{d.index[0].date()} 09:30"), d)
    assert np.isnan(out[0])  # 13 sessions before this date
    assert not np.isnan(out[1])  # 14 sessions: the first ATR
    assert np.isnan(out[2])
    assert np.isnan(daily_atr_for_candles(cidx("2026-02-02 09:30"), daily_frame(10))[0])  # only 10 sessions exist


@pytest.mark.parametrize("daily", [None, pd.DataFrame(), pd.DataFrame(columns=["open", "high", "low", "close", "volume"])])
def test_no_daily_bars_means_no_atr(daily):
    assert np.isnan(daily_atr_for_candles(cidx("2026-02-02 09:30", "2026-02-03 09:30"), daily)).all()


# ---- the four uses, through the real lookup and advance -------------------------------------------------------------------------------

LOWS = [100, 100, 80, 100, 100, 100, 90, 100, 100]  # the Yellow entry on candle 2 (low 80, close 81: 10% stop 72.0); a second signal on candle 6 (low 90, close 91)


def test_repeat_yellow_uses_the_selected_lp_and_falls_back_to_the_ten_percent_stop(make_lookup):
    c = candles(LOWS)
    events = [ev("yellow_up", 2), ev("yellow_up", 6)]
    # close 91, ATR 5 -> limit 86. 10% stop of the repeat = 0.9 x 90 = 81.
    # (a) 2nd LP 85 eligible: min(85, 81) = 81 (10% wins, as before)
    s = w.advance(None, c, events, [], "any", None, make_lookup(c, {6: (90.0, 85.0, 70.0)}, 5.0), False)
    assert (s.stop_price, s.stop_basis) == (pytest.approx(81.0), "10%")
    # (b) 2nd LP 87 too close -> the 3rd, 75 (eligible): min(75, 81) = 75, basis LP
    s = w.advance(None, c, events, [], "any", None, make_lookup(c, {6: (90.0, 87.0, 75.0)}, 5.0), False)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (75.0, "LP", "yellow_up_repeat")
    # (c) 2nd and 3rd too close: no LP -> 0.9 x low
    s = w.advance(None, c, events, [], "any", None, make_lookup(c, {6: (90.0, 87.0, 86.5)}, 5.0), False)
    assert (s.stop_price, s.stop_basis) == (pytest.approx(81.0), "10%")
    # the plain rule (gate off) takes the 2nd LP; where it is above the 10% stop the plain result is the 10% stop, the gated one the lower 3rd LP:
    lk = make_lookup(c, {6: (90.0, 88.0, 60.0)}, 5.0)  # 2nd 88 > 86 too close -> 3rd 60
    assert w.advance(None, c, events, [], "any", None, lk, False, None, w.PREVIOUS_RULES).stop_price == 60.0  # the gated 3rd LP (the rules before 2026-10-19 lowered the stop to it)
    assert w.advance(None, c, events, [], "any", None, lk, False).stop_price == pytest.approx(72.0)  # never lower a stop (2026-10-19): 60 < the 72 entry stop, ignored
    assert w.advance(None, c, events, [], "any", None, lk, False, None, w.PRE_LP_GATE_RULES).stop_price == pytest.approx(81.0)  # plain 88 > 81: the 10% stop


DOWN_LOWS = [100] * 6 + [118] * 6  # the market is above every stop from candle 6 on (no breach)
DOWN_CLOSES = [101.0, 101.0, 81.0, 101.0, 101.0, 101.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0]  # Yellow entry at 81 (candle 2, low 100 -> stop 90.0), then 120


def _entry_events(down: str):
    return [ev("yellow_up", 2), ev(down, 6)]


@pytest.mark.parametrize("down, moved_by", [("yellow_down", "yellow_down"), ("blue_down", "blue_down")])
def test_yellow_down_and_blue_down_raise_the_stop_to_the_selected_lp(make_lookup, down, moved_by):
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    # close 120, ATR 5 -> limit 115. entry stop 90.0 (0.9 x low 100).
    s = w.advance(None, c, _entry_events(down), [], "any", None, make_lookup(c, {6: (119.0, 112.0, 100.0)}, 5.0), False)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.stop_moved_at) == (112.0, "LP", moved_by, ts(6))  # the 2nd LP is eligible: unchanged by the gate
    s = w.advance(None, c, _entry_events(down), [], "any", None, make_lookup(c, {6: (119.0, 116.0, 110.0)}, 5.0), False)
    assert (s.stop_price, s.stop_basis, s.stop_moved_by) == (110.0, "LP", moved_by)  # 2nd (116) too close -> the 3rd (110)
    s = w.advance(None, c, _entry_events(down), [], "any", None, make_lookup(c, {6: (119.0, 118.0, 117.0)}, 5.0), False)
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (90.0, "10%", ts(2), "yellow_up_entry")  # none eligible: stop, basis and stop age unchanged
    assert s.latest_arrow_kind == down and s.instruction_type == (20 if down == "yellow_down" else 10)  # the pill and text still follow the arrow


def test_a_selected_lp_not_above_the_stop_is_no_change_and_no_stop_age(make_lookup):
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    s = w.advance(None, c, _entry_events("blue_down"), [], "any", None, make_lookup(c, {6: (119.0, 118.0, 85.0)}, 5.0), False)  # walks to 85 < stop 90: raise-only
    assert (s.stop_price, s.stop_basis, s.stop_moved_at, s.stop_moved_by) == (90.0, "10%", ts(2), "yellow_up_entry")


def test_trailing_uses_the_selected_lp_and_leaves_the_stop_when_none_is_eligible(make_lookup):
    # Yellow entry (stop 90.0), Blue Down on candle 6 sets an LP stop 100.0; the trail then asks every candle.
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    events = _entry_events("blue_down")
    supports = {6: (119.0, 100.0, 95.0), 7: (119.0, 116.0, 108.0), 8: (119.0, 118.0, 117.0), 9: (119.0, 118.0, 112.0)}
    log: list = []
    s = w.advance(None, c, events, [], "any", None, make_lookup(c, supports, 5.0), True, log)  # limit 115 at close 120
    # candle 7: 2nd 116 too close -> 3rd 108 -> trail 100 -> 108; candle 8: none eligible -> unchanged; candle 9: 3rd 112 -> 112
    assert [(t, o, n) for t, o, n in log] == [(ts(7), 100.0, 108.0), (ts(9), 108.0, 112.0)]
    assert (s.stop_price, s.stop_basis, s.stop_moved_by, s.stop_moved_at) == (112.0, "LP", "trail", ts(9))


def test_the_stop_age_moves_only_on_a_real_change(make_lookup):
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    events = _entry_events("blue_down")
    supports = {6: (119.0, 100.0, 95.0), 7: (119.0, 100.0, 95.0), 8: (119.0, 100.0, 95.0)}  # the same LP every candle: re-setting 100 is not a move
    s = w.advance(None, c, events, [], "any", None, make_lookup(c, supports, 5.0), True)
    assert (s.stop_price, s.stop_moved_by, s.stop_moved_at) == (100.0, "blue_down", ts(6))


def test_the_switch_off_and_a_missing_atr_both_reproduce_the_old_behaviour(make_lookup):
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    events = _entry_events("blue_down")
    supports = {6: (119.0, 116.0, 110.0)}
    gated = w.advance(None, c, events, [], "any", None, make_lookup(c, supports, 5.0), False)
    off = w.advance(None, c, events, [], "any", None, make_lookup(c, supports, 5.0), False, None, w.PRE_LP_GATE_RULES)
    no_atr = w.advance(None, c, events, [], "any", None, make_lookup(c, supports, None), False)
    nan_atr = w.advance(None, c, events, [], "any", None, make_lookup(c, supports, float("nan")), False)
    assert gated.stop_price == 110.0 and off.stop_price == 116.0  # the plain 2nd LP
    assert no_atr == off == nan_atr  # ATR unavailable: the current rule applies


def test_a_plain_callable_is_used_as_it_is_under_both_rule_sets():
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    fixed = lambda pos: 112.0 if pos == 6 else None  # noqa: E731 -- a stand-in lookup without `.plain`
    for rules in (w.CURRENT_RULES, w.PREVIOUS_RULES):
        assert w.advance(None, c, _entry_events("blue_down"), [], "any", None, fixed, False, None, rules).stop_price == 112.0


def test_the_rule_sets():
    assert w.CURRENT_RULES.lp_atr_gate is True
    assert w.PREVIOUS_RULES == replace(w.CURRENT_RULES, never_lower_stop=False, gray_down_entry_buffer=False)  # main's rules as they were before 2026-10-19 (gate on)
    assert w.PRE_LP_GATE_RULES == replace(w.PREVIOUS_RULES, lp_atr_gate=False)  # and before the gate
    assert w.PRE_RAISE_ONLY_RULES.lp_atr_gate is False and w.PRE_RAISE_ONLY_RULES.down_arrows_raise_only is False
    assert w.PRE_GRAY_RAISE_ONLY_RULES.lp_atr_gate is False and w.LEGACY_RULES.lp_atr_gate is False
    assert w.LP_GATE_ATR_MULTIPLE == 1.0


def test_the_gate_stats_count_each_selection(make_lookup):
    c = candles(DOWN_LOWS, DOWN_CLOSES)
    lk = make_lookup(c, {6: (119.0, 116.0, 110.0), 7: (119.0, 100.0, 95.0), 8: (119.0, 118.0, 117.0), 9: (119.0,)}, 5.0)
    for pos in (6, 7, 8, 9):
        lk(pos)
    assert lk.gate_stats == {"uses": 4, "eligible": 1, "walked": 1, "none": 1, "off": 0, "short": 1}
    assert lk.plain(6) == 116.0 and lk.plain(9) is None


# ---- update_warren_watch and the entry points ------------------------------------------------------------------------------------------

def _watch_world(monkeypatch, supports=(99.0, 98.0, 90.0)):
    from test_warren_watch_data import NOW, SETTINGS, bars, canned, fake_lp  # the module's own fixtures (real 60m bars, canned arrows)

    canned(monkeypatch, {"GATE": [("yellow_up", "2026-09-01 09:30"), ("yellow_down", "2026-09-10 09:30")]})
    fake_lp(monkeypatch, list(supports))
    return NOW, SETTINGS, bars("2025-08-01", "2026-10-16")


def _flat_daily() -> pd.DataFrame:
    return daily_frame(300, start="2025-08-01", rng=4.0)  # ATR(14) = 4.0 everywhere


def test_update_warren_watch_applies_the_gate_with_daily_bars_and_not_without(monkeypatch, engine):
    now, settings, frame = _watch_world(monkeypatch)  # flat bars: close 100, entry stop 0.9 x 99 = 89.1; supports 99 / 98 / 90
    gated = wwd.update_warren_watch("GATE", frame, settings, now=now, dry_run=True, daily=_flat_daily())
    plain = wwd.update_warren_watch("GATE", frame, settings, now=now, dry_run=True, daily=pd.DataFrame())
    # limit = 100 - 4 = 96: the 2nd LP 98 is too close, the 3rd 90 passes -> Yellow Down raises 89.1 to 90; plain: 98
    assert gated.changes["<new row>"][1].startswith("yellow entry") and "stop 90.00 LP" in gated.changes["<new row>"][1]
    assert "stop 98.00 LP" in plain.changes["<new row>"][1]
    assert gated.daily_atr is True and plain.daily_atr is False
    assert gated.lp_gate["walked"] >= 1 and plain.lp_gate["off"] >= 1 and plain.lp_gate["walked"] == 0


def test_update_warren_watch_reads_the_daily_bars_from_the_cache_only(monkeypatch, engine):
    now, settings, frame = _watch_world(monkeypatch)
    seen = []

    def spy(ticker, lookback_days, reference=None):
        seen.append((ticker, lookback_days, reference))
        return _flat_daily()

    monkeypatch.setattr(wwd, "read_cached_completed_daily_bars", spy)  # the cache reader: a pure read (no fetch, no write)
    update = wwd.update_warren_watch("GATE", frame, settings, now=now, dry_run=True)
    assert seen == [("GATE", wwd.DAILY_ATR_LOOKBACK_DAYS, now)] and update.daily_atr is True


def test_the_rebuild_replay_and_its_guard_both_use_the_gate_and_differ_only_in_the_2026_10_19_rules(monkeypatch, engine):
    now, settings, frame = _watch_world(monkeypatch)
    monkeypatch.setattr(rb, "watch_replay", wwd.watch_replay)
    monkeypatch.setattr(rb, "completed_candles", lambda b, n: wwd.completed_candles(b, now))
    monkeypatch.setattr(rb, "load_daily_bars", lambda ticker, n=None: _flat_daily())
    rb._DAILY.clear()
    through = datetime(2026, 10, 16, 15, 30)
    current = rb.replay_state("GATE", frame, settings, through, rules=w.CURRENT_RULES).state
    guard = rb.replay_state("GATE", frame, settings, through, rules=rb.GUARD_RULES).state
    pre_gate = rb.replay_state("GATE", frame, settings, through, rules=w.PRE_LP_GATE_RULES).state
    assert current.stop_price == 90.0 and guard.stop_price == 90.0 and pre_gate.stop_price == 98.0  # the guard keeps the gate ON (it is the rules before 2026-10-19); gate OFF gives 98
    assert rb.GUARD_RULES == w.PREVIOUS_RULES and rb.GUARD_RULES.lp_atr_gate is True and not rb.GUARD_RULES.never_lower_stop and not rb.GUARD_RULES.gray_down_entry_buffer
    rb._DAILY.clear()


def test_the_nightly_step_sums_and_logs_the_gate_counts_and_the_tickers_without_a_daily_atr(monkeypatch, caplog):
    updates = {
        "AAA": WatchUpdate("unchanged", 3, 10, {}, {"uses": 10, "eligible": 6, "walked": 2, "none": 1, "off": 0, "short": 1}, True),
        "BBB": WatchUpdate("unchanged", 1, 10, {}, {"uses": 4, "eligible": 0, "walked": 0, "none": 0, "off": 4, "short": 0}, False),
    }
    monkeypatch.setattr(nightly, "update_warren_watch", lambda ticker, bars, settings, **kw: updates[ticker])
    monkeypatch.setattr(nightly, "get_liquidity_zone_settings", lambda session: SimpleNamespace(max_lps_per_side=3))
    monkeypatch.setattr(nightly, "to_engine_settings", lambda s: s)
    with caplog.at_level(logging.INFO, logger=nightly.logger.name):
        out = nightly.update_watch_table(["AAA", "BBB"], {"AAA": pd.DataFrame({"x": [1]}), "BBB": pd.DataFrame({"x": [1]})})
    assert out["watch_lp_gate"] == {"uses": 14, "eligible": 6, "walked": 2, "none": 1, "off": 4, "short": 1}
    assert out["watch_no_daily_atr"] == ["BBB"]
    line = next(r.getMessage() for r in caplog.records if "LP gate" in r.getMessage())
    assert "14 selections" in line and "4 with no daily ATR" in line and "Tickers with no daily ATR: 1 (BBB)" in line


@pytest.fixture
def engine(monkeypatch):
    from sqlmodel import SQLModel, create_engine

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    monkeypatch.setattr(wwd, "engine", eng)
    return eng
