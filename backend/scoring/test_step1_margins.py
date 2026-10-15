"""The Step 1 Margins engine (scoring/step1_margins.py): the archetypes and anchors of the 2026-10 redesign, each rule on its own (one-off
clamp, boom-bust cap, fade cap, the single recent-fall charge, soft floor, positivity ceilings, the TTM nudge and its skip rules) and the
blend 0.5 x Gross + 0.5 x max(Net, Operating). Pure functions, no I/O."""

import numpy as np
import pytest

from scoring.step1_margins import (
    FADE_CAP,
    TTM_CAP,
    assess_margin_series,
    cap_boom_bust,
    clamp_one_off_years,
    classify_margins,
    ttm_allowed,
)

STEADY = [30.0] * 10
SLIDE = [60.0] * 7 + [55.0, 50.0, 45.0]  # six flat years at the old level, then 60 -> 55 -> 50 -> 45
DECLINE_60_36 = list(np.linspace(60, 36, 10))
RISING = list(np.linspace(20, 29, 10))
DIP_1Y = [40, 41, 42, 43, 44, 45, 45, 46, 47, 41]  # a fresh 47 -> 41 fall
DIP_2Y = [40, 41, 42, 43, 44, 45, 45, 46, 41, 38]  # a two-year fall that has not recovered
MID_DIP_RECOVERS = [40, 41, 42, 43, 44, 38, 36, 41, 44, 45]
FADE_FROM_PEAK = [20, 20, 21, 20, 22, 28, 30, 28, 26, 24]  # peaked at 30, ended at 24 (still above the 20-ish start and the median)
ROUND_TRIP = [5, 5, 5, 5, 5, 12, 15, 12, 8, 5]  # a boom that has faded all the way back to the start
CYCLE_BACK_TO_START = [8, 9, 10, 11, 12, 11, 10, 9, 8, 8]  # ends below its own median: a fall, not a fade from above

# Real series (FY2016-25, percent) behind the anchors. TTM: gross, operating, net; True = the outlier check flagged the ticker.
ANCHOR_SERIES = {
    "POOL": (
        [28.8, 28.9, 29.0, 28.9, 28.7, 30.5, 31.3, 30.0, 29.7, 29.7],
        [10.0, 10.2, 10.5, 10.7, 11.8, 15.7, 16.6, 13.5, 11.6, 11.0],
        [5.8, 6.9, 7.8, 8.2, 9.3, 12.3, 12.1, 9.4, 8.2, 7.7],
        (29.6, 10.8, 7.4),
        False,
    ),
    "CIEN": (
        [44.7, 44.5, 42.5, 43.2, 46.8, 47.6, 43.0, 42.8, 42.8, 42.0],
        [6.0, 7.7, 7.4, 9.7, 13.8, 13.7, 7.1, 8.8, 4.8, 6.5],
        [2.8, 45.0, -11.1, 7.1, 10.2, 13.8, 4.2, 5.8, 2.1, 2.6],
        (44.1, 14.1, 10.9),
        True,
    ),
    "PCAR": (
        [19.8, 18.9, 18.7, 18.8, 18.5, 18.2, 18.1, 21.7, 19.9, 16.2],
        [11.3, 10.8, 11.4, 11.6, 0.0, 9.8, 12.8, 16.9, 14.5, 10.4],
        [3.1, 8.6, 9.3, 9.3, 6.9, 7.9, 10.4, 13.1, 12.4, 8.4],
        (14.9, 9.8, 9.2),
        False,
    ),
    "BLDR": (
        [25.1, 24.6, 24.9, 27.2, 26.0, 29.4, 34.1, 35.2, 32.8, 29.0],
        [3.7, 4.1, 4.8, 5.4, 6.4, 12.0, 16.6, 12.7, 9.7, 5.2],
        [2.3, 0.6, 2.7, 3.0, 3.7, 8.7, 12.1, 9.0, 6.6, 2.9],
        (29.2, 3.0, 0.7),
        True,
    ),
    "HUM": (
        [14.3, 13.2, 19.7, 17.2, 20.3, 17.3, 18.5, 17.0, 14.6, 14.5],
        [3.2, 6.2, 3.6, 5.3, 6.1, 4.1, 3.8, 3.1, 1.4, 1.1],
        [1.1, 4.6, 3.0, 4.2, 4.4, 3.5, 3.0, 2.3, 1.0, 0.9],
        (13.7, 1.4, 0.9),
        False,
    ),
    "CVS": (
        [16.2, 15.4, 16.2, 17.7, 18.3, 17.8, 16.9, 15.2, 13.8, 13.8],
        [5.8, 5.2, 2.1, 4.7, 5.2, 4.6, 2.5, 3.8, 2.3, 2.6],
        [3.0, 3.6, -0.3, 2.6, 2.7, 2.7, 1.3, 2.3, 1.2, 0.4],
        (14.2, 2.0, 1.2),
        False,
    ),
}


