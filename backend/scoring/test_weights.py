"""The weight set (scoring/weights.py) and what every scorer does with a non-default one.

Defaults reproduce today's numbers exactly (the other scoring tests pin that). Here: custom weight sets through every scorer,
every exempt-type derivation, and a weight of 0 (the component is not counted in the blend, but its data-gap gating and any
hard fail are untouched)."""

import pytest

from scoring.overall import StepSnapshot, compute_overall_assessment
from scoring.step1 import score_step1
from scoring.step2 import score_step2
from scoring.step4 import ARResult, RatioResult, score_step4
from scoring.step5 import score_step5_standard
from scoring.trend import TrendResult
from scoring.weights import (
    DEFAULT_WEIGHTS,
    OverallWeights,
    ScoreWeights,
    Step1Weights,
    Step2Weights,
    Step4Weights,
    Step5Weights,
    normalize,
    overall_fractions,
    step1_tables,
)

# --- the weight set -------------------------------------------------------------------------------------------------


def test_defaults_are_todays_weights():
    assert DEFAULT_WEIGHTS.overall == OverallWeights(30, 20, 20, 30)  # Financials, Growth, Profitability, Debt (2026-10-07)
    assert DEFAULT_WEIGHTS.step1 == Step1Weights(35, 20, 30, 10, 5)
    assert DEFAULT_WEIGHTS.step2 == Step2Weights(70, 30)
    assert DEFAULT_WEIGHTS.step4 == Step4Weights(25, 35, 20, 20)
    assert DEFAULT_WEIGHTS.step5 == Step5Weights(25, 45, 30)  # Current Ratio, Debt/EBITDA, Debt Servicing (2026-10-07)
    assert sum(vars(DEFAULT_WEIGHTS.step5).values()) == 100
    assert sum(vars(DEFAULT_WEIGHTS.overall).values()) == 100
    assert sum(vars(DEFAULT_WEIGHTS.step1).values()) == 100
    assert sum(vars(DEFAULT_WEIGHTS.step2).values()) == 100
    assert sum(vars(DEFAULT_WEIGHTS.step4).values()) == 100


def test_a_weight_set_is_immutable():
    with pytest.raises(AttributeError):
        DEFAULT_WEIGHTS.overall.debt = 99  # type: ignore[misc]


def test_normalize_shares_the_applicable_total_and_keeps_zero_as_zero():
    assert normalize({"a": 1, "b": 3, "c": 99}, ["a", "b"]) == {"a": 0.25, "b": 0.75}
    assert normalize({"a": 0, "b": 4}, ["a", "b"]) == {"a": 0.0, "b": 1.0}


def test_normalize_returns_none_when_nothing_applicable_has_weight():
    assert normalize({"a": 0, "b": 0, "c": 5}, ["a", "b"]) is None
    assert normalize({"a": 5}, []) is None


def test_overall_fractions_are_shares_of_100():
    fractions = overall_fractions(OverallWeights(25, 25, 25, 25))
    assert fractions == {"step1": 0.25, "step2": 0.25, "step4": 0.25, "step5": 0.25}
    assert overall_fractions(OverallWeights(40, 10, 20, 30)) == {"step1": 0.4, "step2": 0.1, "step4": 0.2, "step5": 0.3}


def test_old_overall_defaults_and_the_proportional_rescale_used_by_the_migration():
    from scoring.weights import OLD_DEFAULT_OVERALL, rescale_overall_to_100

    assert OLD_DEFAULT_OVERALL == {"financials": 24, "growth": 10, "profitability": 20, "debt": 15}
    assert sum(OLD_DEFAULT_OVERALL.values()) == 69
    # 24/10/20/15 of 69 scaled to 100 is 34.78 / 14.49 / 28.99 / 21.74 -> largest remainder: 35 / 14 / 29 / 22
    assert rescale_overall_to_100(OLD_DEFAULT_OVERALL) == {"financials": 35, "growth": 14, "profitability": 29, "debt": 22}
    custom = {"financials": 17, "growth": 30, "profitability": 11, "debt": 11}
    scaled = rescale_overall_to_100(custom)
    assert sum(scaled.values()) == 100 and all(abs(scaled[k] - custom[k] * 100 / 69) < 1 for k in custom)


