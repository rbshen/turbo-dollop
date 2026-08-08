import pytest

from scoring.step1 import _classify_fcf, _classify_margins, _classify_positive_trend, score_step1

GROWING = [100, 110, 121, 133, 146]
DECLINING = [146, 133, 121, 110, 100]
STABLE_MARGINS = [40, 41, 40, 42, 43]
NET_MARGINS_STABLE = [20, 20.5, 20, 21, 21.5]
FCF_ALL_POSITIVE = [50, 60, 55, 70, 65, 80]

# SYM's real cached Net Income / Operating Income / CFO (millions,
# FY2019-FY2025 + TTM) -- the case that motivated the positivity gate.
# Net Income has never been positive; Operating Income hasn't either
# (confirming the OI fallback correctly does NOT rescue it); CFO's TTM
# value is genuinely positive despite a volatile history.
SYM_NET_INCOME = [-104.361, -109.521, -122.314, -78.997, -23.866, -13.490, -16.937, -4.965]
SYM_OPERATING_INCOME = [-105.793, -110.377, -122.381, -140.375, -223.230, -116.725, -92.133, -20.144]
SYM_CFO = [17.185, -124.307, 109.567, -148.247, 230.794, -58.077, 866.939, 845.218]


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
    assert result["weights"] == {"revenue": 0.35, "net_income": 0.20, "cfo": 0.30, "margins": 0.10, "fcf": 0.05}


def test_fail_all_declining():
    # DECLINING's final transition (-9.1%) sits inside the graduated TTM
    # band (NOISE_FLOOR < decline < SEVERE_TTM_DECLINE), so it's no longer
    # an unconditional 0 -- it flows through as an ordinary (merged,
    # 4-transition) dip event that's too recent (age=0) to durably resolve,
    # landing on "multiple_dips"/40 instead. Still a clear Fail overall --
    # the graduated band softens an isolated mild wobble, not a company
    # that's genuinely declined every single year across its whole window.
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
    assert result["components"]["revenue"] == {"score": 40, "pattern": "multiple_dips"}
    assert result["components"]["cfo"] == {"score": 40, "pattern": "multiple_dips"}


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
    # CFO's 30% + FCF's 5% (35% combined) redistribute evenly across the 3
    # remaining applicable metrics: 0.35 + 0.35/3, 0.20 + 0.35/3, 0.10 + 0.35/3.
    assert result["weights"]["cfo"] == 0.0
    assert result["weights"]["fcf"] == 0.0
    assert result["weights"]["revenue"] == pytest.approx(0.466667, abs=1e-5)
    assert result["weights"]["net_income"] == pytest.approx(0.316667, abs=1e-5)
    assert result["weights"]["margins"] == pytest.approx(0.216667, abs=1e-5)
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


# --- Positivity gate (Revenue / Net Income / CFO) --------------------------


def test_positive_trend_gate_growing_series_unaffected():
    pattern, score = _classify_positive_trend(GROWING)
    assert pattern == "grows_every_year"
    assert score == 100


def test_net_income_never_profitable_scores_zero_even_with_relative_recovery():
    # SYM's real shape: Net Income has been negative every single period
    # (-104.4M FY19 -> -4.97M TTM) yet classify_trend alone reads this as
    # multiple_dips_resolved/75 since each "dip" is a relative worsening
    # that later reverses -- never checking whether the value itself is
    # positive. Operating Income is also still negative at TTM, so the
    # one-off/recency-gated OI fallback correctly does NOT rescue this --
    # this is a genuinely unprofitable company, not a one-off charge.
    result = score_step1(
        revenue=GROWING,
        net_income=SYM_NET_INCOME,
        operating_income=SYM_OPERATING_INCOME,
        cfo=SYM_CFO,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
        fcf=FCF_ALL_POSITIVE,
    )
    assert result["components"]["net_income"]["score"] == 0
    assert result["components"]["net_income"]["pattern"] == "not_yet_positive"
    assert result["components"]["net_income"]["used_operating_income_backup"] is False