def score(values, **kwargs):
    return assess_margin_series(values, **kwargs).score


def anchor(name, ttm=True):
    gross, operating, net, ttm_values, flagged = ANCHOR_SERIES[name]
    kwargs = {}
    if ttm:
        kwargs = dict(ttm_margins=dict(zip(("gross", "operating", "net"), ttm_values)), ttm_outlier_flagged=flagged)
    return classify_margins(gross, operating, net, **kwargs)


# --- archetypes -----------------------------------------------------------------------------------------------------------------------


def test_steady_and_rising_and_noise():
    assert score(STEADY) == 88
    assert score([30, 30.4, 29.7, 30.3, 29.8, 30.2, 29.6, 30.4, 29.9, 30.1]) == 88
    assert score(RISING) == 100


def test_sustained_decline_is_about_36_and_the_slide_is_at_or_below_it():
    decline = score(DECLINE_60_36)
    assert decline == 36
    slide = score(SLIDE)
    assert slide <= decline and slide == 35


def test_a_recent_one_year_dip_sits_below_steady_and_above_the_two_year_dip():
    one, two = score(DIP_1Y), score(DIP_2Y)
    assert (one, two) == (81, 53)
    assert two < one < score(STEADY)


def test_a_mid_trend_dip_that_recovers_is_mild_and_a_small_gap_below_average_is_ignored():
    assert score(MID_DIP_RECOVERS) >= 88
    assert score([30, 30.5, 29.5, 30.2, 29.8, 30.1, 29.9, 30.3, 30.0, 29.4]) == 88  # latest 2% below its average: inside the band
    assert score([30, 30.5, 29.5, 30.2, 29.8, 30.1, 29.9, 30.3, 30.0, 27.3]) < 88  # 10% below: a mild cut


def test_a_severe_but_positive_collapse_is_not_in_the_zero_to_ten_band():
    assert score([30.0] * 9 + [3.0]) == 30
    for series in (SLIDE, DECLINE_60_36, [20, 18, 16, 13, 10, 7, 5, 3, 2, 1], [30.0] * 9 + [0.5]):
        assert score(series) >= 20


# --- anchors (real series; targets from the 2026-10 investigation) --------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, low, high",
    [("POOL", 60, 70), ("CIEN", 55, 65), ("PCAR", 48, 58), ("BLDR", 42, 52), ("HUM", 24, 34), ("CVS", 30, 40)],
)
def test_anchor_margin_scores(name, low, high):
    result, _ = anchor(name)
    assert low <= result.score <= high, (name, result.score)


def test_anchors_are_clearly_above_the_floor_where_the_series_is_a_normalisation_or_one_off():
    for name in ("POOL", "CIEN", "PCAR", "BLDR"):
        assert anchor(name)[0].score >= 40
    for name in ("HUM", "CVS"):
        assert anchor(name)[0].score < 40  # a real, steady decline stays low