def test_overall_bounds_no_longer_tie_a_step_to_the_moat_weight():
    from scoring.weights import BOUNDS

    assert BOUNDS["overall"] == {"financials": (10, 50), "growth": (5, 50), "profitability": (5, 50), "debt": (10, 50)}
    # The defaults sit inside the bounds, and the minimums add up to well under 100.
    for field, value in vars(DEFAULT_WEIGHTS.overall).items():
        assert BOUNDS["overall"][field][0] <= value <= BOUNDS["overall"][field][1]
    assert sum(low for low, _ in BOUNDS["overall"].values()) == 30


# --- Step 1 tables --------------------------------------------------------------------------------------------------


def test_step1_default_tables_are_todays():
    standard, cfo_exempt, bank = step1_tables(DEFAULT_WEIGHTS.step1)
    assert standard == {"revenue": 0.35, "net_income": 0.20, "cfo": 0.30, "margins": 0.10, "fcf": 0.05}
    assert cfo_exempt["revenue"] == pytest.approx(28 / 60) and cfo_exempt["net_income"] == pytest.approx(19 / 60)
    assert cfo_exempt["margins"] == pytest.approx(13 / 60)
    assert cfo_exempt["cfo"] == 0.0 and cfo_exempt["fcf"] == 0.0
    assert bank["revenue"] == pytest.approx(28 / 47) and bank["net_income"] == pytest.approx(19 / 47)
    assert bank["margins"] == 0.0


def test_step1_exempt_tables_derive_from_a_custom_base():
    standard, cfo_exempt, bank = step1_tables(Step1Weights(25, 15, 50, 5, 5))
    assert standard == {"revenue": 0.25, "net_income": 0.15, "cfo": 0.50, "margins": 0.05, "fcf": 0.05}
    # CFO 50 + FCF 5 = 55 split EQUALLY (18.33 each) across Revenue, Net Income and Margins.
    bonus = 0.55 / 3
    assert cfo_exempt["revenue"] == pytest.approx(0.25 + bonus)
    assert cfo_exempt["net_income"] == pytest.approx(0.15 + bonus)
    assert cfo_exempt["margins"] == pytest.approx(0.05 + bonus)
    assert sum(cfo_exempt.values()) == pytest.approx(1.0)
    # Bank: Margins dropped, its weight spread PROPORTIONALLY over Revenue and Net Income.
    assert bank["revenue"] == pytest.approx(cfo_exempt["revenue"] / (cfo_exempt["revenue"] + cfo_exempt["net_income"]))
    assert bank["margins"] == 0.0 and sum(bank.values()) == pytest.approx(1.0)


def test_step1_zero_margins_weight_gets_no_cfo_exempt_bonus():
    _, cfo_exempt, bank = step1_tables(Step1Weights(41, 24, 35, 0, 0))
    assert cfo_exempt["margins"] == 0.0
    assert cfo_exempt["revenue"] == pytest.approx(0.41 + 0.35 / 2)
    assert cfo_exempt["net_income"] == pytest.approx(0.24 + 0.35 / 2)
    assert bank["margins"] == 0.0 and sum(bank.values()) == pytest.approx(1.0)


def test_step1_tables_with_a_zero_total_are_none():
    assert step1_tables(Step1Weights(0, 0, 0, 0, 0)) == (None, None, None)
    standard, cfo_exempt, bank = step1_tables(Step1Weights(0, 0, 50, 0, 50))
    assert standard is not None and cfo_exempt is None and bank is None


# --- Step 1 scorer --------------------------------------------------------------------------------------------------

GROWING = [100, 110, 121, 133, 146, 161, 177, 195]
DECLINING = [195, 177, 161, 146, 133, 121, 110, 100]
MARGINS = [40, 41, 40, 42, 43, 44, 45, 46]
NET_MARGINS = [20, 20.5, 20, 21, 21.5, 22, 22.5, 23]
FCF_OK = [50, 60, 55, 70, 65, 80, 85, 90]


