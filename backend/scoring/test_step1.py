"""Step 1 wrappers around the neutral engine (scoring/step1.py): the blend and weight tables, the CFO/FCF and Margins exemptions, the
positivity gate, the Net Income Operating Income backup (completed fiscal years only), the Margins combination min(G, max(N, O)) and
its carve-out, the thin-history cap. The engine itself is pinned in test_step1_engine.py."""

import inspect

import pytest

import scoring.step1 as step1_module
from scoring.step1 import (
    NET_INCOME_BACKUP_CAP,
    NET_INCOME_BACKUP_THRESHOLD,
    _classify_fcf,
    _classify_margins,
    _classify_positive_trend,
    score_step1,
)
from scoring.step1_engine import assess_series
from scoring.trend import TrendResult

N = 10
GROWING = [100 * 1.08**t for t in range(N)]  # uptrend 100
SHORT_GROWING = GROWING[:5]
DECLINING = [100 * 0.88**t for t in range(N)]  # decline 35
UP_MARGIN = [20 + 1.2 * t for t in range(N)]  # uptrend 100
FLAT_MARGIN = [20.0] * N  # flat 88
FALLING_MARGIN = [40 - 3.0 * t for t in range(N)]  # decline 30, ends positive
FLAT_SCORE = 88
FCF_UP = [50 * 1.08**t for t in range(N)]


def strong(**overrides):
    args = dict(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=UP_MARGIN,
        operating_margin=UP_MARGIN,
        net_margin=UP_MARGIN,
        cfo_exempt=False,
        fcf=GROWING,
    )
    args.update(overrides)
    return score_step1(**args)


def ratio_score(values):
    return assess_series(values, "ratio").score


# --- the blend, weights and exemptions ----------------------------------------------------------------------------------------------


def test_strong_pass_all_growing():
    result = strong()
    assert (result["score"], result["verdict"]) == (100, "Strong Pass")
    assert result["components"]["cfo"] == {"score": 100, "pattern": "uptrend"}
    assert result["components"]["fcf"] == {"score": 100, "pattern": "uptrend"}
    assert result["weights"] == {"revenue": 0.35, "net_income": 0.20, "cfo": 0.30, "margins": 0.10, "fcf": 0.05}


def test_fail_all_declining():
    result = strong(
        revenue=DECLINING, net_income=DECLINING, operating_income=DECLINING, cfo=DECLINING, fcf=DECLINING,
        gross_margin=FALLING_MARGIN, operating_margin=FALLING_MARGIN, net_margin=FALLING_MARGIN,
    )
    assert result["verdict"] == "Fail" and result["score"] < 50
    assert result["components"]["revenue"] == {"score": 35, "pattern": "decline"}
    assert result["components"]["cfo"] == {"score": 35, "pattern": "decline"}
    assert result["components"]["margins"]["pattern"] == "decline" and result["components"]["margins"]["score"] == 30


def test_cfo_exemption_redistributes_weights():
    result = strong(cfo=None, cfo_exempt=True, fcf=None)
    # CFO's 30% + FCF's 5% redistribute evenly across the 3 remaining metrics.
    assert result["weights"]["cfo"] == 0.0 and result["weights"]["fcf"] == 0.0
    assert result["weights"]["revenue"] == pytest.approx(0.466667, abs=1e-5)
    assert result["weights"]["net_income"] == pytest.approx(0.316667, abs=1e-5)
    assert result["weights"]["margins"] == pytest.approx(0.216667, abs=1e-5)
    assert result["components"]["cfo"] is None and result["components"]["fcf"] is None
    assert result["score"] == 100


def test_margins_exemption_redistributes_weights_proportionally_for_banks():
    result = strong(cfo=None, cfo_exempt=True, fcf=None, margins_exempt=True)
    assert result["weights"]["margins"] == 0.0
    assert result["weights"]["revenue"] == pytest.approx(28 / 47, abs=1e-5)
    assert result["weights"]["net_income"] == pytest.approx(19 / 47, abs=1e-5)
    assert result["components"]["margins"] is None
    assert result["score"] == 100


def test_margins_exemption_ignores_margin_data_entirely():
    bad = [80, 60, 40, 20, 5, -5]
    exempt = strong(cfo=None, cfo_exempt=True, fcf=None, margins_exempt=True, gross_margin=bad, operating_margin=bad, net_margin=bad)
    assert exempt["score"] == 100 and exempt["components"]["margins"] is None
    # an exempt Bank with no margin data at all is not a data gap
    assert strong(cfo=None, cfo_exempt=True, fcf=None, margins_exempt=True, gross_margin=[], operating_margin=[], net_margin=[])["score"] == 100