def test_pool_stable_gross_with_falling_profit_lands_mid_band_because_of_the_blend_and_the_boom_bust_cap():
    result, detail = anchor("POOL")
    assert detail["legs"]["gross"] > 85 and detail["legs"]["profit"] < 45
    assert detail["profit_leg"] == "operating" and detail["binding"] == "operating"
    assert 60 <= result.score <= 70


# --- rule 6: the one-off-year clamp ------------------------------------------------------------------------------------------------------


def test_clamp_pulls_an_isolated_outlier_year_into_its_neighbours_range():
    x, clamped = clamp_one_off_years(np.array([10.0] * 4 + [40.0] + [10.0] * 5))
    assert clamped == [4] and list(x) == [10.0] * 10
    assert score([10.0] * 4 + [40.0] + [10.0] * 5) == score([10.0] * 10) == 88
    assert score([10.0] * 4 + [0.0] + [10.0] * 5) == 88  # a freak dip, too


def test_clamp_never_touches_the_first_or_the_latest_year():
    for series in ([40.0] + [10.0] * 9, [10.0] * 9 + [40.0], [10.0] * 9 + [-30.0]):
        x, clamped = clamp_one_off_years(np.array(series))
        assert clamped == [] and list(x) == series


def test_clamp_needs_75_percent_of_level_and_1_5_times_the_neighbour_spread():
    small = [10.0] * 4 + [16.0] + [10.0] * 5  # 6 points outside a flat range: 60% of level 10, below the 75% line
    assert clamp_one_off_years(np.array(small))[1] == []
    noisy = [10, 14, 6, 15, 5, 19, 5, 14, 6, 12]  # swings as big as the outlier: no year clears 1.5x its neighbours' spread
    assert clamp_one_off_years(np.array(noisy, dtype=float))[1] == []
    level_shift = [10.0] * 5 + [30.0] * 5  # a permanent step is not a one-off
    assert clamp_one_off_years(np.array(level_shift))[1] == []


def test_clamp_repeats_at_most_twice_and_handles_the_cien_pair():
    three = [10.0, 10, 40, 10, 10, 40, 10, 10, 40, 10, 10, 10]
    assert len(clamp_one_off_years(np.array(three))[1]) == 2
    cien_net = ANCHOR_SERIES["CIEN"][2]
    assert assess_margin_series(cien_net).clamped_years == (1, 2)  # 45.0 in 2017 and -11.1 in 2018
    assert assess_margin_series(ANCHOR_SERIES["PCAR"][1]).clamped_years == (4,)  # the 2020 operating zero


def test_the_clamp_needs_five_years():
    assert clamp_one_off_years(np.array([10.0, 10, 40, 10]))[1] == []


# --- rule 7: the boom-bust cap -----------------------------------------------------------------------------------------------------------


def test_boom_bust_keeps_half_the_excess_of_a_boom_that_faded_back_to_baseline():
    x, applied = cap_boom_bust(np.array(ROUND_TRIP, dtype=float))
    assert applied
    assert list(x) == [5, 5, 5, 5, 5, 8.5, 10.0, 8.5, 6.5, 5.0]
    assert assess_margin_series(ROUND_TRIP).boom_bust is True


@pytest.mark.parametrize(
    "series",
    [
        [60, 58, 55, 52, 48, 45, 42, 40, 38, 36],  # a decline that starts high: no ordinary years before the boom
        [5, 5, 5, 5, 5, 12, 15, 12, 10, 9],  # the latest year is not back within +15% of the baseline
        [5, 5, 5, 5, 5, 12, 15, 12, 8, 2],  # ... or below -25%: a real collapse under the baseline
        [5, 5, 5, 12, 15, 12, 5],  # fewer than 8 years
        [5, 5, 5, 5, 5, 5, 5, 5, 5, 20],  # one boom year only (and it is the latest)
    ],
)
def test_boom_bust_does_not_apply(series):
    x, applied = cap_boom_bust(np.array(series, dtype=float))
    assert not applied and list(x) == series