def _step1(weights=DEFAULT_WEIGHTS.step1, **overrides):
    args = dict(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=DECLINING,  # a different shape from the rest, so the components score differently
        gross_margin=MARGINS,
        net_margin=NET_MARGINS,
        cfo_exempt=False,
        fcf=FCF_OK,
    )
    args.update(overrides)
    return score_step1(**args, weights=weights)


def _blend(result, weights):
    return round(sum(result["components"][key]["score"] * weights[key] for key in weights if result["components"][key]))


def test_step1_custom_weights_blend_the_component_scores():
    default = _step1()
    custom = _step1(Step1Weights(20, 20, 20, 20, 20))
    assert custom["weights"] == {"revenue": 0.2, "net_income": 0.2, "cfo": 0.2, "margins": 0.2, "fcf": 0.2}
    assert custom["score"] == _blend(custom, custom["weights"])
    assert custom["score"] != default["score"]  # the CFO component really differs


def test_step1_cfo_exempt_uses_the_derived_table():
    weights = Step1Weights(25, 15, 50, 5, 5)
    result = _step1(weights, cfo=None, cfo_exempt=True, fcf=None)
    _, cfo_exempt, _ = step1_tables(weights)
    assert result["weights"] == cfo_exempt
    assert result["score"] == _blend(result, cfo_exempt)


def test_step1_bank_uses_the_derived_table():
    weights = Step1Weights(25, 15, 50, 5, 5)
    result = _step1(weights, cfo=None, cfo_exempt=True, margins_exempt=True, fcf=None)
    _, _, bank = step1_tables(weights)
    assert result["weights"] == bank
    assert result["components"]["margins"] is None


def test_step1_zero_weight_is_left_out_of_the_blend():
    with_cfo = _step1(Step1Weights(41, 24, 35, 0, 0))
    assert with_cfo["weights"]["margins"] == 0.0 and with_cfo["weights"]["fcf"] == 0.0
    # Margins and FCF were still classified (shown), they just do not move the score.
    assert with_cfo["components"]["margins"] is not None and with_cfo["components"]["fcf"] is not None
    assert with_cfo["score"] == _blend(with_cfo, with_cfo["weights"])


def test_step1_zero_weight_does_not_change_data_gap_gating():
    # FCF has one point: insufficient data. At weight 0 it is still a data gap: the step is null, exactly as at weight 5.
    thin_fcf = [50]
    assert _step1(fcf=thin_fcf)["verdict"] == "insufficient_data"
    assert _step1(Step1Weights(41, 24, 35, 0, 0), fcf=thin_fcf)["verdict"] == "insufficient_data"
    # Margins likewise: net and operating margin both missing (a single net-margin point, no operating margin series).
    assert _step1(Step1Weights(41, 24, 35, 0, 0), net_margin=[40])["verdict"] == "insufficient_data"


def test_step1_with_nothing_to_blend_is_insufficient_not_a_crash():
    result = _step1(Step1Weights(0, 0, 50, 0, 50), cfo=None, cfo_exempt=True, fcf=None)
    assert result["score"] is None and result["verdict"] == "insufficient_data"


# --- Step 2 ---------------------------------------------------------------------------------------------------------


def test_step2_custom_split():
    magnitude_only = score_step2(12.0, 40.0, Step2Weights(100, 0))
    agreement_only = score_step2(12.0, 5.0, Step2Weights(0, 100))
    assert magnitude_only.score == magnitude_only.magnitude_score == 85
    assert agreement_only.score == agreement_only.agreement_score == 100
    # 85*0.5 + 20*0.5 = 52.5 reads 52 -> the 70 floor for non-negative growth lifts it.
    blended = score_step2(12.0, 40.0, Step2Weights(50, 50))
    assert blended.magnitude_score == 85 and blended.agreement_score == 20 and blended.score == 70
    assert score_step2(12.0, 5.0, Step2Weights(50, 50)).score == round(85 * 0.5 + 100 * 0.5)


