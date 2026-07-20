import pytest

from scoring.step1 import _classify_fcf, _classify_margins, score_step1

GROWING = [100, 110, 121, 133, 146]
DECLINING = [146, 133, 121, 110, 100]
STABLE_MARGINS = [40, 41, 40, 42, 43]
NET_MARGINS_STABLE = [20, 20.5, 20, 21, 21.5]
FCF_ALL_POSITIVE = [50, 60, 55, 70, 65, 80]


def test_strong_pass_all_growing():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
        fcf=FCF_ALL_POSITIVE,
    )
    assert result["score"] == 100
    assert result["verdict"] == "Strong Pass"
    assert result["components"]["cfo"]["score"] == 100
    assert result["components"]["fcf"]["score"] == 100
    assert result["weights"] == {"revenue": 0.25, "net_income": 0.25, "cfo": 0.25, "margins": 0.10, "fcf": 0.15}


def test_fail_all_declining():
    result = score_step1(
        revenue=DECLINING,
        net_income=DECLINING,
        operating_income=DECLINING,
        cfo=DECLINING,
        gross_margin=list(reversed(STABLE_MARGINS)),
        net_margin=list(reversed(NET_MARGINS_STABLE)),
        cfo_exempt=False,
    )
    assert result["score"] < 50
    assert result["verdict"] == "Fail"
    assert result["components"]["revenue"]["score"] == 0
    assert result["components"]["cfo"]["score"] == 0


def test_cfo_exemption_redistributes_weights():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=None,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=True,
    )
    # CFO's 25% + FCF's 15% (40% combined) redistribute evenly across the 3
    # remaining applicable metrics: 0.25 + 0.4/3, 0.25 + 0.4/3, 0.10 + 0.4/3.
    assert result["weights"]["cfo"] == 0.0
    assert result["weights"]["fcf"] == 0.0
    assert result["weights"]["revenue"] == pytest.approx(0.383333, abs=1e-5)
    assert result["weights"]["net_income"] == pytest.approx(0.383333, abs=1e-5)
    assert result["weights"]["margins"] == pytest.approx(0.233333, abs=1e-5)
    assert result["components"]["cfo"] is None
    assert result["components"]["fcf"] is None
    assert result["score"] == 100


def test_fcf_exemption_mirrors_cfo_exemption_ignores_fcf_data_entirely():
    # Even genuinely bad FCF data must have zero influence once CFO (and
    # therefore FCF) is exempt -- confirms the exemption branch ignores the
    # `fcf` argument entirely rather than only skipping it "usually".
    fcf_sustained_burn = [-10, -20, -30, -15, -25, -5]
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=None,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=True,
        fcf=fcf_sustained_burn,
    )
    assert result["components"]["fcf"] is None
    assert result["weights"]["fcf"] == 0.0
    assert result["score"] == 100


def test_net_income_backup_rule_uses_operating_income():
    # Net income is badly inconsistent (score <= 40) but operating income is clean.
    weak_net_income = [100, 60, 90, 55, 95]
    result = score_step1(
        revenue=GROWING,
        net_income=weak_net_income,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"]["used_operating_income_backup"] is True
    # min(80, max(weak_ni_score, 100)) == 80
    assert result["components"]["net_income"]["score"] == 80


def test_net_income_backup_not_used_when_score_above_threshold():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"]["used_operating_income_backup"] is False


def test_margins_single_big_dip_with_full_recovery_reads_as_stable():
    # One synchronized shock-and-recovery year (e.g. NVDA's FY2023) shouldn't
    # override an otherwise expanding trend just because it produces a high
    # stdev -- this is the exact case the old volatility check misclassified.
    gross = [55, 58, 60, 62, 50, 65, 68, 70, 72]
    net = [20, 22, 24, 26, 15, 28, 30, 32, 34]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "stable_or_expanding"
    assert score == 100


def test_margins_sustained_decline_not_forgiven_by_late_rebound():
    # A genuine 3-year decline (60 -> 58 -> 50 -> 42) followed by a strong
    # late rebound (-> 80) must not read as "stable_or_expanding" just
    # because the early-vs-late average nets positive.
    gross = [60, 58, 50, 42, 55, 70, 75, 78, 80]
    net = [25, 24, 20, 15, 22, 30, 33, 35, 37]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "gradually_compressing"
    assert score == 60


def test_margins_wildly_inconsistent_requires_real_oscillation_not_just_variance():
    # Repeated large swings in both directions netting no overall progress
    # -- genuine directionless chaos, not a single clean event.
    gross = [50, 70, 30, 70, 30, 70, 50]
    net = [20, 28, 12, 28, 12, 28, 20]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "wildly_inconsistent"
    assert score == 0


def test_score_clamped_to_valid_range():
    result = score_step1(
        revenue=GROWING,
        net_income=GROWING,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert 0 <= result["score"] <= 100


# --- FCF tiers -------------------------------------------------------------


def test_fcf_excellent_all_positive():
    pattern, score = _classify_fcf(FCF_ALL_POSITIVE)
    assert pattern == "consistently_positive"
    assert score == 100


def test_fcf_good_single_isolated_negative_year():
    # A one-off blip (index 2 only) surrounded by positive years on both
    # sides -- not a pattern, shouldn't score like a real problem.
    fcf = [50, 60, -5, 70, 65, 80]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "isolated_dip"
    assert score == 85


def test_fcf_fail_two_consecutive_negative_years_mid_history():
    fcf = [50, -10, -20, 70, 65, 80]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_fail_consecutive_run_at_the_very_end_including_ttm():
    # The 2-consecutive-negative pattern must be caught even when the run is
    # the most recent two periods (including TTM), not just mid-history.
    fcf = [50, 60, 70, -5, -10]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_fail_sustained_burn_throughout_entire_window():
    # RIVN-style: every single year is negative -- the strongest possible
    # case of the consecutive-run rule, not just a borderline 2-in-a-row.
    fcf = [-10, -20, -30, -15, -25, -5]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_marginal_scattered_non_consecutive_negative_years():
    # 2 negative years, but NOT adjacent to each other -- must be
    # distinguished from the 2-consecutive Fail case, landing at Marginal.
    fcf = [50, -10, 60, 70, -5, 80]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "scattered_negative_years"
    assert score == 60


def test_fcf_insufficient_data_below_two_points():
    pattern, score = _classify_fcf([50])
    assert pattern == "insufficient_data"
    assert score == 0