def test_boom_bust_lifts_the_pool_style_fade():
    pool_operating = ANCHOR_SERIES["POOL"][1]
    assert assess_margin_series(pool_operating).boom_bust is True


# --- rule 5: the fade cap -----------------------------------------------------------------------------------------------------------------


def test_fade_cap_limits_the_recent_fall_charge_when_the_latest_year_is_still_at_or_above_the_median():
    capped = assess_margin_series(FADE_FROM_PEAK)
    assert capped.fade_capped and capped.charge_points == FADE_CAP == 35.0
    assert capped.score == 65


def test_fade_cap_does_not_apply_below_the_median_or_with_under_8_years_or_a_small_charge():
    below = assess_margin_series(CYCLE_BACK_TO_START)  # latest 8 < median 10
    assert not below.fade_capped and below.charge_points > FADE_CAP
    assert not assess_margin_series(FADE_FROM_PEAK[-7:]).fade_capped
    assert not assess_margin_series(DIP_1Y).fade_capped


# --- rule 4: the single recent-fall charge -------------------------------------------------------------------------------------------------


def test_a_recent_fall_is_charged_once_as_the_largest_of_four_measures_not_their_sum():
    result = assess_margin_series(ANCHOR_SERIES["PCAR"][2])  # PCAR net: several measures fire at once
    measures = result.wf["measures"]
    firing = [m for m in measures.values() if m >= 3.0]
    assert len(firing) >= 2
    assert result.charge_points == max(measures.values()) < sum(measures.values())
    assert result.charge == max(measures, key=measures.get)
    assert result.wf["recent_charge"] == pytest.approx(result.charge_points)


def test_the_recent_slope_blend_never_pulls_an_uptrend_down():
    # a gently rising series whose last 4 years wobble inside the -1.5% dead band: no recent charge at all
    gentle = [20, 20.5, 21, 21.5, 22, 22.5, 23, 23.5, 23.4, 23.6]
    result = assess_margin_series(gentle)
    assert result.wf["measures"]["slope"] == 0 and result.score == 100


def test_older_dips_decay_and_are_not_part_of_the_recent_charge():
    old_dip = [40, 41, 20, 41, 42, 43, 44, 45, 46, 47]  # a deep dip eight years back, fully recovered
    recent_dip = [40, 41, 42, 43, 44, 45, 46, 47, 48, 25]
    assert score(old_dip) > score(recent_dip)
    assert assess_margin_series(old_dip).wf["older_dips"] > 0


# --- rule 8: soft floor and the positivity ceiling ---------------------------------------------------------------------------------------


def test_soft_floor_maps_a_profitable_raw_zero_to_twenty():
    collapse = [20, 18, 16, 13, 10, 7, 5, 3, 2, 0.5]
    result = assess_margin_series(collapse)
    assert result.wf["soft_floor"] < 0 and 20 <= result.score <= 30


def test_positivity_ceiling_caps_a_latest_value_at_or_below_zero():
    losing = [10, 8, 6, 4, 2, 0, -2, -4, -6, -8]
    result = assess_margin_series(losing)
    assert result.ceiling == pytest.approx(8.0) and result.score <= 8  # 40 at zero, 0 at -10 points: 8 at -8
    assert assess_margin_series([10, 8, 6, 4, 2, 0.5, 0.4, 0.3, 0.2, 0.0]).ceiling == 40.0
    assert assess_margin_series([10] * 9 + [-10]).score == 0


# --- rule 10: the TTM nudge and its skip rules ---------------------------------------------------------------------------------------------