def test_step2_default_matches_the_old_constants():
    assert score_step2(12.0, 15.0) == score_step2(12.0, 15.0, Step2Weights(70, 30))
    assert score_step2(12.0, 15.0).score == round(85 * 0.70 + 60 * 0.30)


def test_step2_fail_gate_and_floor_read_no_weights():
    for weights in (Step2Weights(100, 0), Step2Weights(0, 100), Step2Weights(70, 30)):
        negative = score_step2(-3.0, 5.0, weights)
        assert negative.verdict == "Fail"
        weak = score_step2(1.0, 50.0, weights)  # growth >= 0: the score never reads below the 70 floor
        assert weak.verdict == "Pass" and weak.score >= 70


def test_step2_with_nothing_to_blend_is_none():
    assert score_step2(12.0, 15.0, Step2Weights(0, 0)) is None


# --- Step 4 ---------------------------------------------------------------------------------------------------------

ROE_100 = RatioResult("excellent", 100, False)
ROIC_60 = RatioResult("marginal", 60, False)
AR_40 = ARResult("outpacing_concerning", 40, False, None, None, 0, 0)
CCC_0 = TrendResult("sustained_upward", 0)


def test_step4_custom_weights():
    result = score_step4(ROE_100, AR_40, ROIC_60, CCC_0, weights=Step4Weights(25, 25, 25, 25))
    assert result["weights"] == {"roe": 0.25, "ar": 0.25, "roic": 0.25, "ccc": 0.25}
    assert result["score"] == round(100 * 0.25 + 40 * 0.25 + 60 * 0.25 + 0 * 0.25)


def test_step4_exempt_metrics_leave_the_rest_to_share_proportionally():
    weights = Step4Weights(15, 45, 20, 20)
    no_ccc = score_step4(ROE_100, AR_40, ROIC_60, None, weights=weights)  # no-inventory company
    assert no_ccc["weights"] == pytest.approx({"roe": 15 / 80, "ar": 20 / 80, "roic": 45 / 80})
    roe_only = score_step4(ROE_100, None, None, None, weights=weights)  # Bank / Insurance / Utility / REIT
    assert roe_only["weights"] == {"roe": 1.0}
    assert roe_only["score"] == 100


def test_step4_zero_weight_is_left_out_but_a_hard_fail_still_reads_fail():
    result = score_step4(ROE_100, AR_40, ROIC_60, CCC_0, weights=Step4Weights(42, 58, 0, 0))
    assert result["weights"]["ar"] == 0.0 and result["weights"]["ccc"] == 0.0
    assert result["score"] == round(100 * 0.42 + 60 * 0.58)
    failing_roic = RatioResult("fail", 0, True)
    failed = score_step4(ROE_100, AR_40, failing_roic, CCC_0, weights=Step4Weights(100, 0, 0, 0))
    assert failed["weights"]["roic"] == 0.0  # not counted in the blend...
    assert failed["hard_fail"] is True and failed["verdict"] == "Fail"  # ...but its hard fail is still a Fail


def test_step4_with_nothing_to_blend_is_insufficient_not_a_crash():
    # ROE alone applies (an exempt type) and ROE is weighted 0.
    result = score_step4(ROE_100, None, None, None, weights=Step4Weights(0, 50, 25, 25))
    assert result["score"] is None and result["verdict"] == "insufficient_data" and result["weights"] == {}


# --- Step 5 ---------------------------------------------------------------------------------------------------------


def _step5(weights=DEFAULT_WEIGHTS.step5, dsr=25.0, **overrides):
    # Current Ratio 2.5 -> 100, Debt/EBITDA 2.5 -> 70, DSR 25% -> 60 (approaching the limit).
    args = dict(
        current_ratio=2.5,
        adjusted_current_ratio=2.5,
        debt_to_ebitda=2.5,
        debt_servicing_pct=dsr,
        interest_coverage_ratio=10.0,
    )
    args.update(overrides)
    return score_step5_standard(**args, weights=weights)