def test_non_bank_cfo_exempt_types_keep_margins_scored():
    result = strong(cfo=None, cfo_exempt=True, fcf=None, gross_margin=FALLING_MARGIN, operating_margin=FALLING_MARGIN, net_margin=FALLING_MARGIN)
    assert result["components"]["margins"] is not None and result["components"]["margins"]["score"] == 30
    assert result["weights"]["margins"] == pytest.approx(0.216667, abs=1e-5)


def test_fcf_exemption_mirrors_cfo_exemption_ignores_fcf_data_entirely():
    with_junk = strong(cfo=None, cfo_exempt=True, fcf=[-5, -9])
    assert with_junk["components"]["fcf"] is None and with_junk["score"] == 100


def test_score_clamped_to_valid_range_and_rounded_once():
    result = strong()
    assert 0 <= result["score"] <= 100
    assert isinstance(result["score"], int)


def test_the_scorer_has_no_ttm_parameter():
    assert not [name for name in inspect.signature(score_step1).parameters if "ttm" in name]


# --- positivity gate (Revenue, Net Income, CFO; not FCF) ---------------------------------------------------------------------------------


def test_positive_trend_gate_growing_series_unaffected():
    assert _classify_positive_trend(GROWING) == ("uptrend", 100)


def test_the_latest_completed_year_at_or_below_zero_is_not_yet_positive_whatever_the_shape():
    pattern, score = _classify_positive_trend([10, 20, 30, 40, 50, 60, 70, 80, 90, -5])
    assert (pattern, score) == ("not_yet_positive", 0)  # no revenue scale: a flat 0
    assert _classify_positive_trend([10, 20, 30, -1, 40, 50, 60, 70, 80, 90]).pattern == "uptrend_dips"  # an earlier negative is a dip


def test_net_income_never_profitable_stays_not_yet_positive_even_while_recovering():
    sym = [-104.361, -109.521, -122.314, -78.997, -23.866, -13.490, -16.937, -4.965]
    revenue = [500.0, 520.0, 540.0, 560.0, 580.0, 600.0, 620.0, 640.0]
    result = _classify_positive_trend(sym, revenue)
    assert result.pattern == "not_yet_positive" and 0 < result.score <= 15


def test_not_yet_positive_graduated_scale_boundaries():
    scale = [100] * N
    values = [10] * (N - 1)
    assert _classify_positive_trend(values + [-0.1], scale).score == 15  # one dollar from breakeven
    assert _classify_positive_trend(values + [-10.0], scale).score == 8  # halfway to -20%
    assert _classify_positive_trend(values + [-20.0], scale) == ("not_yet_positive", 0)
    assert _classify_positive_trend(values + [-50.0], scale) == ("not_yet_positive", 0)
    assert _classify_positive_trend(values + [-5.0], [100] * (N - 1) + [0]) == ("not_yet_positive", 0)  # no usable scale


def test_free_cash_flow_is_not_positivity_gated_a_negative_value_is_just_a_dip():
    fcf = [50, 55, 60, 65, 70, 75, 80, 85, 90, -10]
    result = _classify_fcf(fcf)
    assert result.pattern != "not_yet_positive"
    assert result == assess_series(fcf, "dollar")
    assert _classify_positive_trend(fcf).pattern == "not_yet_positive"  # CFO, for contrast, is gated


def test_an_insufficient_data_series_is_a_gap_not_a_scored_zero():
    assert strong(fcf=[50])["verdict"] == "insufficient_data"
    assert strong(cfo=[50])["verdict"] == "insufficient_data"
    assert strong(revenue=[100])["verdict"] == "insufficient_data"


# --- Net Income Operating Income backup (completed fiscal years) --------------------------------------------------------------------------

WEAK_NI = [100, 140, 120, 150, 130, 170, 190, 150, 210, 185]  # a recent real dip (age 0); engine score 69 (<= 79)
REVENUE = [600, 650, 700, 750, 800, 850, 900, 950, 1000, 1050]
CLEAN_OI = [200 + 20.0 * t for t in range(N)]


def backup_case(oi=None, revenue=REVENUE, net_income=WEAK_NI, **latest):
    result = score_step1(
        revenue=revenue,
        net_income=net_income,
        operating_income=CLEAN_OI if oi is None else oi,
        cfo=GROWING,
        gross_margin=UP_MARGIN,
        operating_margin=UP_MARGIN,
        net_margin=UP_MARGIN,
        cfo_exempt=False,
        fcf=GROWING,
        **latest,
    )
    return result["components"]["net_income"]