def test_ttm_bonus_and_penalty_are_capped_at_five_points():
    base = score(DIP_2Y)
    up = assess_margin_series(DIP_2Y, ttm=44.0).ttm_adjustment
    down = assess_margin_series(DIP_2Y, ttm=33.0).ttm_adjustment
    assert 0 < up <= TTM_CAP and -TTM_CAP <= down < 0
    assert score(DIP_2Y, ttm=44.0) > base > score(DIP_2Y, ttm=33.0)
    assert assess_margin_series(DIP_2Y, ttm=500.0).ttm_adjustment == pytest.approx(TTM_CAP)
    assert assess_margin_series(DIP_2Y, ttm=-500.0).ttm_adjustment == pytest.approx(-TTM_CAP)


def test_a_steady_series_gets_no_ttm_bonus_and_only_a_big_shortfall_a_penalty():
    assert assess_margin_series(STEADY, ttm=45.0).ttm_adjustment == 0  # no dip, no shortfall: nothing to recover
    assert assess_margin_series(STEADY, ttm=29.0).ttm_adjustment == 0  # inside the band
    assert assess_margin_series(STEADY, ttm=24.0).ttm_adjustment < 0


def test_ttm_needs_five_completed_years_and_a_positive_latest_year():
    assert assess_margin_series(DIP_2Y[-4:], ttm=44.0).ttm_adjustment == 0
    assert assess_margin_series(DIP_2Y[:-1] + [-3.0], ttm=44.0).ttm_adjustment == 0


def test_ttm_skip_rules():
    assert ttm_allowed([30.0, 31.0], 33.0, outlier_flagged=False)
    assert not ttm_allowed([30.0, 31.0], 33.0, outlier_flagged=True)  # a flagged ticker
    assert not ttm_allowed([30.0, 31.0], None, outlier_flagged=False)
    assert not ttm_allowed([10.0, 10.0], 10.0 + 8.01, outlier_flagged=False)  # more than 8 points away (50% of 10 is only 5)
    assert ttm_allowed([10.0, 10.0], 10.0 + 7.9, outlier_flagged=False)
    assert ttm_allowed([30.0, 31.0], 31.0 + 15.0, outlier_flagged=False)  # a bigger latest year widens the limit to 50% of it
    assert not ttm_allowed([60.0, 60.0], 60.0 + 30.1, outlier_flagged=False)  # more than 50% of the latest year
    assert ttm_allowed([60.0, 60.0], 60.0 + 29.9, outlier_flagged=False)
    assert not ttm_allowed([], 5.0, outlier_flagged=False)


def test_googl_style_net_margin_jump_is_skipped_but_gross_and_operating_still_apply():
    gross = [56, 56.5, 57, 57.5, 58, 56, 57, 57.5, 58, 58.2]
    operating = [30, 24, 20, 22, 25, 23, 26, 27, 32, 32.0]
    net = [20, 22, 18, 22, 25, 21, 24, 26, 30, 32.8]
    _, with_ttm = classify_margins(gross, operating, net, ttm_margins=dict(gross=60.9, operating=33.1, net=54.8))
    assert "ttm_adjustment" not in with_ttm["inputs"]["net"]  # 54.8 vs 32.8 is a 22-point gap, over the 16.4-point limit


def test_flagged_ticker_gets_no_ttm_at_all():
    _, flagged = classify_margins(DIP_2Y, DIP_2Y, DIP_2Y, ttm_margins=dict(gross=44.0, operating=44.0, net=44.0), ttm_outlier_flagged=True)
    assert all("ttm_adjustment" not in entry for entry in flagged["inputs"].values())
    plain, _ = classify_margins(DIP_2Y, DIP_2Y, DIP_2Y)
    assert classify_margins(DIP_2Y, DIP_2Y, DIP_2Y, ttm_margins=dict(gross=44.0, operating=44.0, net=44.0), ttm_outlier_flagged=True)[0] == plain


# --- rule 9: the combination -----------------------------------------------------------------------------------------------------------------


