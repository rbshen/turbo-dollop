"""scoring/opportunity_rules.py: every rule of the weekly opportunity agent at its boundary, plus the edge cases (unrankable,
delisted, stale or provisional last bar, not-covered signals). Pure: no DB, no network."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import opportunity_rules as r

AS_OF = date(2026, 10, 9)


def price(**kw) -> r.PriceFeatures:
    base = dict(
        first_bar_date=date(2024, 9, 1), last_bar_date=AS_OF, n_bars=500, close=100.0, adv_usd=100e6, atr=2.0,
        drawdown_pct=35.0, higher_low=True, above_10w_sma=True, ma_slope_now=-0.5, ma_slope_4w_ago=-1.5,
    )
    base.update(kw)
    return r.PriceFeatures(**base)


def feats(**kw) -> r.Features:
    """A Quality stock that passes the gate and rule A by default; each test overrides what it probes."""
    base = dict(
        ticker="AAA", overall_verdict="Pass", overall_score=80, steps_score=80.0, moat="wide_moat", moat_multiplier=1.0,
        price=price(), stage="advance", ma_slope_pct=1.0, vs_ma_pct=10.0, mansfield_rs=2.0, weeks_in_advance=20,
        momentum_rank=10, momentum_group_size=500, return_3m=0.10, return_12m=0.40, signal_status=r.SIGNAL_NONE,
    )
    base.update(kw)
    return r.Features(**base)


# --- gate -------------------------------------------------------------------------------------------------------------


def test_a_healthy_ticker_passes_the_gate():
    assert r.gate_reason(feats(), AS_OF) is None


def test_spy_is_excluded_whatever_else_is_true():
    assert r.gate_reason(feats(ticker="SPY"), AS_OF) == r.GATE_EXCLUDED


def test_a_delisted_ticker_is_dropped():
    assert r.gate_reason(feats(delisted=True), AS_OF) == r.GATE_DELISTED


def test_a_ticker_with_no_bars_is_dropped():
    assert r.gate_reason(feats(price=None), AS_OF) == r.GATE_NO_BARS


def test_a_stale_last_bar_is_dropped_even_one_session_behind():
    assert r.gate_reason(feats(price=price(last_bar_date=date(2026, 10, 8))), AS_OF) == r.GATE_STALE_BAR


def test_a_provisional_as_of_bar_is_dropped():
    assert r.gate_reason(feats(provisional_last_bar=True), AS_OF) == r.GATE_PROVISIONAL_BAR


def test_twelve_months_of_bars_is_enough_and_eleven_is_not():
    assert r.gate_reason(feats(price=price(first_bar_date=date(2025, 10, 9))), AS_OF) is None  # exactly 12 months
    assert r.gate_reason(feats(price=price(first_bar_date=date(2025, 10, 10))), AS_OF) == r.GATE_SHORT_HISTORY


def test_the_dollar_volume_floor_is_inclusive_at_25_million():
    assert r.gate_reason(feats(price=price(adv_usd=25_000_000.0)), AS_OF) is None
    assert r.gate_reason(feats(price=price(adv_usd=24_999_999.0)), AS_OF) == r.GATE_ILLIQUID


def test_an_unknown_dollar_volume_fails_the_floor():
    assert r.gate_reason(feats(price=price(adv_usd=None)), AS_OF) == r.GATE_ILLIQUID


# --- tiers ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("verdict, tier", [
    ("Pass", r.TIER_QUALITY), ("Strong Pass", r.TIER_QUALITY),
    ("Pass with caution", r.TIER_MOMENTUM_ONLY), ("Fail", r.TIER_MOMENTUM_ONLY), (None, r.TIER_MOMENTUM_ONLY),
])
def test_tier_follows_the_stored_overall_verdict(verdict, tier):
    assert r.tier_for(feats(overall_verdict=verdict)) == tier


def test_an_etf_is_the_etf_tier_whatever_its_verdict():
    assert r.tier_for(feats(is_etf=True, overall_verdict="Pass")) == r.TIER_ETF


# --- list A -----------------------------------------------------------------------------------------------------------


def test_quality_qualifies_with_advance_a_rising_ma_and_positive_rs():
    assert r.momentum_rule_ids(feats(), r.TIER_QUALITY) == [r.RULE_A]


@pytest.mark.parametrize("override", [
    dict(stage="top"), dict(stage="base"), dict(stage=None), dict(ma_slope_pct=0.0), dict(ma_slope_pct=None),
    dict(mansfield_rs=0.0), dict(mansfield_rs=None), dict(vs_ma_pct=None),
])
def test_any_failed_or_unknown_base_condition_keeps_a_ticker_off_list_a(override):
    assert r.momentum_rule_ids(feats(**override), r.TIER_QUALITY) == []


def test_quality_extension_ceiling_is_strictly_below_20():
    assert r.momentum_rule_ids(feats(vs_ma_pct=19.99), r.TIER_QUALITY) == [r.RULE_A]
    assert r.momentum_rule_ids(feats(vs_ma_pct=20.0), r.TIER_QUALITY) == []


def test_quality_needs_no_rank():
    assert r.momentum_rule_ids(feats(momentum_rank=None, momentum_group_size=None), r.TIER_QUALITY) == [r.RULE_A]


def test_momentum_only_ceiling_is_15():
    assert r.momentum_rule_ids(feats(overall_verdict="Fail", vs_ma_pct=14.99), r.TIER_MOMENTUM_ONLY) == [r.RULE_A]
    assert r.momentum_rule_ids(feats(overall_verdict="Fail", vs_ma_pct=15.0), r.TIER_MOMENTUM_ONLY) == []


@pytest.mark.parametrize("field, ok, bad", [
    ("weeks_in_advance", 52, 53), ("return_3m", 0.30, 0.31), ("return_12m", 1.50, 1.51),
])
def test_momentum_only_guards_are_inclusive_at_their_limit(field, ok, bad):
    assert r.momentum_rule_ids(feats(**{field: ok}), r.TIER_MOMENTUM_ONLY) == [r.RULE_A]
    assert r.momentum_rule_ids(feats(**{field: bad}), r.TIER_MOMENTUM_ONLY) == []


@pytest.mark.parametrize("field", ["weeks_in_advance", "return_3m", "return_12m", "momentum_rank", "momentum_group_size"])
def test_an_unrankable_or_unmeasurable_momentum_only_stock_is_never_listed(field):
    assert r.momentum_rule_ids(feats(**{field: None}), r.TIER_MOMENTUM_ONLY) == []


def test_momentum_only_needs_the_top_quintile_of_the_ranked_stocks():
    assert r._top_cut(575, r.MOMENTUM_ONLY_TOP_FRACTION) == 115  # exact: 575 x 0.2 in floats would round up to 116
    assert r.momentum_rule_ids(feats(momentum_rank=115, momentum_group_size=575), r.TIER_MOMENTUM_ONLY) == [r.RULE_A]
    assert r.momentum_rule_ids(feats(momentum_rank=116, momentum_group_size=575), r.TIER_MOMENTUM_ONLY) == []


def test_etf_needs_the_top_third_of_its_own_group_and_the_20_ceiling():
    etf = dict(is_etf=True, overall_verdict=None)
    assert r.momentum_rule_ids(feats(momentum_rank=10, momentum_group_size=28, **etf), r.TIER_ETF) == [r.RULE_A]
    assert r.momentum_rule_ids(feats(momentum_rank=11, momentum_group_size=28, **etf), r.TIER_ETF) == []
    assert r.momentum_rule_ids(feats(momentum_rank=1, momentum_group_size=28, vs_ma_pct=20.0, **etf), r.TIER_ETF) == []


def test_leveraged_etfs_are_ranked_in_their_own_small_group():
    etf = dict(is_etf=True, overall_verdict=None, leverage=3)
    assert r.momentum_rule_ids(feats(momentum_rank=1, momentum_group_size=3, **etf), r.TIER_ETF) == [r.RULE_A]
    assert r.momentum_rule_ids(feats(momentum_rank=2, momentum_group_size=3, **etf), r.TIER_ETF) == []


def test_an_unranked_etf_is_never_listed():
    assert r.momentum_rule_ids(feats(is_etf=True, momentum_rank=None, momentum_group_size=None), r.TIER_ETF) == []


# --- list B -----------------------------------------------------------------------------------------------------------


def test_b1_is_a_base_or_a_pending_advance_for_quality_only():
    assert r.reversal_rule_ids(feats(stage="base", price=price(drawdown_pct=5.0)), r.TIER_QUALITY) == [r.RULE_B1]
    assert r.reversal_rule_ids(feats(stage="decline", pending_direction="advance", price=price(drawdown_pct=5.0)), r.TIER_QUALITY) == [r.RULE_B1]
    assert r.reversal_rule_ids(feats(stage="base", price=price(drawdown_pct=5.0)), r.TIER_MOMENTUM_ONLY) == []
    assert r.reversal_rule_ids(feats(stage="base", is_etf=True, price=price(drawdown_pct=5.0)), r.TIER_ETF) == []


def test_b1_does_not_fire_for_a_pending_decline_or_a_plain_decline():
    assert r.reversal_rule_ids(feats(stage="decline", pending_direction="decline", price=price(drawdown_pct=5.0)), r.TIER_QUALITY) == []


def test_b2_drawdown_threshold_is_20_for_quality_and_etf_and_30_for_momentum_only():
    assert r.price_structure_ok(feats(price=price(drawdown_pct=20.0)), r.TIER_QUALITY)
    assert not r.price_structure_ok(feats(price=price(drawdown_pct=19.99)), r.TIER_QUALITY)
    assert r.price_structure_ok(feats(price=price(drawdown_pct=20.0)), r.TIER_ETF)
    assert not r.price_structure_ok(feats(price=price(drawdown_pct=29.99)), r.TIER_MOMENTUM_ONLY)
    assert r.price_structure_ok(feats(price=price(drawdown_pct=30.0)), r.TIER_MOMENTUM_ONLY)


@pytest.mark.parametrize("override", [
    dict(higher_low=False), dict(above_10w_sma=False),
    dict(ma_slope_now=-1.5, ma_slope_4w_ago=-1.5),  # not strictly above its value 4 weeks ago
    dict(ma_slope_now=-2.01, ma_slope_4w_ago=-5.0),  # still rising, but below the -2% floor
    dict(higher_low=None), dict(above_10w_sma=None), dict(drawdown_pct=None), dict(ma_slope_now=None), dict(ma_slope_4w_ago=None),
])
def test_b2_needs_every_part_of_the_price_structure(override):
    assert not r.price_structure_ok(feats(price=price(**override)), r.TIER_QUALITY)


def test_b2_slope_floor_is_inclusive_at_minus_two():
    assert r.price_structure_ok(feats(price=price(ma_slope_now=-2.0, ma_slope_4w_ago=-3.0)), r.TIER_QUALITY)


def test_b2_with_no_bars_is_false():
    assert not r.price_structure_ok(feats(price=None), r.TIER_QUALITY)


@pytest.mark.parametrize("stage", ["decline", "base"])
def test_b3_fires_for_quality_with_a_signal_in_decline_or_base(stage):
    f = feats(stage=stage, signal_status=r.SIGNAL_FIRED, price=price(drawdown_pct=5.0))
    assert r.RULE_B3 in r.reversal_rule_ids(f, r.TIER_QUALITY)


@pytest.mark.parametrize("stage", ["advance", "top", None])
def test_b3_needs_decline_or_base(stage):
    assert r.reversal_rule_ids(feats(stage=stage, signal_status=r.SIGNAL_FIRED, price=price(drawdown_pct=5.0)), r.TIER_QUALITY) == []


@pytest.mark.parametrize("status", [r.SIGNAL_NONE, r.SIGNAL_NOT_COVERED])
def test_b3_needs_a_fired_signal(status):
    assert r.reversal_rule_ids(feats(stage="decline", signal_status=status, price=price(drawdown_pct=5.0)), r.TIER_QUALITY) == []


def test_b3_is_quality_only():
    f = feats(stage="decline", signal_status=r.SIGNAL_FIRED, price=price(drawdown_pct=5.0))
    assert r.reversal_rule_ids(f, r.TIER_MOMENTUM_ONLY) == []


def test_each_reversal_rule_keeps_its_own_id():
    f = feats(stage="base", signal_status=r.SIGNAL_FIRED)  # drawdown 35: B2 too
    assert r.reversal_rule_ids(f, r.TIER_QUALITY) == [r.RULE_B1, r.RULE_B2, r.RULE_B3]


# --- one list per ticker: trend stage decides ----------------------------------------------------------------------------


@pytest.mark.parametrize("weeks, expected", [(8, r.LIST_REVERSAL), (9, r.LIST_MOMENTUM), (1, r.LIST_REVERSAL), (60, r.LIST_MOMENTUM), (None, None)])
def test_the_fresh_advance_cutoff_is_exactly_eight_weeks(weeks, expected):
    assert r.FRESH_ADVANCE_MAX_WEEKS == 8
    assert r.assign_list(feats(stage="advance", weeks_in_advance=weeks)) == expected


@pytest.mark.parametrize("stage, pending, expected", [
    ("decline", None, r.LIST_REVERSAL), ("base", None, r.LIST_REVERSAL), ("top", None, None), (None, None, None),
    ("top", "advance", r.LIST_REVERSAL), ("decline", "advance", r.LIST_REVERSAL), ("top", "decline", None), ("base", "decline", r.LIST_REVERSAL),
])
def test_assign_list_by_stage(stage, pending, expected):
    assert r.assign_list(feats(stage=stage, pending_direction=pending, weeks_in_advance=None)) == expected


def test_an_established_advance_wins_over_a_pending_advance_flag():
    assert r.assign_list(feats(stage="advance", weeks_in_advance=20, pending_direction="advance")) == r.LIST_MOMENTUM


def test_fresh_advance_at_8_weeks_is_never_on_momentum_even_when_every_a_rule_passes():
    assert r.momentum_rule_ids(feats(weeks_in_advance=8), r.TIER_QUALITY) == []
    assert r.momentum_rule_ids(feats(weeks_in_advance=9), r.TIER_QUALITY) == [r.RULE_A]


def test_fresh_advance_is_on_reversal_only_through_b2():
    deep = feats(weeks_in_advance=8, price=price(drawdown_pct=35.0))
    shallow = feats(weeks_in_advance=8, price=price(drawdown_pct=5.0))
    assert r.place(deep, r.TIER_QUALITY) == r.Placement(r.LIST_REVERSAL, [r.RULE_B2])
    assert r.place(shallow, r.TIER_QUALITY) == r.Placement(None, [])  # fresh advance without B2: on neither list
    assert r.place(feats(weeks_in_advance=9, price=price(drawdown_pct=5.0)), r.TIER_QUALITY).list_name == r.LIST_MOMENTUM


def test_b2_is_not_evaluated_for_an_established_advance_or_for_top():
    assert r.reversal_rule_ids(feats(stage="advance", weeks_in_advance=40), r.TIER_QUALITY) == []
    assert r.reversal_rule_ids(feats(stage="top", weeks_in_advance=None), r.TIER_QUALITY) == []
    assert r.price_structure_ok(feats(stage="top"), r.TIER_QUALITY)  # the chart test itself still passes; the stage keeps it off the list


def test_top_stage_is_on_neither_list_even_with_a_fired_signal_and_a_perfect_chart():
    f = feats(stage="top", weeks_in_advance=None, signal_status=r.SIGNAL_FIRED)
    assert r.place(f, r.TIER_QUALITY) == r.Placement(None, [])


def test_a_pending_advance_from_top_is_a_quality_b1_reversal():
    f = feats(stage="top", pending_direction="advance", weeks_in_advance=None, price=price(drawdown_pct=5.0))
    assert r.place(f, r.TIER_QUALITY) == r.Placement(r.LIST_REVERSAL, [r.RULE_B1])


def test_an_established_advance_with_a_deep_drawdown_gets_the_tag_instead_of_a_reversal_listing():
    p = r.place(feats(weeks_in_advance=55, price=price(drawdown_pct=31.0)), r.TIER_QUALITY)
    assert p == r.Placement(r.LIST_MOMENTUM, [r.RULE_A], deep_pullback=True)


def test_the_deep_pullback_tag_uses_the_tiers_own_drawdown_threshold():
    mo = dict(overall_verdict="Fail", weeks_in_advance=30, vs_ma_pct=5.0)
    assert r.place(feats(price=price(drawdown_pct=25.0), **mo), r.TIER_MOMENTUM_ONLY).deep_pullback is False  # needs 30
    assert r.place(feats(price=price(drawdown_pct=30.0), **mo), r.TIER_MOMENTUM_ONLY).deep_pullback is True
    assert r.place(feats(price=price(drawdown_pct=20.0), weeks_in_advance=30), r.TIER_QUALITY).deep_pullback is True  # Quality: 20


def test_no_deep_pullback_without_the_rest_of_the_price_structure():
    assert r.place(feats(weeks_in_advance=30, price=price(drawdown_pct=40.0, higher_low=False)), r.TIER_QUALITY).deep_pullback is False


def test_a_momentum_stage_ticker_that_fails_rule_a_is_not_rerouted_to_reversal():
    f = feats(weeks_in_advance=30, vs_ma_pct=25.0, price=price(drawdown_pct=35.0))  # extended: fails A, passes B2's chart test
    assert r.place(f, r.TIER_QUALITY) == r.Placement(None, [])


def test_decline_and_base_keep_their_reversal_rules_unchanged():
    f = feats(stage="base", signal_status=r.SIGNAL_FIRED, weeks_in_advance=None)
    assert r.place(f, r.TIER_QUALITY) == r.Placement(r.LIST_REVERSAL, [r.RULE_B1, r.RULE_B2, r.RULE_B3])
    assert r.place(f, r.TIER_MOMENTUM_ONLY) == r.Placement(r.LIST_REVERSAL, [r.RULE_B2])


@pytest.mark.parametrize("stage", ["advance", "decline", "base", "top", None])
@pytest.mark.parametrize("weeks", [None, 1, 8, 9, 60])
@pytest.mark.parametrize("pending", [None, "advance", "decline"])
@pytest.mark.parametrize("tier", [r.TIER_QUALITY, r.TIER_MOMENTUM_ONLY, r.TIER_ETF])
def test_a_ticker_can_never_qualify_for_both_lists(stage, weeks, pending, tier):
    f = feats(stage=stage, weeks_in_advance=weeks, pending_direction=pending, signal_status=r.SIGNAL_FIRED, overall_verdict="Pass" if tier == r.TIER_QUALITY else "Fail", is_etf=tier == r.TIER_ETF)
    assert not (r.momentum_rule_ids(f, tier) and r.reversal_rule_ids(f, tier))


# --- tags -------------------------------------------------------------------------------------------------------------


def test_late_trend_starts_at_52_weeks_in_advance():
    assert "late_trend" not in r.build_tags(feats(weeks_in_advance=51), r.TIER_QUALITY, r.LIST_MOMENTUM, False, None, None)
    assert r.build_tags(feats(weeks_in_advance=52), r.TIER_QUALITY, r.LIST_MOMENTUM, False, None, None)["late_trend"] is True


def test_leveraged_etf_tag_carries_the_factor():
    f = feats(is_etf=True, leverage=3, overall_verdict=None)
    assert r.build_tags(f, r.TIER_ETF, r.LIST_MOMENTUM, False, None, None)["leveraged"] == 3
    assert "leveraged" not in r.build_tags(feats(is_etf=True, overall_verdict=None), r.TIER_ETF, r.LIST_MOMENTUM, False, None, None)


@pytest.mark.parametrize("steps, overall, expected", [(72.0, 50, True), (72.0, 72, False), (69.9, 48, False), (70.0, 49, True), (None, 49, False)])
def test_held_back_by_moat(steps, overall, expected):
    f = feats(overall_verdict="Fail", steps_score=steps, overall_score=overall)
    assert r.held_back_by_moat(f) is expected


def test_why_not_quality_keeps_the_raw_fail_key_and_names_the_failed_steps():
    f = feats(
        overall_verdict="Fail", moat=None,
        step_scores={"step1": 90, "step2": 40, "step4": None, "step5": 60},
        step_verdicts={"step1": "Pass", "step2": "Fail", "step4": "insufficient_data", "step5": "Pass"},
    )
    why = r.why_not_quality(f)
    assert why == {"overall_verdict": "Fail", "failed_steps": ["Growth rate", "Debt"], "incomplete_steps": ["Profitability"], "moat": None}


def test_why_not_quality_skips_a_not_supported_step():
    f = feats(
        step_scores={"step1": 90, "step2": 90, "step4": 90, "step5": None},
        step_verdicts={"step1": "Pass", "step2": "Pass", "step4": "Pass", "step5": "not_supported"},
    )
    assert r.why_not_quality(f) == {"overall_verdict": "Pass", "failed_steps": [], "incomplete_steps": [], "moat": "wide_moat"}


def test_only_momentum_only_rows_carry_why_not_quality_and_only_quality_rows_a_signal_status():
    mo = r.build_tags(feats(overall_verdict="Fail"), r.TIER_MOMENTUM_ONLY, r.LIST_MOMENTUM, False, None, None)
    q = r.build_tags(feats(), r.TIER_QUALITY, r.LIST_REVERSAL, False, None, None)
    assert "why_not_quality" in mo and "signal_status" not in mo
    assert "why_not_quality" not in q and q["signal_status"] == r.SIGNAL_NONE


def test_market_and_sector_are_carried_and_there_is_no_also_on_tag():
    tags = r.build_tags(feats(), r.TIER_QUALITY, r.LIST_MOMENTUM, False, {"net_new_highs": 3}, {"etf": "XLK"})
    assert tags["market"] == {"net_new_highs": 3} and tags["sector"] == {"etf": "XLK"}
    assert "also_on" not in tags and "deep_pullback" not in tags


def test_the_deep_pullback_tag_is_a_momentum_row_tag_only():
    assert r.build_tags(feats(), r.TIER_QUALITY, r.LIST_MOMENTUM, True, None, None)["deep_pullback"] is True
    assert "deep_pullback" not in r.build_tags(feats(), r.TIER_QUALITY, r.LIST_REVERSAL, True, None, None)


# --- leveraged detection, rules hash ----------------------------------------------------------------------------------


@pytest.mark.parametrize("ticker, name, expected", [
    ("TQQQ", "ProShares UltraPro QQQ", 3), ("SOXL", None, 3), ("XYZ", "Direxion Daily Semiconductor Bull 3X ETF", 3),
    ("XYZ", "ProShares UltraPro S&P 500", 3), ("XYZ", "Something Daily 2x Long", 2),
    ("QQQ", "Invesco QQQ Trust, Series 1", None), ("XLK", "State Street Technology Select Sector SPDR ETF", None), ("ABC", None, None),
])
def test_leverage_factor(ticker, name, expected):
    assert r.leverage_factor(ticker, name) == expected


def test_the_rules_hash_is_stable_and_moves_with_any_threshold(monkeypatch):
    first = r.rules_hash()
    assert first == r.rules_hash() and len(first) == 64
    monkeypatch.setattr(r, "MIN_ADV_USD", 10e6)
    assert r.rules_hash() != first


def test_the_rules_definition_names_every_rule_id_and_is_json_serialisable():
    import json

    definition = r.rules_definition()
    json.dumps(definition)
    assert r.RULES_VERSION == "2" and definition["list_assignment"]["fresh_advance_max_weeks"] == r.FRESH_ADVANCE_MAX_WEEKS == 8
    assert definition["rule_ids"] == list(r.RULE_IDS) and set(r.RULE_LABELS) == set(r.RULE_IDS)
    assert all(rid.endswith(".v2") for rid in r.RULE_IDS)


# --- bar-derived features ---------------------------------------------------------------------------------------------


def bars(n: int, end: date = AS_OF, start_price: float = 50.0, drift: float = 0.0005, volume: float = 1e6, shock=None) -> pd.DataFrame:
    index = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    close = start_price * np.exp(drift * np.arange(n))
    if shock is not None:
        close = shock(close)
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": np.full(n, volume)}, index=index
    )


def test_price_features_basics():
    p = r.compute_price_features(bars(400), AS_OF)
    assert p.last_bar_date == AS_OF and p.n_bars == 400
    assert p.adv_usd == pytest.approx((bars(400)["close"] * 1e6).tail(50).mean())
    assert 0 < p.atr < 5
    assert p.drawdown_pct == pytest.approx(0.0 + (1 - p.close / (bars(400)["high"].tail(252).max())) * 100)


def test_bars_after_the_as_of_date_are_ignored():
    p = r.compute_price_features(bars(400, end=date(2026, 10, 16)), AS_OF)
    assert p.last_bar_date == AS_OF


def test_no_bars_gives_none():
    assert r.compute_price_features(bars(400).iloc[0:0], AS_OF) is None
    assert r.compute_price_features(bars(10, end=date(2026, 1, 2)).iloc[0:0], AS_OF) is None


def test_short_history_leaves_the_long_window_figures_unknown_not_imputed():
    p = r.compute_price_features(bars(30), AS_OF)
    assert p.adv_usd is None and p.drawdown_pct is None and p.higher_low is None
    assert p.above_10w_sma is None and p.ma_slope_now is None


def test_a_recovering_stock_has_a_drawdown_a_higher_low_and_a_rising_slope():
    def shock(c):
        c = c.copy()
        n = len(c)
        # long climb, a 40% crash 70 sessions ago to a trough 40 sessions ago, then a steady recovery with a higher low
        c[: n - 110] = np.linspace(80, 200, n - 110)
        c[n - 110 : n - 40] = np.linspace(200, 100, 70)
        c[n - 40 :] = np.linspace(100, 125, 40)
        return c

    p = r.compute_price_features(bars(500, shock=shock), AS_OF)
    assert p.drawdown_pct == pytest.approx((1 - 125 / (200 * 1.01)) * 100, abs=1.0)
    assert p.higher_low is True and p.above_10w_sma is True
    assert p.ma_slope_now > p.ma_slope_4w_ago


def test_a_fresh_low_is_not_a_higher_low():
    def shock(c):
        c = c.copy()
        c[-5:] = c[-5] * np.linspace(1, 0.5, 5)
        return c

    assert r.compute_price_features(bars(500, shock=shock), AS_OF).higher_low is False
