"""The neutral Step 1 engine (scoring/step1_engine.py; docs/specs/financials.md, "The engine"). The synthetic shapes are the ones of the
design's ordering suite; several scores are pinned to the figures the design records for them."""

import pytest

from scoring.step1_engine import (
    CEILING_AT_ZERO,
    ENGINE_PATTERNS,
    assess_series,
    assess_series_detail,
)

N = 11


def dollar(values):
    return assess_series(values, "dollar")


def ratio(values):
    return assess_series(values, "ratio")


def grower(dips=(), growth=0.08, drop=0.15, n=N, length=1):
    """100 growing `growth` a year; each index in `dips` is a fall of `drop` from the previous level that stays down `length` years,
    then returns to the growth path."""
    path = [100 * (1 + growth) ** t for t in range(n)]
    values = list(path)
    for start in dips:
        for t in range(start, min(start + length, n)):
            values[t] = path[start - 1] * (1 - drop)
    return values


def decline(rate, n=N):
    return [100 * (1 - rate) ** t for t in range(n)]


FLAT = [100.0] * N
ZIGZAGS = (
    [100 if t % 2 == 0 else 85 for t in range(N)],
    [100 if t % 2 == 0 else 70 for t in range(N)],
    [(100 - 2 * t) if t % 2 == 0 else (100 - 2 * t) * 0.7 for t in range(N)],
)


# --- contract ---------------------------------------------------------------------------------------------------------------------


def test_labels_are_the_six_shapes_plus_insufficient_data():
    assert set(ENGINE_PATTERNS) == {
        "uptrend", "uptrend_dips", "flat", "flat_dips", "decline", "decline_dips", "insufficient_data",
    }
    seen = {dollar(v).pattern for v in (grower(), grower((3, 6)), FLAT, ZIGZAGS[0], decline(0.12), decline(0.12)[:5] + [60, 55, 58, 40, 41, 30])}
    assert seen <= set(ENGINE_PATTERNS)
    assert {"uptrend", "uptrend_dips", "flat", "flat_dips", "decline"} <= seen


def test_fewer_than_two_points_is_insufficient_data_for_both_kinds():
    for kind in ("dollar", "ratio"):
        assert assess_series([], kind) == ("insufficient_data", 0)
        assert assess_series([5.0], kind) == ("insufficient_data", 0)


def test_a_dollar_series_with_a_zero_median_size_is_insufficient_data():
    assert dollar([0, 0, 0, 0, 0, 0, 300]) == ("insufficient_data", 0)
    assert dollar([0, 0, 0]) == ("insufficient_data", 0)
    assert ratio([0, 0, 0]).pattern == "flat"  # a ratio series needs no size


def test_the_kind_is_always_passed_in_and_validated():
    with pytest.raises(ValueError):
        assess_series([1, 2, 3], "percent")


def test_two_points_are_scored_as_they_are():
    assert dollar([100, 110]).pattern == "uptrend"
    assert dollar([110, 100]).pattern.startswith("decline")


# --- DOLLAR scale invariance --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("factor", [1e-9, 0.001, 0.5, 3.7, 1e3, 1e9])
@pytest.mark.parametrize(
    "values",
    [grower(), grower((2, 5, 8)), FLAT, decline(0.06), ZIGZAGS[1], [50, 55, 60, 65, -20, 75, 80, 85, 90, 95], [-5, -3, 2, 6, 9, 14, 20]],
)
def test_dollar_scores_do_not_change_when_the_series_is_multiplied_by_a_positive_constant(values, factor):
    assert dollar([v * factor for v in values]) == dollar(values)


def test_ratio_series_are_in_points_not_scale_invariant():
    wobble = [20, 20, 15, 20, 20, 20, 20, 20, 20, 20, 20]  # a 5-point fall...
    assert ratio(wobble).pattern.endswith("_dips")
    assert ratio([v / 100 for v in wobble]).pattern == "flat"  # ...is a rounding error at a hundredth of the size


# --- the dollar ordering suite ------------------------------------------------------------------------------------------------------


def test_clean_flat_and_declining_shapes_match_the_design():
    assert dollar(grower()) == ("uptrend", 100)
    assert dollar(FLAT) == ("flat", 68)
    assert dollar(decline(0.03)) == ("decline", 60)
    assert dollar(decline(0.06)) == ("decline", 52)
    assert dollar(decline(0.12)) == ("decline", 35)


def test_more_dips_score_strictly_lower_at_every_growth_rate():
    for growth in (0.03, 0.05, 0.08, 0.12, 0.20):
        scores = [dollar(grower(dips, growth)).score for dips in ((), (3,), (3, 6), (2, 5, 8), (2, 4, 6, 8))]
        assert all(a > b for a, b in zip(scores, scores[1:])), (growth, scores)