def test_step5_default_is_25_45_30():
    result = _step5()
    assert result["weights"] == {"current_ratio": 0.25, "debt_to_ebitda": 0.45, "debt_servicing_ratio": 0.30}
    assert result["score"] == round(100 * 0.25 + 70 * 0.45 + 60 * 0.30)


def test_step5_relative_equal_weights_still_give_exact_thirds():
    result = _step5(Step5Weights(1, 1, 1))
    assert result["weights"] == {"current_ratio": 1 / 3, "debt_to_ebitda": 1 / 3, "debt_servicing_ratio": 1 / 3}


def test_step5_custom_weights():
    result = _step5(Step5Weights(60, 20, 20))
    assert result["weights"] == pytest.approx({"current_ratio": 0.6, "debt_to_ebitda": 0.2, "debt_servicing_ratio": 0.2})
    assert result["score"] == round(100 * 0.6 + 70 * 0.2 + 60 * 0.2)


def test_step5_excluded_dsr_redistributes_proportionally():
    result = _step5(Step5Weights(60, 20, 20), dsr=None, cfo_ttm=-5.0)
    assert result["weights"] == pytest.approx({"current_ratio": 0.75, "debt_to_ebitda": 0.25})
    assert result["score"] == round(100 * 0.75 + 70 * 0.25)
    # The defaults (25 / 45) keep their proportion: 5/14 and 9/14.
    assert _step5(dsr=None, cfo_ttm=-5.0)["weights"] == pytest.approx({"current_ratio": 25 / 70, "debt_to_ebitda": 45 / 70})


def test_step5_zero_weight_is_left_out_but_the_breach_is_still_named():
    result = _step5(Step5Weights(50, 50, 0), dsr=45.0)  # DSR past its Severe line, weighted 0: not in the blend, still a breach
    assert result["weights"]["debt_servicing_ratio"] == 0.0
    assert result["hard_fail"] is False and result["unrescued_breaches"] == ["debt_servicing_ratio"]
    # 100*.5 + 70*.5 = 85 reaches the Pass line; the unrescued breach makes it a caution pass, capped at 74.
    assert result["score"] == 74 and result["verdict"] == "Pass with caution"


def test_step5_with_nothing_to_blend_is_insufficient_not_a_crash():
    # DSR is excluded (negative CFO) and both remaining ratios are weighted 0.
    result = _step5(Step5Weights(0, 0, 100), dsr=None, cfo_ttm=-5.0)
    assert result["score"] is None and result["verdict"] == "insufficient_data" and result["weights"] == {}


# --- Overall --------------------------------------------------------------------------------------------------------


def _snap(key, score, verdict="Pass"):
    return StepSnapshot(key, key, False, score, verdict)


STEPS = [_snap("step1", 90), _snap("step2", 80), _snap("step4", 70), _snap("step5", 60)]


def test_overall_default_weights_blend():
    # 90*0.30 + 80*0.20 + 70*0.20 + 60*0.30 = 75 (Wide, multiplier 1.0)
    assert compute_overall_assessment(STEPS, moat="wide_moat").score == 75
    assert compute_overall_assessment(STEPS, moat="wide_moat", weights=DEFAULT_WEIGHTS.overall).score == 75


def test_overall_custom_weights():
    weights = OverallWeights(10, 5, 5, 80)  # sums to 100: Debt-heavy
    assert sum(vars(weights).values()) == 100
    result = compute_overall_assessment(STEPS, moat="wide_moat", weights=weights)
    assert result.score == round((90 * 10 + 80 * 5 + 70 * 5 + 60 * 80) / 100)
    assert result.breakdown[3].base_weight == 80 / 100


def test_overall_custom_weights_renormalize_across_the_steps_that_apply():
    weights = OverallWeights(15, 8, 16, 61)
    steps = [_snap("step1", 90), _snap("step2", 80), _snap("step4", 70), StepSnapshot("step5", "step5", False, None, "not_supported")]
    result = compute_overall_assessment(steps, moat="wide_moat", weights=weights)
    assert result.score == round((90 * 15 + 80 * 8 + 70 * 16) / (15 + 8 + 16))
    assert result.breakdown[3].effective_weight is None
    assert sum(entry.effective_weight for entry in result.breakdown[:3]) == pytest.approx(1.0)