def test_the_backup_lifts_to_the_cap_when_every_gate_passes_and_reports_the_measured_gates():
    ni = backup_case()
    assert ni["used_operating_income_backup"] is True
    assert (ni["score_before_backup"], ni["score"]) == (assess_series(WEAK_NI, "dollar").score, NET_INCOME_BACKUP_CAP)
    # latest fiscal year OI 380 on latest fiscal year revenue 1050
    assert ni["backup_gates"] == {
        "oi_margin_pct": 36.2,
        "min_oi_margin_pct": 5.0,
        "positive_periods": 5,
        "min_positive_periods": 4,
        "window": 5,
    }


def test_the_backup_is_not_used_when_the_net_income_score_is_above_the_threshold():
    assert strong()["components"]["net_income"]["used_operating_income_backup"] is False
    assert set(strong()["components"]["net_income"]) == {"score", "pattern", "used_operating_income_backup"}


def test_backup_margin_gate_exactly_5_percent_passes_and_just_below_blocks():
    assert backup_case(latest_revenue=1000, latest_operating_income=50)["used_operating_income_backup"] is True
    blocked = backup_case(latest_revenue=1000, latest_operating_income=49.99)
    assert blocked["used_operating_income_backup"] is False
    assert set(blocked) == {"score", "pattern", "used_operating_income_backup"}  # the display fields are absent when nothing was lifted


def test_backup_blocked_when_the_latest_operating_income_is_not_positive():
    oi = CLEAN_OI[:-1] + [-5.0]
    assert backup_case(oi)["used_operating_income_backup"] is False


def test_backup_positive_year_gate_4_of_5_passes_3_of_5_fails_and_only_the_last_5_count():
    base = [200, 220, 240, 260, 280]
    four = [-1.0] + base[1:]
    assert backup_case([100.0] * 5 + four)["used_operating_income_backup"] is True
    assert backup_case([100.0] * 5 + four)["backup_gates"]["positive_periods"] == 4
    three = [-1.0, -2.0] + base[2:]
    assert backup_case([100.0] * 5 + three)["used_operating_income_backup"] is False
    # an old loss outside the last 5 years is not looked at
    assert backup_case([-50.0] * 5 + base)["used_operating_income_backup"] is True


def test_backup_missing_latest_revenue_or_operating_income_fails_the_gate():
    assert backup_case(latest_revenue=None, latest_operating_income=380)["used_operating_income_backup"] is False
    assert backup_case(latest_revenue=1050, latest_operating_income=None)["used_operating_income_backup"] is False
    assert backup_case(latest_revenue=1050, latest_operating_income=380)["used_operating_income_backup"] is True


def test_backup_explicit_latest_values_override_the_series_tail():
    assert backup_case(latest_revenue=10000, latest_operating_income=380)["used_operating_income_backup"] is False  # 3.8%


def test_backup_flag_is_true_only_when_the_score_actually_changed():
    # OI is no better than Net Income: eligible and gated through, but nothing to lift.
    ni = backup_case(oi=WEAK_NI)
    assert ni["used_operating_income_backup"] is False


def test_backup_blocked_still_lets_insufficient_net_income_count_as_scored_when_oi_has_data():
    result = score_step1(
        revenue=GROWING, net_income=[10.0], operating_income=CLEAN_OI, cfo=GROWING, gross_margin=UP_MARGIN,
        operating_margin=UP_MARGIN, net_margin=UP_MARGIN, cfo_exempt=False, fcf=GROWING, latest_revenue=1000, latest_operating_income=10,
    )
    assert result["verdict"] != "insufficient_data"
    assert result["components"]["net_income"]["pattern"] == "insufficient_data"


def test_net_income_insufficient_and_operating_income_insufficient_is_a_data_gap():
    result = score_step1(
        revenue=GROWING, net_income=[10.0], operating_income=[5.0], cfo=GROWING, gross_margin=UP_MARGIN,
        operating_margin=UP_MARGIN, net_margin=UP_MARGIN, cfo_exempt=False, fcf=GROWING,
    )
    assert result["verdict"] == "insufficient_data"