def test_a_grower_with_one_to_three_dips_stays_above_flat_when_growth_is_five_percent_or_more():
    for growth in (0.05, 0.08, 0.12, 0.20):
        for dips in ((3,), (3, 6), (2, 5, 8)):
            assert dollar(grower(dips, growth)).score > dollar(FLAT).score, (growth, dips)


def test_design_figures_for_the_grower_with_dips():
    assert [dollar(grower(d)).score for d in ((), (3,), (3, 6), (2, 5, 8), (2, 4, 6, 8))] == [100, 96, 89, 80, 72]


def test_ordering_flat_above_slow_above_moderate_above_steep_decline_above_every_zigzag():
    flat, slow, moderate, steep = (dollar(v).score for v in (FLAT, decline(0.03), decline(0.06), decline(0.12)))
    assert flat > slow > moderate > steep
    for zigzag in ZIGZAGS:
        assert dollar(zigzag).score < steep


def test_zigzag_design_figures():
    assert [dollar(z).score for z in ZIGZAGS[:2]] == [32, 15]


def test_the_dip_penalty_never_rises_with_dip_depth():
    scores = [dollar(grower((5,), drop=d / 100)).score for d in range(0, 31)]
    assert all(a >= b for a, b in zip(scores, scores[1:])), scores
    assert scores[0] == 100 and scores[-1] < scores[0]


def test_a_longer_dip_scores_strictly_lower():
    scores = [dollar(grower((4,), length=k)).score for k in (1, 2, 3)]
    assert scores == [96, 92, 87]


def test_a_dip_still_open_at_the_end_scores_below_the_same_dip_recovered():
    recovered, open_at_the_end = dollar(grower((8,))), dollar(grower((N - 1,)))
    assert (recovered.score, open_at_the_end.score) == (96, 86)
    assert dollar(grower((N - 3,), length=3)).score == 76  # a 3-year dip open at the end


def test_a_one_year_fall_swept_in_tenth_of_a_percent_steps_never_jumps():
    path = [100 * 1.08**t for t in range(N)]
    previous = None
    for tenth in range(0, 600):
        values = [v * (1 - tenth / 1000) if t == 5 else v for t, v in enumerate(path)]
        score = assess_series(values, "dollar")
        raw = assess_series_detail(values, "dollar")
        assert raw.burden is not None
        if previous is not None:
            assert abs(raw.burden - previous) < 0.1  # no cliff: the burden is continuous in the size of the fall
        previous = raw.burden
        assert score.score <= 100


def test_a_negative_year_in_a_grower_is_just_one_dip():
    result = dollar([50, 55, 60, 65, 70, -20, 75, 80, 85, 90, 95])
    assert result == ("uptrend_dips", 86)


# --- spike year -------------------------------------------------------------------------------------------------------------------


def test_a_flat_series_with_one_spike_year_scores_above_a_steady_decline_and_never_above_the_same_series_without_it():
    spike = FLAT[:5] + [175.0] + FLAT[6:]
    assert dollar(spike) == ("flat_dips", 62)
    assert dollar(spike).score > dollar(decline(0.12)).score
    assert dollar(spike).score <= dollar(FLAT).score


def test_a_spike_followed_by_decline_scores_no_higher_than_the_same_series_with_the_spike_replaced_by_the_flat_level():
    after = [100 * 0.94**k for k in range(1, 6)]
    with_spike = dollar(FLAT[:5] + [175.0] + after)
    spike_replaced = dollar(FLAT[:5] + [100.0] + after)
    assert with_spike.score == 25
    assert with_spike.score <= spike_replaced.score
    assert with_spike.score <= dollar(FLAT[:5] + [175.0] + FLAT[6:]).score


# --- RATIO: points, the flat score, the positivity ceiling ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", [5, 20, 40])
def test_a_flat_positive_margin_scores_88_at_any_level(level):
    assert ratio([level + 0.3 * (-1) ** t for t in range(N)]) == ("flat", 88)
    assert ratio([level] * N) == ("flat", 88)


def test_ratio_design_figures():
    assert ratio([15 + 0.8 * t for t in range(N)]) == ("uptrend", 98)
    assert ratio([20 - 0.6 * t for t in range(N)]) == ("decline", 76)
    assert ratio([20 - 1.2 * t for t in range(N)]) == ("decline", 65)
    assert ratio([20 if t % 2 == 0 else 15 for t in range(N)]).score == 54
    assert ratio([20 if t % 2 == 0 else 10 for t in range(N)]).score == 31