def test_cfo_positive_ttm_keeps_existing_dip_tolerance_unchanged():
    # SYM's real CFO shape: 3 full sign-flips (17M -> -124M -> 110M -> -148M
    # -> 231M -> -58M) before finally settling positive the last 2 periods
    # (867M, 845M TTM). The confirmed rule only gates the CURRENT value's
    # sign -- it deliberately does not tighten classify_trend's own
    # dip-tolerance/recovery math -- so this stays multiple_dips_resolved/75.
    # Documents this is intended behavior, not a regression.
    pattern, score = _classify_positive_trend(SYM_CFO)
    assert pattern == "multiple_dips_resolved"
    assert score == 75


def test_net_income_oi_fallback_triggers_for_recent_one_off_dip():
    # TTM itself drops sharply (a plausibly one-off charge landing in the
    # latest reported period, age 0) while Operating Income stays clean --
    # the recency gate is deliberately inclusive of age 0 (see
    # NET_INCOME_BACKUP_RECENCY_YEARS's comment), so this qualifies.
    recent_dip_net_income = [50, 60, 70, 80, 30]
    result = score_step1(
        revenue=GROWING,
        net_income=recent_dip_net_income,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"]["used_operating_income_backup"] is True
    assert result["components"]["net_income"]["score"] == 80


def test_net_income_oi_fallback_does_not_trigger_when_classify_trend_already_resolves_it():
    # The one real dip happened 6 periods before TTM with 6 clean growth
    # years since -- classify_trend's own age/recovery-run-aware resolution
    # (see trend.py::_dip_durably_resolved) now recognizes this as durably
    # resolved (75) on its own merits, so NI's score never drops to/below
    # NET_INCOME_BACKUP_THRESHOLD in the first place and the OI fallback is
    # never even considered. (Before that fix, this same fixture scored 40
    # and this test existed to confirm the OI fallback still correctly
    # declined to rescue an old, chronic-looking dip -- see
    # test_net_income_oi_fallback_does_not_trigger_for_a_still_unresolved_old_dip
    # below for that scenario, preserved with a fixture that still exercises it.)
    old_dip_net_income = [100, 40, 45, 50, 55, 60, 65, 70]
    result = score_step1(
        revenue=GROWING,
        net_income=old_dip_net_income,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"] == {
        "score": 75,
        "pattern": "dip_durably_resolved",
        "used_operating_income_backup": False,
    }


def test_net_income_oi_fallback_does_not_trigger_for_a_still_unresolved_old_dip():
    # A single real dip whose most recent (only) transition is 3 periods
    # before TTM -- outside the OI fallback's own "1 or 2 years in the
    # past" recency window (NET_INCOME_BACKUP_RECENCY_YEARS=2), AND outside
    # the new durable-resolution path's own age floor (DIP_RESOLUTION_MIN_AGE
    # =4) too, so NI's score stays at "multiple_dips"/40 on both counts.
    # Confirms the OI fallback's recency gate still holds for a genuinely
    # bad, not-yet-old-enough-to-excuse score -- not just for cases the new
    # resolution path has since rescued to a good score on its own.
    old_unresolved_net_income = [100, 110, 120, 60, 70, 80, 90]
    result = score_step1(
        revenue=GROWING,
        net_income=old_unresolved_net_income,
        operating_income=GROWING,
        cfo=GROWING,
        gross_margin=STABLE_MARGINS,
        net_margin=NET_MARGINS_STABLE,
        cfo_exempt=False,
    )
    assert result["components"]["net_income"] == {
        "score": 40,
        "pattern": "multiple_dips",
        "used_operating_income_backup": False,
    }
    assert result["components"]["net_income"]["score"] == 40


def test_revenue_positive_gate_is_no_op_when_ttm_recovers():
    dip_then_recovers = [10, 20, -5, 30, 40]
    pattern, score = _classify_positive_trend(dip_then_recovers)
    assert pattern == "significant_dip_recovers"
    assert score == 85


def test_revenue_positive_gate_applies_when_ttm_still_negative():
    still_negative_ttm = [10, 20, -5]
    pattern, score = _classify_positive_trend(still_negative_ttm)
    assert pattern == "not_yet_positive"
    assert score == 0


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


def test_fcf_old_recovered_cash_burn_scores_good_not_fail():
    # Mirrors AMD's real shape: a 2-consecutive-negative run early in the
    # window (indices 1-2 here, 7 periods before the last point), followed
    # by strong, growing positive FCF ever since -- classify_trend reads
    # this as multiple_dips_resolved, so an old, durably recovered
    # cash-burn stretch no longer permanently reads as "sustained_cash_burn".
    fcf = [10, -20, -30, 100, 200, 300, 400, 500, 600, 700]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "cash_burn_recovered"
    assert score == 85


def test_fcf_old_unrecovered_cash_burn_still_fails():
    # Same old run position as above, but the series never durably
    # recovers past the pre-dip level (classify_trend reads multiple_dips,
    # not a resolved pattern) -- an old run alone isn't enough to excuse
    # the tier; the recovery must actually be confirmed.
    fcf = [100, -20, -30, 10, 15, 12, 18, 20, 22, 25]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_old_recovered_cash_burn_tolerates_minor_ttm_wobble():
    # TSLA-style: an old run, then several years of robust, growing positive
    # FCF, then a TTM dip (>5%, would trip classify_trend's blunt
    # any-TTM-decline rule on its own) that's still nowhere near the burn
    # level. Dropping TTM reads as durably recovered, and TTM itself is
    # still well above the early post-burn baseline -- the wobble shouldn't
    # re-flag an already-resolved cash-burn stretch as ongoing risk.
    fcf = [10, -20, -30, 100, 200, 300, 700, 400, 350, 600, 550]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "cash_burn_recovered"
    assert score == 85


def test_fcf_recurring_negative_years_since_the_run_still_fails():
    # PEG-style: the LAST 2+-consecutive run ended long enough ago to clear
    # the recency gate, but a further isolated negative year (and a
    # negative TTM) since then shows the company hasn't actually been
    # solidly positive since -- must not be waved through as a "wobble".
    fcf = [100, -20, -30, 10, 15, 12, -40, 18, 20, -5]
    pattern, score = _classify_fcf(fcf)
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_insufficient_data_below_two_points():
    pattern, score = _classify_fcf([50])
    assert pattern == "insufficient_data"
    assert score == 0


# --- FCF capex-driven softening (2026-08-08 fix) ---------------------------

# AEP/DUK/ED/ES/FE/SO-shaped: a 3-year negative-FCF run ending at TTM (too
# recent to clear FCF_CASH_BURN_RECENCY_YEARS on its own).
_CAPEX_HEAVY_FCF = [50, 60, 70, -5, -8, -10]


def test_fcf_capex_driven_burn_scores_good_when_cfo_positive_and_growing_throughout():
    # CFO stayed positive and grew across the entire negative-FCF run --
    # there was never a real cash crisis, just heavy capex outspending
    # operating cash flow, so the recency gate doesn't apply.
    pattern, score = _classify_fcf(_CAPEX_HEAVY_FCF, [400, 420, 450, 470, 485, 500])
    assert pattern == "capex_driven_negative_fcf"
    assert score == 85


def test_fcf_capex_driven_check_requires_cfo_positive_throughout_not_just_endpoints():
    # CFO dips negative in the MIDDLE of the run even though both endpoints
    # are fine -- must not be softened just because CFO looks okay at a
    # glance at the start/end of the window.
    pattern, score = _classify_fcf(_CAPEX_HEAVY_FCF, [400, 420, 450, 470, -10, 500])
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_capex_driven_check_requires_cfo_non_declining():
    # CFO positive throughout the run, but declining (not growing) across
    # it -- doesn't read as "strong operations funding an investment
    # phase," so the softening doesn't apply.
    pattern, score = _classify_fcf(_CAPEX_HEAVY_FCF, [400, 420, 450, 500, 490, 480])
    assert pattern == "sustained_cash_burn"
    assert score == 0


def test_fcf_capex_driven_softening_requires_cfo_argument():
    # No cfo passed (default None) -- unchanged legacy behavior, confirming
    # backward compatibility for every existing caller of _classify_fcf.
    pattern, score = _classify_fcf(_CAPEX_HEAVY_FCF)
    assert pattern == "sustained_cash_burn"
    assert score == 0