def _with_forced_ni_score(monkeypatch, ni_score):
    real = step1_module._classify_positive_trend
    calls = {"n": 0}

    def fake(values, revenue_for_scale=None):
        calls["n"] += 1
        return TrendResult("flat_dips", ni_score) if calls["n"] == 2 else real(values, revenue_for_scale)  # the second call is Net Income

    monkeypatch.setattr(step1_module, "_classify_positive_trend", fake)
    return score_step1(
        revenue=GROWING, net_income=WEAK_NI, operating_income=CLEAN_OI, cfo=GROWING, gross_margin=UP_MARGIN,
        operating_margin=UP_MARGIN, net_margin=UP_MARGIN, cfo_exempt=False, fcf=GROWING,
    )["components"]["net_income"]


def test_backup_trigger_boundary_79_is_lifted_80_is_not_considered(monkeypatch):
    assert NET_INCOME_BACKUP_THRESHOLD == NET_INCOME_BACKUP_CAP - 1
    assert _with_forced_ni_score(monkeypatch, 79)["used_operating_income_backup"] is True
    monkeypatch.undo()
    assert _with_forced_ni_score(monkeypatch, 80)["used_operating_income_backup"] is False


def test_backup_needs_a_recent_dip_unless_net_income_is_insufficient():
    # a chronic decline with the dip 5+ years back and nothing since: the old recency helper sees no recent dip, so no rescue
    old_dip = [100, 60, 90, 100, 110, 120, 130, 140, 150, 160]
    ni = backup_case(net_income=old_dip)
    assert ni["used_operating_income_backup"] is False


# --- Margins: min(G, max(N, O)) -----------------------------------------------------------------------------------------------------

N_BAD = [5, -3, 4, -2, 3, -4, 2, -3, 2, -1, 1]  # a margin that falls through zero in most years and ends at 1
ONE_NEGATIVE_YEAR = [20, 20, 20, -5, 20, 20, 20, 20, 20, 20, 20]


def margins(g, o, n, carveout=False):
    return _classify_margins(g, o, n, carveout)


def test_margins_is_the_lower_of_gross_and_the_better_of_net_and_operating():
    for g, o, n in [
        (FLAT_MARGIN, UP_MARGIN, N_BAD),
        (FLAT_MARGIN, FALLING_MARGIN, UP_MARGIN),
        (UP_MARGIN, FLAT_MARGIN, ONE_NEGATIVE_YEAR),
        (FALLING_MARGIN, UP_MARGIN, UP_MARGIN),
        (UP_MARGIN, N_BAD, N_BAD),
    ]:
        gs, os_, ns = ratio_score(g), ratio_score(o), ratio_score(n)
        result, _ = margins(g, o, n)
        assert result.score == min(gs, max(ns, os_)), (gs, os_, ns)


def test_a_weak_gross_margin_binds_even_when_net_and_operating_are_healthy():
    result, detail = margins(FALLING_MARGIN, UP_MARGIN, UP_MARGIN)
    assert (result.score, result.pattern, detail["binding"]) == (30, "decline", "gross")


def test_operating_margin_stands_in_for_a_bad_net_margin_when_gross_is_healthy():
    result, detail = margins(FLAT_MARGIN, FLAT_MARGIN, N_BAD)
    assert result.score == FLAT_SCORE
    assert detail["inputs"]["net"]["score"] < FLAT_SCORE
    assert detail["binding"] == "gross"  # G 88 <= max(N, O) 88


def test_both_net_and_operating_bad_leaves_margins_low_whatever_gross_says():
    result, detail = margins(UP_MARGIN, N_BAD, N_BAD)
    assert result.score == ratio_score(N_BAD) < 50
    assert detail["binding"] in ("net", "operating")


def test_a_missing_input_drops_out():
    g, o, n = FLAT_MARGIN, UP_MARGIN, N_BAD
    gs, os_, ns = ratio_score(g), ratio_score(o), ratio_score(n)
    assert margins([], o, n)[0].score == max(os_, ns)  # no gross margin: max(N, O)
    assert margins([20.0], o, n)[0].score == max(os_, ns)  # one point is missing too
    assert margins(g, [], n)[0].score == min(gs, ns)  # no operating margin: min(G, N)
    assert margins(g, o, [])[0].score == min(gs, os_)  # no net margin: min(G, O)


def test_net_and_operating_both_missing_makes_margins_insufficient_whatever_gross_says():
    result, detail = margins(UP_MARGIN, [], [])
    assert result.pattern == "insufficient_data"
    assert "gross" in detail["inputs"]
    scored = strong(gross_margin=UP_MARGIN, operating_margin=[], net_margin=[])
    assert scored["verdict"] == "insufficient_data" and scored["score"] is None