def test_margins_is_half_gross_plus_half_the_better_of_net_and_operating():
    for g, o, n in [
        (STEADY, RISING, DIP_2Y),
        (DECLINE_60_36, RISING, RISING),
        (RISING, SLIDE, SLIDE),
        (STEADY, DIP_1Y, DIP_2Y),
    ]:
        result, detail = classify_margins(g, o, n)
        gs = assess_margin_series(g).score_f
        profit = max(assess_margin_series(o).score_f, assess_margin_series(n).score_f)
        assert result.score == int(round(0.5 * gs + 0.5 * profit)), (gs, profit)


def test_there_is_no_gross_hard_cap_and_no_min():
    result, detail = classify_margins(DECLINE_60_36, RISING, RISING)  # weak gross (36), perfect profit leg (100)
    assert result.score == 68 and detail["binding"] == "gross"
    assert result.score > assess_margin_series(DECLINE_60_36).score  # the old min() would have given 36


def test_operating_margin_stays_inside_the_profit_leg_as_the_net_margin_fallback():
    one_off_net = [20, 20, 20, 20, 20, 20, 20, 20, 20, 12]  # net margin falls; operating stays flat
    result, detail = classify_margins(STEADY, STEADY, one_off_net)
    assert detail["profit_leg"] == "operating"
    assert result.score == 88


def test_a_missing_input_drops_out():
    gross_only_profit, _ = classify_margins([], RISING, DIP_2Y)
    assert gross_only_profit.score == assess_margin_series(RISING).score  # no gross margin: max(N, O) alone
    assert classify_margins([20.0], RISING, DIP_2Y)[0].score == gross_only_profit.score  # one point is missing too
    no_operating, d1 = classify_margins(STEADY, [], RISING)
    no_net, d2 = classify_margins(STEADY, RISING, [])
    assert d1["profit_leg"] == "net" and d2["profit_leg"] == "operating"
    assert no_operating.score == no_net.score == 94


def test_net_and_operating_both_missing_makes_margins_insufficient():
    result, detail = classify_margins(RISING, [], [])
    assert result.pattern == "insufficient_data" and "gross" in detail["inputs"]


def test_loss_making_ceiling_caps_margins_when_neither_net_nor_operating_is_positive():
    losing = [10, 8, 6, 4, 2, 0, -2, -4, -6, -1.0]
    result, detail = classify_margins(RISING, losing, losing)
    assert detail["ceiling"] == pytest.approx(36.0) and result.score == 36  # the better latest value is -1: 40 x 0.9
    deep = [10, 8, 6, 4, 2, 0, -5, -10, -20, -60.0]
    assert classify_margins(RISING, deep, deep)[0].score == 0
    # one positive leg lifts the cap: a profitable operating margin makes the ceiling irrelevant
    result, detail = classify_margins(RISING, RISING, losing)
    assert "ceiling" not in detail and result.score == 100


def test_the_utility_carveout_lifts_a_declining_series_to_60_before_the_blend():
    plain, _ = classify_margins(DECLINE_60_36, DECLINE_60_36, DECLINE_60_36)
    carved, detail = classify_margins(DECLINE_60_36, DECLINE_60_36, DECLINE_60_36, carveout=True)
    assert plain.score == 36 and carved.score == 60
    assert classify_margins(STEADY, STEADY, STEADY, carveout=True)[0].score == 88  # a flat series is untouched
    assert detail["inputs"]["gross"]["pattern"].startswith("decline")


def test_the_detail_fields_for_the_display():
    result, detail = anchor("POOL", ttm=False)
    assert set(detail["inputs"]) == {"gross", "operating", "net"}
    assert set(detail["legs"]) == {"gross", "profit"}
    assert detail["binding"] in ("gross", "net", "operating") and detail["profit_leg"] in ("net", "operating")
    assert result.pattern in {"uptrend", "flat", "decline", "uptrend_dips", "flat_dips", "decline_dips"}