def test_the_moat_multiplier_is_independent_of_the_step_weights():
    # Whatever the split of the four, a perfect Steps score is 100 and a No moat multiplier scales it to exactly 70.
    perfect = [_snap("step1", 100, "Strong Pass"), _snap("step2", 100, "Strong Pass"), _snap("step4", 100, "Strong Pass"), _snap("step5", 100, "Strong Pass")]
    for weights in (OverallWeights(50, 5, 5, 40), OverallWeights(10, 50, 30, 10), OverallWeights(25, 25, 25, 25)):
        assert compute_overall_assessment(perfect, moat="no_moat", weights=weights).score == 70
        assert compute_overall_assessment(perfect, moat="narrow_moat", weights=weights).score == 85
        assert compute_overall_assessment(perfect, moat="wide_moat", weights=weights).score == 100


def test_a_whole_score_weights_object_can_be_built_and_shared():
    weights = ScoreWeights(
        overall=OverallWeights(25, 25, 25, 25),
        step1=Step1Weights(20, 20, 20, 20, 20),
        step2=Step2Weights(50, 50),
        step4=Step4Weights(25, 25, 25, 25),
        step5=Step5Weights(25, 45, 30),
    )
    assert weights.step5.debt_servicing == 30


# --- Step 5 bounds, ordering and the no-hard-fail guarantee (2026-10-07) -------------------------------------------------


def _valid_step5_sets():
    """Every whole-number Step 5 set the Settings page accepts: inside the bounds, adding up to 100, strictly ordered."""
    from scoring.weights import BOUNDS

    bounds = BOUNDS["step5"]
    for debt_to_ebitda in range(bounds["debt_to_ebitda"][0], bounds["debt_to_ebitda"][1] + 1):
        for debt_servicing in range(bounds["debt_servicing"][0], bounds["debt_servicing"][1] + 1):
            current_ratio = 100 - debt_to_ebitda - debt_servicing
            if bounds["current_ratio"][0] <= current_ratio <= bounds["current_ratio"][1] and debt_to_ebitda > debt_servicing > current_ratio:
                yield Step5Weights(current_ratio, debt_to_ebitda, debt_servicing)


def test_step5_bounds_and_ordering_are_the_owners_numbers():
    from scoring.weights import BOUNDS, ORDERINGS

    assert BOUNDS["step5"] == {"current_ratio": (15, 30), "debt_to_ebitda": (35, 60), "debt_servicing": (15, 30)}
    assert ORDERINGS == {"step5": ("debt_to_ebitda", "debt_servicing", "current_ratio")}


def test_the_default_step5_set_and_the_lowest_usable_set_are_valid():
    from scoring.weights import ScoreWeights, validate_weights

    assert validate_weights(DEFAULT_WEIGHTS) == []
    sets = list(_valid_step5_sets())
    assert Step5Weights(29, 41, 30) in sets  # the sum of 100 and the 30 caps make 41 the lowest Debt/EBITDA weight in use
    assert min(w.debt_to_ebitda for w in sets) == 41 and max(w.debt_to_ebitda for w in sets) == 60
    for weights in sets:
        candidate = ScoreWeights(DEFAULT_WEIGHTS.overall, DEFAULT_WEIGHTS.step1, DEFAULT_WEIGHTS.step2, DEFAULT_WEIGHTS.step4, weights)
        assert validate_weights(candidate) == []