def test_no_operating_margin_argument_is_a_missing_input_not_an_error():
    result = score_step1(
        revenue=GROWING, net_income=GROWING, operating_income=GROWING, cfo=GROWING, gross_margin=UP_MARGIN, net_margin=UP_MARGIN,
        cfo_exempt=False, fcf=GROWING,
    )
    assert result["components"]["margins"]["score"] == 100
    assert set(result["components"]["margins"]["inputs"]) == {"gross", "net"}


def test_the_positivity_ceiling_reaches_margins_a_loss_making_net_and_operating_cannot_lift_it():
    losing = [10, 8, 6, 4, 2, 0, -2, -4, -6, -8]
    result, _ = margins(UP_MARGIN, losing, losing)
    assert result.score <= 16  # ceiling at a latest -8 is 8, and the engine alone gives less than 40


def test_the_margins_component_exposes_its_inputs_and_the_deciding_one():
    component = strong(gross_margin=FALLING_MARGIN)["components"]["margins"]
    assert component["binding"] == "gross"
    assert component["inputs"]["gross"] == {"score": 30, "pattern": "decline"}
    assert set(component["inputs"]) == {"gross", "operating", "net"}


# --- carve-out (Insurance / REIT-Property-Developer / Utility) ---------------------------------------------------------------------------


def test_the_carveout_lifts_a_declining_margin_series_to_60_and_leaves_everything_else_alone():
    assert margins(FALLING_MARGIN, FALLING_MARGIN, FALLING_MARGIN)[0].score == 30
    with_carveout, _ = margins(FALLING_MARGIN, FALLING_MARGIN, FALLING_MARGIN, carveout=True)
    assert (with_carveout.score, with_carveout.pattern) == (60, "decline")
    # a healthy or flat series is never touched, and a score already above 60 is not lowered
    assert margins(FLAT_MARGIN, FLAT_MARGIN, FLAT_MARGIN, carveout=True)[0].score == FLAT_SCORE
    assert margins(UP_MARGIN, UP_MARGIN, UP_MARGIN, carveout=True)[0].score == 100


def test_the_carveout_is_per_series_before_the_combination():
    # G declines (lifted to 60), N and O flat 88: Margins = min(60, 88) = 60, not 30
    result, _ = margins(FALLING_MARGIN, FLAT_MARGIN, FLAT_MARGIN, carveout=True)
    assert result.score == 60


def test_the_carveout_acts_after_the_ceiling_and_can_lift_a_loss_making_decline_to_60():
    losing = [10, 8, 6, 4, 2, 0, -2, -4, -6, -8]
    assert margins(losing, losing, losing)[0].score < 20
    assert margins(losing, losing, losing, carveout=True)[0].score == 60  # known and accepted: wrappers are unchanged


def test_carveout_wires_through_score_step1():
    plain = strong(gross_margin=FALLING_MARGIN, operating_margin=FALLING_MARGIN, net_margin=FALLING_MARGIN)
    carved = strong(
        gross_margin=FALLING_MARGIN, operating_margin=FALLING_MARGIN, net_margin=FALLING_MARGIN, margins_severity_carveout=True
    )
    assert plain["components"]["margins"]["score"] == 30 and carved["components"]["margins"]["score"] == 60
    assert carved["score"] > plain["score"]


# --- thin-history cap on Strong Pass (H1) ------------------------------------------------------------------------------------------------


def test_thin_history_7_points_caps_a_would_be_100_at_90_and_reads_pass():
    result = strong(revenue=GROWING[:7])
    assert (result["score"], result["verdict"]) == (90, "Pass")


def test_history_of_8_points_is_not_capped():
    result = strong(revenue=GROWING[:8])
    assert (result["score"], result["verdict"]) == (100, "Strong Pass")


def test_cap_leaves_a_score_at_or_below_90_alone():
    weak = [100, 90, 80, 70, 60, 50, 40, 30]
    thin = strong(revenue=GROWING[:5], net_income=weak, operating_income=weak)
    long = strong(revenue=GROWING[:8], net_income=weak, operating_income=weak)
    assert thin["score"] == long["score"] <= 90


def test_the_count_is_the_revenue_series_not_the_other_series():
    result = strong(revenue=GROWING, cfo=GROWING[:5], fcf=GROWING[:5], net_income=GROWING[:5], operating_income=GROWING[:5])
    assert result["score"] == 100
