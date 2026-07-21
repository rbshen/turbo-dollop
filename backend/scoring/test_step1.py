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


def test_margins_sustained_decline_not_forgiven_by_partial_rebound():
    # A genuine 3-year decline (60 -> 58 -> 50 -> 42) followed by only a
    # partial rebound (-> 49, still well below the pre-decline 60) must not
    # read as "stable_or_expanding" -- the decline hasn't actually been
    # reversed, regardless of what the early-vs-late average nets to.
    gross = [60, 58, 50, 42, 45, 46, 47, 48, 49]
    net = [25, 24, 20, 15, 17, 18, 18, 19, 19]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "gradually_compressing"
    assert score == 60


def test_margins_sustained_decline_forgiven_once_durably_reversed():
    # Same shape as the case above, but the late rebound (-> 80) fully
    # reverses AND exceeds the pre-decline peak (60) -- confirmed via real
    # tickers (CRM, TJX, PG, STE, MSCI, ADBE, VRSN) that this must NOT stay
    # permanently capped just because a multi-year decline occurred
    # somewhere in a 10yr+TTM window (see CLAUDE.md's Step 1 deviations).
    gross = [60, 58, 50, 42, 55, 70, 75, 78, 80]
    net = [25, 24, 20, 15, 22, 30, 33, 35, 37]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "stable_or_expanding"
    assert score == 100


def test_margins_positive_average_direction_alone_is_not_enough_to_forgive():
    # Boundary case distinguishing this fix from a plain direction-sign
    # gate: the early-vs-late WINDOW AVERAGE direction is exactly flat
    # (0.0, passing the stable tolerance), but the single most recent
    # (TTM-equivalent) value is still well below the early-window average
    # -- i.e. the series is declining again at the tail end. Must stay
    # capped: a positive multi-year average alone doesn't mean "recovered".
    gross = [70, 70, 70, 40, 30, 20, 90, 70, 50]
    net = [25, 25, 25, 15, 12, 9, 32, 25, 18]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "gradually_compressing"
    assert score == 60


def test_margins_late_window_spike_does_not_forgive_an_otherwise_flat_series():
    # Mirrors LYV's real shape: gross margin flat at ~30% for the entire
    # history, then a single anomalous TTM-equivalent spike to 45. Net
    # margin is genuinely flat throughout (never triggers anything). The
    # raw direction reads positive purely because of that one late-window
    # outlier -- removing it (the same de-spike test used to find this
    # class of bug) flips direction negative, so this must NOT read as
    # "stable_or_expanding" just because of one anomalous point.
    gross = [30, 30, 30, 30, 30, 30, 30, 26, 45]
    net = [10, 10, 10, 10, 10, 10, 10, 10, 10]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "gradually_compressing"
    assert score == 60


def test_margins_sharp_decline_not_excused_by_unrelated_gross_recovery():
    # Regression guard: net margin is currently sharply declining (below
    # MARGIN_SHARP_DECLINE) while gross margin -- which independently
    # triggered sustained_decline and has since durably recovered -- must
    # not let the recovery gate excuse net's ongoing sharp decline. The
    # sharp-decline check must always run first, regardless of reversal
    # status on the OTHER series (mirrors a real case found in APD).
    gross = [30, 29, 30, 26, 22, 30, 32, 33, 32]  # dips then recovers past its own early average
    net = [20, 19, 18, 10, 5, 3, 2, 1, -3]  # currently in a sharp, unresolved decline
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "sharply_declining"
    assert score == 20


def test_margins_wildly_inconsistent_requires_real_oscillation_not_just_variance():
    # Repeated large swings in both directions netting no overall progress
    # -- genuine directionless chaos, not a single clean event.
    gross = [50, 70, 30, 70, 30, 70, 50]
    net = [20, 28, 12, 28, 12, 28, 20]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern == "wildly_inconsistent"
    assert score == 0


def test_margins_one_choppy_series_no_longer_vetoes_an_unambiguously_improving_other():
    # GOOGL's real gross/net margin history: gross bounces around with 2+
    # real dips netting flat (chaotic on its own), but net margin nearly
    # doubles over the same window -- a clearly, unambiguously improving
    # business. Requiring BOTH series to be chaotic (not either alone)
    # means this no longer reads as the worst possible tier.
    gross = [61.1, 58.9, 56.5, 55.6, 53.6, 56.9, 55.4, 56.6, 58.2, 59.7, 60.4]
    net = [21.6, 11.4, 22.5, 21.2, 22.1, 29.5, 21.2, 24.0, 28.6, 32.8, 37.9]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern != "wildly_inconsistent"


def test_margins_chaotic_net_alone_no_longer_vetoes_a_steadily_rising_gross():
    # PAYX's real gross/net margin history: net margin wobbles in a narrow
    # band (2+ real dips, near-flat direction), but gross margin rises
    # steadily and cleanly. One noisy series shouldn't veto an otherwise
    # clean read.
    gross = [70.8, 69.9, 68.8, 68.3, 68.7, 70.6, 71.0, 72.0, 72.4, 74.3, 74.3]
    net = [25.9, 27.6, 27.4, 27.2, 27.1, 30.2, 31.1, 32.0, 29.7, 27.0, 27.0]
    pattern, score = _classify_margins(gross, net, revenue_growing=True)
    assert pattern != "wildly_inconsistent"


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