def test_ratio_flat_above_slow_above_moderate_above_steep_decline_above_the_zigzags():
    flat, slow, moderate, steep = (ratio([20 - r * t for t in range(N)]).score for r in (0, 0.3, 0.6, 1.2))
    assert flat > slow > moderate > steep
    for gap in (5, 10):
        assert ratio([20 if t % 2 == 0 else 20 - gap for t in range(N)]).score < steep


def test_ratio_more_dips_score_strictly_lower():
    def margin_grower(dips):
        return [15 + 0.8 * t - (5 if t in dips else 0) for t in range(N)]

    scores = [ratio(margin_grower(d)).score for d in ((), (3,), (3, 6), (2, 5, 8), (2, 4, 6, 8))]
    assert all(a > b for a, b in zip(scores, scores[1:])), scores


def test_the_positivity_ceiling_caps_a_series_whose_latest_value_is_at_or_below_zero():
    thin = [3.0 + 0.1 * (-1) ** t for t in range(10)]
    swept = {v: ratio(thin + [v]).score for v in (3.0, 1.0, 0.3, 0.01, 0.0, -0.5, -1, -2, -4, -6, -8, -10, -15)}
    ceilings = {0.0: 40, -0.5: 38, -1: 36, -2: 32, -4: 24, -6: 16, -8: 8, -10: 0, -15: 0}
    for value, ceiling in ceilings.items():
        assert swept[value] <= ceiling, (value, swept[value])
        assert assess_series_detail(thin + [value], "ratio").ceiling == pytest.approx(ceiling)
    assert swept[0.01] > 40 and assess_series_detail(thin + [0.01], "ratio").ceiling is None  # a positive latest value is never capped
    below_zero = [swept[v] for v in (0.0, -0.5, -1, -2, -4, -6, -8, -10)]
    assert all(a > b for a, b in zip(below_zero, below_zero[1:])), below_zero
    positive = [swept[v] for v in (3.0, 1.0, 0.3, 0.01)]
    assert all(a >= b for a, b in zip(positive, positive[1:])), positive
    assert CEILING_AT_ZERO == 40


def test_an_improving_but_still_negative_margin_scores_below_a_flat_positive_one():
    improving_negative = ratio([-12 + 11.8 * t / 10 for t in range(N)])
    assert improving_negative.pattern == "uptrend" and improving_negative.score == 39
    assert improving_negative.score < ratio([5.0] * N).score
    assert ratio([-12 + 12.3 * t / 10 for t in range(N)]).score == 100  # the same series ending just positive: the ceiling steps at zero


def test_earlier_negative_years_are_ordinary_dips_not_capped():
    assert ratio([20, 20, 20, -5, 20, 20, 20, 20, 20, 20, 20]) == ("flat_dips", 74)


def test_dollar_series_have_no_ceiling():
    assert assess_series_detail(grower(), "dollar").ceiling is None
    assert dollar([50, 40, 30, 20, 10, 5, -1]).score >= 0


# --- real series: the FCF / CFO expectations of the design ------------------------------------------------------------------------------

# Annual cash flow from operations and free cash flow, oldest -> latest completed fiscal year, millions (cached FMP statements).
REAL_SERIES = {
    "WMT": {
        "cfo": [31673, 28337, 27753, 25255, 36074, 24181, 28841, 35726, 36443, 41565],
        "fcf": [21054, 18286, 17409, 14550, 25810, 11075, 11984, 15120, 12660, 14923],
        "expected": {"cfo": 58, "fcf": 3},
    },
    "ABBV": {
        "cfo": [7041, 9960, 13427, 13324, 17588, 22777, 24943, 22839, 18806, 19030],
        "fcf": [6562, 9431, 12789, 12772, 16790, 21990, 24248, 22062, 17832, 17816],
        "expected": {"cfo": 82, "fcf": 80},
    },
    "TSCO": {
        "cfo": [650.7, 631.5, 694.4, 811.7, 1394.5, 1138.7, 1357.0, 1334.0, 1420.8, 1635.3],
        "fcf": [424.7, 381.0, 415.9, 594.3, 1100.5, 510.3, 583.6, 580.1, 636.8, 740.5],
        "expected": {"cfo": 93, "fcf": 74},
    },
}


@pytest.mark.parametrize("ticker", sorted(REAL_SERIES))
def test_real_cfo_and_fcf_series_score_as_the_design_records(ticker):
    series = REAL_SERIES[ticker]
    assert dollar(series["cfo"]).score == series["expected"]["cfo"]
    assert dollar(series["fcf"]).score == series["expected"]["fcf"]


def test_wmt_free_cash_flow_erodes_and_scores_near_zero_while_tsco_scores_well():
    assert dollar(REAL_SERIES["WMT"]["fcf"]).pattern == "decline_dips"
    assert dollar(REAL_SERIES["TSCO"]["cfo"]).pattern == "uptrend_dips"