@pytest.mark.parametrize(
    "step5, message",
    [
        (Step5Weights(30, 34, 36), "Debt: Debt/EBITDA must be between 35 and 60."),
        (Step5Weights(15, 54, 31), "Debt: Debt Servicing Ratio must be between 15 and 30."),
        (Step5Weights(31, 40, 29), "Debt: Current Ratio must be between 15 and 30."),
        (Step5Weights(33, 33, 34), "Debt: Debt/EBITDA must be between 35 and 60."),  # the pre-2026-10-07 default
    ],
)
def test_step5_bound_violations_are_named(step5, message):
    from scoring.weights import ScoreWeights, validate_weights

    candidate = ScoreWeights(DEFAULT_WEIGHTS.overall, DEFAULT_WEIGHTS.step1, DEFAULT_WEIGHTS.step2, DEFAULT_WEIGHTS.step4, step5)
    assert message in validate_weights(candidate)


@pytest.mark.parametrize("step5", [Step5Weights(30, 40, 30), Step5Weights(25, 35, 40), Step5Weights(30, 30, 40)])
def test_step5_ordering_is_strict_and_named(step5):
    from scoring.weights import ScoreWeights, validate_group, validate_weights, as_dict

    messages = validate_group("step5", as_dict(step5))
    order = [m for m in messages if "must keep this order" in m]
    assert order == [
        "Debt weights must keep this order, each strictly larger than the next: Debt/EBITDA > Debt Servicing Ratio > Current Ratio."
    ]
    candidate = ScoreWeights(DEFAULT_WEIGHTS.overall, DEFAULT_WEIGHTS.step1, DEFAULT_WEIGHTS.step2, DEFAULT_WEIGHTS.step4, step5)
    assert order[0] in validate_weights(candidate)


def test_step5_ordering_is_not_checked_on_a_set_that_is_not_whole_numbers_and_other_groups_have_none():
    from scoring.weights import validate_group

    assert validate_group("step2", {"magnitude": 50, "agreement": 50}) == []
    assert any("whole number" in m for m in validate_group("step5", {"current_ratio": 25.5, "debt_to_ebitda": 45, "debt_servicing": 30}))


def test_no_valid_step5_set_lets_negative_ebitda_or_a_debt_ebitda_breach_reach_70():
    # With no hard fail the weights alone must keep these under the Pass line, for EVERY set the Settings page can save,
    # with the other ratios as good as they can be.
    sets = list(_valid_step5_sets())
    assert sets
    for weights in sets:
        negative_ebitda = score_step5_standard(
            current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=None, debt_servicing_pct=0.0,
            interest_coverage_ratio=None, ebitda_ttm=-1.0, weights=weights,
        )
        assert negative_ebitda["score"] < 70 and negative_ebitda["verdict"] == "Fail", weights
        # The same with Debt Servicing excluded (negative CFO): Current Ratio and Debt/EBITDA split the weight.
        excluded = score_step5_standard(
            current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=None, debt_servicing_pct=None,
            interest_coverage_ratio=None, ebitda_ttm=-1.0, cfo_ttm=-1.0, weights=weights,
        )
        assert excluded["score"] < 70 and excluded["verdict"] == "Fail", weights
        # Debt/EBITDA just over its limit with nothing to rescue it (0 points), the other two perfect.
        breach = score_step5_standard(
            current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=3.01, debt_servicing_pct=0.0,
            interest_coverage_ratio=None, weights=weights,
        )
        assert breach["ratios"]["debt_to_ebitda"]["points"] == 0
        assert breach["score"] < 70 and breach["verdict"] == "Fail", weights
        # A severe Debt/EBITDA breach (4.01x, 15 points) is also kept under the line.
        severe = score_step5_standard(
            current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=4.01, debt_servicing_pct=0.0,
            interest_coverage_ratio=None, weights=weights,
        )
        assert severe["score"] < 70 and severe["verdict"] == "Fail", weights


def test_the_old_33_33_34_default_would_have_let_a_severe_breach_through():
    # Why the bounds exist: at equal thirds a severe Debt/EBITDA breach with two perfect ratios blends to 71 and passes.
    result = score_step5_standard(
        current_ratio=3.0, adjusted_current_ratio=3.0, debt_to_ebitda=4.62, debt_servicing_pct=0.0,
        interest_coverage_ratio=None, weights=Step5Weights(33, 33, 34),
    )
    assert result["score"] >= 70
