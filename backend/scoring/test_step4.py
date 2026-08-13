import pytest

from scoring.step4 import (
    AR_DSO_TREND_MATERIALITY_DAYS,
    check_roe_roic_divergence,
    classify_ccc_trend,
    income_recovery_detail,
    recovery_excluded_prefix_length,
    score_revenue_vs_ar,
    score_roe,
    score_roic,
    score_step4,
)
from scoring.trend import TrendResult

POSITIVE_EQUITY = [100.0] * 6

# --- ROE tiers ---


def test_roe_excellent_above_15_with_consistent_min_year():
    result = score_roe([20.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("excellent", 100, False)


def test_roe_good_12_to_15():
    result = score_roe([13.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("good", 85, False)


def test_roe_good_boundary_at_15_is_good_not_excellent():
    result = score_roe([15.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("good", 85, False)


def test_roe_marginal_8_to_12():
    result = score_roe([10.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("marginal", 60, False)


def test_roe_marginal_when_high_average_but_inconsistent_min_year():
    # avg well above 15%, but one very weak year (min < 8%) -- inconsistent,
    # so it doesn't get the "excellent" tier despite the high average.
    result = score_roe([30.0, 30.0, 30.0, 30.0, 30.0, 5.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("marginal", 60, False)


def test_roe_below_floor_but_never_negative_is_weak_but_positive_not_hard_fail():
    # 2026-08-13 graduated-scale fix: a consistently positive-but-mediocre
    # average (5.0%, never once negative) is no longer flattened into the
    # same flat 0/hard_fail as a company actively destroying capital.
    # points = round(20 + 35*(5.0/8.0)) = 42.
    result = score_roe([5.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("weak_but_positive", 42, False)


def test_roe_negative_average_still_hard_fails():
    # The graduated scale only applies when avg >= 0 -- a genuinely
    # negative average stays exactly as before: flat 0, hard_fail.
    result = score_roe([-5.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("fail", 0, True)


# --- ROE/ROIC trend-awareness: spike-robust average ---


def test_roe_anomalous_spike_excluded_flips_tier():
    # A single year >=2x the median of the rest (a one-time tax benefit,
    # e.g. MPWR's real 2024) can't inflate the average into a higher tier
    # on its own -- 50 vs a 14-median baseline (3.6x) is excluded, leaving
    # a robust average of 14 ("good"), not the raw average's 20 ("excellent").
    result = score_roe([14.0, 14.0, 14.0, 50.0, 14.0, 14.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("good", 85, False)


def test_roe_ordinary_variation_not_excluded_as_spike():
    # 24 vs a 16-median baseline is only 1.5x -- not extreme enough to
    # count as an anomaly (mirrors MPWR's own ROIC: a real ~1.6x cyclical
    # peak that must NOT be excluded). The raw average (17.33, "excellent")
    # stands unchanged.
    result = score_roe([16.0, 16.0, 16.0, 24.0, 16.0, 16.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("excellent", 100, False)


def test_roe_low_outlier_year_is_never_excluded():
    # Mirrors DAL's real shape: a severe crash year (-40) must NEVER be
    # treated as an "anomaly" to exclude by _spike_robust_avg -- only the
    # series MAXIMUM is ever a candidate, since ROE_MIN_YEAR_CONSISTENCY
    # already exists specifically to catch a single bad year; erasing it
    # here would silently undo that protection and wrongly promote this to
    # "good" (if -40 were wrongly excluded, the remaining 5 values average
    # 15.98). TTM (15.9) is deliberately kept just under the pre-crash
    # baseline (16.0) so recovery_excluded_prefix_length's own exclusion
    # (see the next test for the case where it DOES apply) never engages
    # here -- this test is isolating _spike_robust_avg's own guarantee,
    # not recovery-aware exclusion's interaction with it. Correctly
    # including -40 gives avg 6.65 -- positive, so this is graduated
    # "weak_but_positive" (2026-08-13 fix), not "good", and nowhere near
    # the wrongly-excluded outcome this test guards against.
    result = score_roe([16.0, 16.0, 16.0, -40.0, 16.0, 15.9], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("weak_but_positive", 49, False)


def test_roe_low_outlier_inside_a_literally_resolved_dip_can_be_excluded():
    # A real, deliberate interaction between two independently-tuned
    # mechanisms: unlike the test above, TTM here returns to EXACTLY the
    # pre-crash baseline (16.0) -- a literal recovery, so
    # recovery_excluded_prefix_length's broad exclusion (through the
    # trough inclusive) now DOES apply and removes the crash year along
    # with everything before it, leaving just [16.0, 16.0] to average.
    # This is the same class of tradeoff already known and accepted for
    # C-broad (LHX/LUV/MU-shaped structural-decline regressions, see
    # profitability.md) -- a genuinely bad year that's since been fully
    # recovered from no longer anchors the average, even though
    # _spike_robust_avg's own max-only exclusion rule would never have
    # touched it on its own.
    result = score_roe([16.0, 16.0, 16.0, -40.0, 16.0, 16.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("excellent", 100, False)


# --- ROE/ROIC trend-awareness: decline-durability gate ---


def test_roe_unrecovered_decline_demotes_from_excellent_to_good():
    # Mirrors INTU's real shape: a severe decline (early-window avg 38 ->
    # trough 12) with only partial recovery by TTM (14, still far below
    # the early-window average) -- both avg (25.8) and min-year (12) clear
    # "excellent" today, but the decline hasn't actually been reclaimed.
    result = score_roe([40.0, 38.0, 36.0, 15.0, 12.0, 14.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("good", 85, False)


def test_roe_recovered_decline_does_not_demote():
    # Same early decline, but TTM (50) has since climbed back ABOVE the
    # early-window average (38) -- a durably reversed decline must read
    # the same as if it never happened, exactly like Margins' Rule 1.
    result = score_roe([40.0, 38.0, 36.0, 15.0, 45.0, 50.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("excellent", 100, False)


def test_roe_decline_recovered_to_exactly_the_early_average_does_not_demote():
    # Boundary: TTM == early-window average exactly -- the gate uses a
    # strict "<", so exact reclamation counts as recovered.
    result = score_roe([40.0, 38.0, 36.0, 15.0, 12.0, 38.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("excellent", 100, False)


def test_roe_unrecovered_decline_from_good_demotes_to_marginal_not_fail():
    # The demotion must never manufacture a hard-fail that the absolute
    # avg/min-year floor itself didn't already produce -- caps at
    # "marginal", the same floor a plain avg/min-year read would allow.
    result = score_roe([20.0, 18.0, 16.0, 7.0, 6.0, 7.0], POSITIVE_EQUITY, [10.0] * 6)
    assert result == ("marginal", 60, False)


# --- Recovery-aware exclusion (Candidate C-broad, 2026-08-08) ---
# A resolved dip's own stale years (through and including its trough) are
# excluded from the flat 10yr+TTM average before tiering -- see
# recovery_excluded_prefix_length's own docstring for the exact rule
# (broad: the whole prefix through the last resolved dip's trough, not
# just its own declining leg) and profitability.md for the full writeup,
# including the known LHX/LUV-shaped structural-decline tradeoff this
# mechanism accepts.

_HWM_ROE = [-18.3, -1.5, 11.5, 10.2, 5.9, 7.4, 13.0, 18.9, 25.4, 28.2, 34.4]
_HWM_ROIC = [-18.0, -1.4, 6.4, 4.9, 8.3, 7.7, 9.1, 11.0, 15.5, 18.2, 18.6]


def test_recovery_excluded_prefix_length_hwm_shaped():
    # ROE: one merged event (transitions 2-3, trough at value-index 4) ->
    # excludes indices 0-4 (5 values). ROIC: two single-transition events
    # (troughs at value-index 3 and 5) -- the LAST resolved trough governs
    # the broad cutoff -> excludes indices 0-5 (6 values).
    assert recovery_excluded_prefix_length(_HWM_ROE) == 5
    assert recovery_excluded_prefix_length(_HWM_ROIC) == 6


def test_recovery_excluded_prefix_length_no_dip_returns_zero():
    assert recovery_excluded_prefix_length([10.0, 11.0, 12.0, 13.0, 14.0]) == 0


def test_recovery_excluded_prefix_length_falls_back_when_too_little_would_remain():
    # A resolved dip (100 -> 20 -> literally back to 100 by TTM) whose
    # trough sits at value-index 3 of a 5-point series -- excluding
    # through it (broad) would leave only 1 point (index 4), below the
    # 2-point floor _score_avg_min_tier needs, so exclusion must not
    # apply at all despite the dip genuinely resolving.
    assert recovery_excluded_prefix_length([50.0, 50.0, 100.0, 20.0, 100.0]) == 0


def test_score_roe_hwm_shaped_lands_on_excellent_matching_the_prototype():
    result = score_roe(_HWM_ROE, [100.0] * 11, [10.0] * 11)
    assert result == ("excellent", 100, False)


def test_score_roic_hwm_shaped_lands_on_good_matching_the_prototype():
    result = score_roic(_HWM_ROIC)
    assert result == ("good", 85, False)


def test_score_roe_lhx_shaped_structural_decline_still_regresses_below_marginal():
    # Real, accepted tradeoff (not a bug): a genuine long-term decliner
    # whose only strong years sit before a resolved dip loses those years
    # to the same exclusion mechanism that helps HWM -- LHX's own real ROE
    # shape (values from the candidate comparison), real=Marginal/60
    # before this build, below-marginal after. Confirms the exclusion is
    # applied unconditionally on resolution, not gated on "does this
    # help." The post-exclusion average is positive (never negative), so
    # as of the 2026-08-13 graduated-scale fix this reads
    # "weak_but_positive"/55 (near the graduated ceiling), not a flat
    # 0/hard_fail -- still a real, meaningful demotion from its
    # pre-exclusion Marginal/60 read, just an honest number instead of a
    # manufactured hard fail.
    lhx_roe = [18.5, 23.3, 28.2, 0.0, 5.4, 9.6, 5.7, 6.5, 7.7, 8.2, 9.5]
    result = score_roe(lhx_roe, [100.0] * 11, [10.0] * 11)
    assert result == ("weak_but_positive", 55, False)


def test_score_roe_ball_shaped_no_dip_story_is_unaffected():
    # BALL's real ROE shape -- no detected dip anywhere in the window, so
    # recovery-aware exclusion must never engage; score is unchanged from
    # the pre-build design (confirmed the same in both prototype rounds).
    ball_roe = [7.7, 9.5, 13.1, 19.2, 17.9, 24.2, 20.8, 18.8, 68.4, 16.8, 17.0]
    result = score_roe(ball_roe, [100.0] * 11, [10.0] * 11)
    assert result == ("marginal", 60, False)


# --- Negative equity exception ---


def test_negative_equity_with_positive_growing_income_scores_100():
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    # Raw ROE values are ignored entirely once equity goes negative anywhere.
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("positive_despite_negative_equity", 100, False)


def test_negative_equity_with_a_recent_loss_year_scores_60_not_a_fail():
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [10.0, 10.0, 10.0, 10.0, 10.0, -5.0]  # loss at TTM -- recent
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("negative_equity_inconsistent_income", 60, False)
    assert result.hard_fail is False


def test_negative_equity_with_an_old_recovered_loss_scores_100():
    # Same shape as the recent-loss case, but the loss is 4 periods before
    # TTM (outside DIP_RECOVERY_RECENCY_YEARS) and classify_trend reads the
    # series as significant_dip_recovers -- an old, since-resolved loss
    # shouldn't permanently disqualify the substitute signal, same
    # philosophy as Step 3's CFO/Net Income recency fix.
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [10.0, -5.0, 10.0, 10.0, 10.0, 10.0]
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("positive_despite_negative_equity", 100, False)


def test_negative_equity_with_declining_income_scores_60():
    equity = [100.0, 100.0, -50.0, 100.0, 100.0, 100.0]
    net_income = [20.0, 18.0, 16.0, 14.0, 12.0, 10.0]  # positive but net declining
    result = score_roe([-999.0] * 6, equity, net_income)
    assert result == ("negative_equity_inconsistent_income", 60, False)


# --- income_recovery_detail's shape labels ------------------------------------
# score_roe()'s own outcome (100/60/hard_fail) is unchanged by any of this --
# these tests exist because step4_data.py's ROE reasoning-text builder needs
# to know WHICH of the 5 branches produced a given consistent/inconsistent
# read, not just the bool. Reuses the exact same fixtures as the
# score_roe() negative-equity tests above (same shape, different assertion)
# plus one new fixture for the shape no existing score_roe() test exercises.


def test_shape_always_positive_growing():
    net_income = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    assert income_recovery_detail(net_income) == (True, "always_positive_growing")


def test_shape_always_positive_but_declined():
    net_income = [20.0, 18.0, 16.0, 14.0, 12.0, 10.0]
    assert income_recovery_detail(net_income) == (False, "always_positive_but_declined")


def test_shape_recent_dip():
    net_income = [10.0, 10.0, 10.0, 10.0, 10.0, -5.0]
    assert income_recovery_detail(net_income) == (False, "recent_dip")


def test_shape_old_dip_recovered():
    net_income = [10.0, -5.0, 10.0, 10.0, 10.0, 10.0]
    assert income_recovery_detail(net_income) == (True, "old_dip_recovered")


def test_shape_old_dip_not_recovered():
    # The loss (index 1) is 4 periods before TTM, same as the
    # old_dip_recovered fixture -- clears the recency gate -- but net
    # income keeps declining afterward (10 -> 8 -> 6 -> 4) so the final
    # transition is itself a real decline, and classify_trend reads the
    # whole series as "declining" (0), not a recovery pattern.
    net_income = [10.0, -5.0, 10.0, 8.0, 6.0, 4.0]
    assert income_recovery_detail(net_income) == (False, "old_dip_not_recovered")


def test_shape_no_data():
    assert income_recovery_detail([]) == (False, "no_data")


# --- ROIC uses the same tiering, independently ---


def test_roic_excellent():
    assert score_roic([20.0] * 6) == ("excellent", 100, False)


def test_roic_below_floor_but_positive_is_weak_but_positive_not_hard_fail():
    # GLW's real shape (2026-08-13 investigation): consistently positive
    # but chronically mediocre ROIC (avg 6.42% across 11 years, never
    # negative) -- graduated, not a flat 0/hard_fail. Mirrors ROE's own
    # fix (test above); confirms the graduated scale applies identically
    # to ROIC via the same _score_avg_min_tier.
    assert score_roic([2.0] * 6) == ("weak_but_positive", 29, False)


def test_roic_negative_average_still_hard_fails():
    assert score_roic([-2.0] * 6) == ("fail", 0, True)


def test_roic_shares_the_same_spike_robust_and_decline_durability_gates():
    # ROIC goes through the exact same _spike_robust_avg /
    # _demote_for_unrecovered_decline path as ROE -- one confirmation
    # that neither mechanism is ROE-only.
    assert score_roic([14.0, 14.0, 14.0, 50.0, 14.0, 14.0]) == ("good", 85, False)
    assert score_roic([40.0, 38.0, 36.0, 15.0, 12.0, 14.0]) == ("good", 85, False)


# --- ROE-vs-ROIC divergence flag ---


def test_divergence_flags_excellent_roe_marginal_roic():
    roe = _ratio("excellent", 100)
    roic = _ratio("marginal", 60)
    note = check_roe_roic_divergence(roe, roic)
    assert note is not None
    assert "excellent" in note and "marginal" in note


def test_divergence_flags_good_roe_marginal_roic():
    roe = _ratio("good", 85)
    roic = _ratio("marginal", 60)
    assert check_roe_roic_divergence(roe, roic) is not None


def test_divergence_silent_when_roic_also_strong():
    # Mirrors MA's real shape: a large absolute gap, but ROIC is still
    # comfortably "excellent" in its own right -- not a real divergence.
    roe = _ratio("excellent", 100)
    assert check_roe_roic_divergence(roe, _ratio("excellent", 100)) is None
    assert check_roe_roic_divergence(roe, _ratio("good", 85)) is None


def test_divergence_silent_when_roic_already_fails():
    # A "fail" ROIC already trips score_step4's hard-fail override on its
    # own -- no need to double-flag.
    roe = _ratio("excellent", 100)
    assert check_roe_roic_divergence(roe, _ratio("fail", 0, hard_fail=True)) is None


def test_divergence_silent_when_roic_exempt():
    roe = _ratio("excellent", 100)
    assert check_roe_roic_divergence(roe, None) is None


def test_divergence_silent_for_negative_equity_substitute_labels():
    # The negative-equity substitute paths never produce "excellent"/"good"
    # labels, so they're naturally exempt without special-casing.
    roe = _ratio("positive_despite_negative_equity", 100)
    assert check_roe_roic_divergence(roe, _ratio("marginal", 60)) is None


# --- Metric 3: Revenue vs Accounts Receivable ---


def _build(revenue_yoys: list[float], ar_yoys: list[float], revenue0: float = 100.0, ar0: float = 50.0):
    revenue = [revenue0]
    ar = [ar0]
    for ry, ay in zip(revenue_yoys, ar_yoys):
        revenue.append(revenue[-1] * (1 + ry / 100))
        ar.append(ar[-1] * (1 + ay / 100))
    return revenue, ar


def _label_points_hard_fail(result):
    """Most AR tests only care about the tier outcome, not the DSO/count
    fields ARResult now also carries for step4_data.py's reasoning-note
    builder -- this keeps assertions readable instead of hardcoding
    float DSO values that aren't the point of the test."""
    return (result.label, result.points, result.hard_fail)


def test_ar_zero_outpacing_years_scores_100():
    revenue, ar = _build([10, 10], [10, 10])
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("healthy", 100, False)


def test_ar_one_isolated_small_gap_scores_100():
    revenue, ar = _build([10, 10], [10, 20])  # gap = 10pp on one of two transitions
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("healthy", 100, False)


def test_ar_one_isolated_medium_gap_scores_70():
    revenue, ar = _build([10, 10], [10, 40])  # gap = 30pp (medium)
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("outpacing_isolated", 70, False)


# --- AR noise floor + aggregate-trend fix (2026-08-01) -----------------------
# The worst tier's trigger changed from "majority of individual years
# outpacing" to "AR's Days Sales Outstanding rose materially in aggregate,
# early-window vs a robust late window" (see this module's own comment
# block on AR_DSO_TREND_MATERIALITY_DAYS for why). The tests below replace
# the old majority-count-focused suite: a few use fixtures where a numeric
# majority of individual years outpace but the aggregate DSO trend stays
# mild (the AAPL-shaped bug this fix targets -- confirmed these no longer
# force the worst tier), and others confirm a genuinely material aggregate
# DSO increase still forces it even without a majority of individual years.
# AR_CONCERNING_TRANSITION_RATIO's own count-based rescaling (the
# "concerning" tier) is UNCHANGED by this fix -- these fixtures are built
# to keep the aggregate trend mild specifically so that tier can be
# exercised on its own, without the (now DSO-driven) worst tier
# intercepting first.


def test_ar_numeric_majority_with_mild_aggregate_trend_no_longer_forces_zero():
    # AAPL-shaped: 6 of 10 individual years show AR outpacing revenue by a
    # real per-year gap (13% vs 10%, well past the noise floor) -- a
    # numeric majority under the OLD rule, which would have forced 0
    # regardless of the bigger picture. Interleaved with 4 slower-AR years
    # so the aggregate DSO trend nets out mild (+0.3 days over the window)
    # -- correctly no longer lands on the worst tier; the still-unchanged
    # count-based "concerning" tier picks it up instead (6 hits the n=10
    # concerning_threshold of 6).
    ar_yoys = [13, 7, 13, 7, 13, 7, 13, 7, 13, 13]
    revenue, ar = _build([10] * 10, ar_yoys)
    result = score_revenue_vs_ar(revenue, ar)
    assert result.num_outpacing == 6
    assert result.dso_late_robust - result.dso_early < 15.0
    assert _label_points_hard_fail(result) == ("outpacing_concerning", 40, False)


def test_ar_few_outpacing_years_but_genuine_aggregate_drift_forces_zero():
    # The mirror case: only 2 of 4 individual years show AR outpacing
    # (never a numeric majority under the old rule), but those 2 gaps are
    # large enough that they compound into a genuine, material aggregate
    # DSO increase (+62 days) by the end of the window -- correctly still
    # forces the worst tier under the new aggregate-trend rule, confirming
    # this fix doesn't just loosen the worst tier across the board.
    revenue, ar = _build([10, 10, 10, 10], [10, 10, 40, 22])
    result = score_revenue_vs_ar(revenue, ar)
    assert result.num_outpacing == 2
    assert result.dso_late_robust - result.dso_early > AR_DSO_TREND_MATERIALITY_DAYS
    assert _label_points_hard_fail(result) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_small_persistent_gaps_can_still_compound_into_material_drift():
    # 2 of 3 individual years outpace by a SMALL per-year gap (10pp each,
    # not one dramatic year) -- still compounds to a real +17.6 day
    # aggregate DSO increase, past the materiality floor. A couple of
    # small-but-persistent gaps, not just one dramatic gap, can add up to
    # a genuine aggregate problem.
    revenue, ar = _build([10, 10, 10], [20, 20, 10])
    result = score_revenue_vs_ar(revenue, ar)
    assert result.dso_late_robust - result.dso_early > AR_DSO_TREND_MATERIALITY_DAYS
    assert _label_points_hard_fail(result) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_concerning_tier_rescaling_at_n5_still_reachable_with_mild_aggregate():
    # 3 of 5 transitions outpace (the doc's original 5yr+TTM window,
    # concerning_threshold = max(3, round(0.6*5)) = 3), aggregate DSO trend
    # kept mild (+3.2 days, interleaved fast/slow years) so the worst tier
    # doesn't intercept first -- confirms the concerning tier's own
    # rescaling logic is unaffected by the worst tier's trigger change.
    ar_yoys = [13, 7, 13, 7, 13]
    revenue, ar = _build([10] * 5, ar_yoys)
    result = score_revenue_vs_ar(revenue, ar)
    assert result.num_outpacing == 3
    assert result.dso_late_robust - result.dso_early < AR_DSO_TREND_MATERIALITY_DAYS
    assert _label_points_hard_fail(result) == ("outpacing_concerning", 40, False)


def test_ar_concerning_tier_rescaling_at_n6_below_threshold_reads_isolated():
    # Same 3-outpacing count as above, but over 6 transitions instead of 5
    # (50% vs. the doc-calibrated 60% severity bar, concerning_threshold =
    # max(3, round(0.6*6)) = 4) -- proportional rescaling means this reads
    # as isolated noise, not concerning. Aggregate DSO trend stays mild.
    ar_yoys = [13, 7, 13, 7, 13, 7]
    revenue, ar = _build([10] * 6, ar_yoys)
    result = score_revenue_vs_ar(revenue, ar)
    assert result.num_outpacing == 3
    assert _label_points_hard_fail(result) == ("outpacing_isolated", 70, False)


def test_ar_concerning_tier_rescaling_at_n10_five_below_threshold():
    # The exact rescaling AR_CONCERNING_TRANSITION_RATIO was built for: at
    # n=10 (10yr+TTM), concerning_threshold is 6, so 5 outpacing years --
    # which used to trip the old fixed "3+" rule -- reads as isolated.
    ar_yoys = [13, 7, 13, 7, 13, 7, 13, 7, 13, 7]
    revenue, ar = _build([10] * 10, ar_yoys)
    result = score_revenue_vs_ar(revenue, ar)
    assert result.num_outpacing == 5
    assert _label_points_hard_fail(result) == ("outpacing_isolated", 70, False)


def test_ar_strong_red_flag_noise_floored_trivial_move_no_longer_scores_0():
    # CAT's real shape: revenue -3.4%, AR +0.14% -- both legs are trivial
    # noise, well under AR_GAP_NOISE_FLOOR (2pp). Previously a bare sign
    # check forced 0 regardless of magnitude; now correctly falls through.
    revenue = [100.0, 96.6]
    ar = [50.0, 50.07]
    assert score_revenue_vs_ar(revenue, ar).label != "outpacing_majority_or_red_flag"


def test_ar_strong_red_flag_material_move_still_scores_0():
    # BA-shape: revenue -24.3%, AR +217% -- both legs are clearly past the
    # noise floor, a genuine red flag, must still force 0.
    revenue = [100.0, 75.7]
    ar = [50.0, 158.5]
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_old_red_flag_outside_the_recency_window_no_longer_forces_zero():
    # Mirrors NVDA's real shape: revenue declining while AR grows, but in
    # the OLDEST transition (index 0 of 6) -- well outside the last
    # AR_RED_FLAG_RECENCY_WINDOW transitions. A single old, resolved
    # occurrence must no longer permanently force the worst tier.
    revenue, ar = _build([-10, 5, 5, 5, 5, 5], [10, 5, 5, 5, 5, 5])
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("outpacing_isolated", 70, False)


def test_ar_recent_red_flag_still_forces_zero():
    # Same shape, but the revenue-declining/AR-growing transition is the
    # MOST RECENT one -- a genuinely current problem must still hard-fail
    # regardless of the recency gate.
    revenue, ar = _build([5, 5, 5, 5, 5, -10], [5, 5, 5, 5, 5, 10])
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_red_flag_at_the_recency_window_boundary_still_counts():
    # i == n - AR_RED_FLAG_RECENCY_WINDOW is the OLDEST transition still
    # inside the recency window (inclusive) -- must still force 0.
    revenue, ar = _build([5, 5, 5, -10, 5, 5], [5, 5, 5, 10, 5, 5])
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("outpacing_majority_or_red_flag", 0, False)


def test_ar_single_large_gap_scores_40_even_if_isolated():
    revenue, ar = _build([10, 10], [10, 80])  # gap = 70pp (large), only 1 outpacing year
    assert _label_points_hard_fail(score_revenue_vs_ar(revenue, ar)) == ("outpacing_concerning", 40, False)


def test_ar_insufficient_data_with_fewer_than_two_periods():
    result = score_revenue_vs_ar([100.0], [50.0])
    assert _label_points_hard_fail(result) == ("insufficient_data", 0, False)
    assert result.dso_early is None and result.dso_late_robust is None


# --- Metric 4: Cash Conversion Cycle trend (inverted margin classifier) ---


def test_ccc_declining_steadily_scores_100():
    result = classify_ccc_trend([50, 48, 46, 44, 42, 40])
    assert result == TrendResult("declining_or_stable", 100)


def test_ccc_volatile_but_net_declining_scores_70():
    result = classify_ccc_trend([50, 55, 40, 35, 30, 25])
    assert result == TrendResult("volatile_but_net_declining", 70)


def test_ccc_volatile_no_clear_trend_scores_40():
    result = classify_ccc_trend([50, 60, 40, 60, 40, 50])
    assert result == TrendResult("volatile_no_trend", 40)


def test_ccc_sharp_sustained_rise_scores_graduated_not_flat_zero():
    # 2026-08-13 fix: sustained_upward's points are graduated by how far
    # CCC has actually worsened (early-vs-late direction, 22.7 days here),
    # not a flat 0. Still deep in the low end of the graduated range.
    result = classify_ccc_trend([30, 32, 38, 44, 50, 56])
    assert result == TrendResult("sustained_upward", 33)


def test_ccc_slow_net_worsening_scores_at_the_graduated_mild_ceiling():
    # 2026-08-13 fix: a slow creep (10 days early-vs-late) sits right at
    # CCC_UPWARD_MILD_DAYS, the graduated range's ceiling (40, matching
    # volatile_no_trend's own score) -- still the worst pattern, just an
    # honest number for a genuinely mild move.
    result = classify_ccc_trend([30, 30, 30, 30, 30, 40])
    assert result == TrendResult("sustained_upward", 40)


def test_ccc_insufficient_data():
    assert classify_ccc_trend([50.0]) == TrendResult("insufficient_data", 0)


def test_ccc_old_resolved_dip_does_not_override_a_strongly_positive_trend():
    # Mirrors MSFT's real shape: a small early rise, followed by a much
    # larger decline that crosses into negative CCC territory and stays
    # there (early window avg +25.3, robust late window avg -7.5) -- a
    # genuine settle into negative CCC (suppliers funding the business),
    # not just "improving positive CCC". Under sign-aware classification
    # this is "gained_bargaining_power", 100 -- a more accurate read than
    # the old flat 70, which had no way to represent "durably crossed into
    # negative territory" as its own, stronger outcome. Still must not read
    # as sustained_upward / 0.
    result = classify_ccc_trend([20, 26, 30, 15, 0, -15])
    assert result.pattern != "sustained_upward"
    assert result.score > 0
    assert result == TrendResult("gained_bargaining_power", 100)


def test_ccc_recent_unresolved_decline_still_overrides_to_negative():
    # Regression guard: a genuinely still-worsening series (direction
    # stays clearly negative, matching ANET/FTNT's real shape) must keep
    # scoring in the worst tier -- the recency gate must not soften real
    # deterioration. Graduated as of 2026-08-13 (33, not a flat 0 -- same
    # fixture as the test above, still deep in the low end of the range).
    result = classify_ccc_trend([30, 32, 38, 44, 50, 56])
    assert result == TrendResult("sustained_upward", 33)


def test_ccc_direction_exactly_at_the_stable_tolerance_boundary_does_not_override():
    # direction lands at (a hair above, due to float precision) exactly
    # CCC_STABLE_TOLERANCE_DAYS (-1.0) despite sustained_decline firing on
    # an early rise -- the gate uses a strict "<", so a direction that's
    # merely at the boundary (not clearly negative) does not re-trigger
    # the hard override; it falls through to the ordinary tiering instead.
    result = classify_ccc_trend([10, 16, 20, 21, 21, 7])
    assert result.pattern != "sustained_upward"


def test_ccc_late_window_spike_does_not_forgive_a_genuinely_worsening_trend():
    # Mirrors ABBV's real shape: real CCC drifts upward (worsening) for 8
    # periods via alternating up/down moves (never 2 consecutive worsening
    # periods, so sustained_decline never fires), then one wild anomalous
    # TTM value (-300, an implausible one-off) that reads as a dramatic
    # "improvement" on its own. Since this crosses the sign boundary, it
    # now first passes through the isolated-spike-rescue check (see
    # test_ccc_isolated_spike_is_rescued_to_the_pure_positive_path below)
    # before reaching this module's unchanged positive-CCC trend logic --
    # same end result: must not read as improving. Graduated as of
    # 2026-08-13 (40, at the graduated mild ceiling -- the robust-late-
    # direction magnitude that actually drove this classification, not
    # the raw direction, which is what's used for the "worsening" score
    # here since the raw reading is deceptively non-negative).
    result = classify_ccc_trend([70, 68, 74, 72, 78, 76, 82, 80, -300])
    assert result == TrendResult("sustained_upward", 40)


def test_ccc_spike_guard_does_not_touch_cases_already_resolved_by_the_recency_gate():
    # Regression guard: this series genuinely settles negative (see
    # test_ccc_old_resolved_dip_does_not_override_a_strongly_positive_trend
    # above for the sign-aware reasoning) and must land on
    # "gained_bargaining_power" via the mixed-series settling check, not be
    # re-capped by an unrelated rule.
    result = classify_ccc_trend([20, 26, 30, 15, 0, -15])
    assert result == TrendResult("gained_bargaining_power", 100)


# --- CCC sign-awareness (2026-08-01) ------------------------------------------


def test_ccc_consistently_negative_strengthening_scores_100():
    # DAL-shaped: deeply negative throughout, getting MORE negative over
    # time (early window avg -4.3, late window avg -8.4) -- suppliers
    # increasingly funding the business, the strongest possible signal.
    result = classify_ccc_trend([-3.5, -7.3, -2.0, 0.1, -6.0, -12.0, -11.2, -7.2, -7.0, -10.6, -7.7])
    assert result == TrendResult("consistently_negative_strengthening", 100)


def test_ccc_consistently_negative_weakening_still_scores_100():
    # AAPL's real shape: deeply negative throughout (-84 to -54 days,
    # still elite), but the direction is easing (early window avg -76.1,
    # late window avg -66.9 -- less negative, not less negative enough to
    # be a concern). Must NOT read as "sustained_upward" / 0 -- a still-
    # deeply-negative CCC is never a red flag just because its own
    # direction eased (see CLAUDE.md's Step 4 deviations).
    result = classify_ccc_trend(
        [-71.0, -73.5, -83.9, -62.9, -60.9, -56.4, -70.5, -67.8, -75.8, -71.1, -53.9]
    )
    assert result == TrendResult("consistently_negative_weakening", 100)


def test_ccc_gained_bargaining_power_scores_100():
    # KR-shaped: starts clearly positive (~7-8 days), durably settles
    # negative by TTM (~-7.6 days) -- a real improvement, not noise.
    result = classify_ccc_trend([8.2, 7.4, 7.8, 7.9, 6.3, 3.7, -2.7, -5.1, -4.5, -6.2, -7.6])
    assert result == TrendResult("gained_bargaining_power", 100)


def test_ccc_lost_bargaining_power_scores_0():
    # Mirror of the gained-bargaining-power case: starts clearly negative,
    # durably settles positive by TTM -- losing supplier leverage, a real
    # warning worth flagging.
    result = classify_ccc_trend([-8.2, -7.4, -7.8, -7.9, -6.3, -3.7, 2.7, 5.1, 4.5, 6.2, 7.6])
    assert result == TrendResult("lost_bargaining_power", 0)


def test_ccc_negligible_working_capital_scores_85():
    # COST-shaped: oscillates within a narrow band around zero (-1.5 to
    # +8.7), crossing zero repeatedly with no clear directional settling --
    # a moderately positive "structurally low capital intensity" signal,
    # not noise to flag as unclear.
    result = classify_ccc_trend([8.7, 4.8, 3.7, 2.9, -1.5, -1.1, 3.7, 2.0, 2.6, 1.7, 0.5])
    assert result == TrendResult("negligible_working_capital", 85)


def test_ccc_mixed_unclear_scores_40():
    # CCL-shaped: real, larger-magnitude swings across the sign boundary
    # (-8.6 to +12.5) with no clear directional settling and no near-zero
    # amplitude -- genuinely unclear, worth a manual look, not silently
    # scored as either a strength or a weakness.
    result = classify_ccc_trend([-8.6, -6.5, -2.3, -1.5, 5.0, 12.5, -7.5, -6.9, -6.0, -5.1, -5.7])
    assert result == TrendResult("mixed_unclear", 40)


def test_ccc_isolated_spike_is_rescued_to_the_pure_positive_path():
    # ABBV's real shape: 10yrs of clean positive CCC (62-102 days) then one
    # wildly anomalous TTM value (-496.7, a one-time acquisition-related
    # accounting event, ratio ~6.2x the positive side's typical magnitude)
    # -- must be rescued back to the pure-positive path (today's unchanged
    # trend logic) rather than misrouted into the mixed-series settling/
    # amplitude checks, which would otherwise misread a single anomalous
    # point as a genuine sign-crossing story.
    result = classify_ccc_trend([70.1, 72.6, 62.8, 77.3, 94.8, 69.9, 84.3, 82.3, 97.4, 102.4, -496.7])
    assert result == TrendResult("volatile_but_net_declining", 70)


def test_ccc_two_point_sign_shift_is_not_rescued_as_an_isolated_spike():
    # CDNS's real shape: 2 consecutive negative years (not a single
    # isolated point) after 9 years of positive, rising CCC -- must NOT
    # qualify for the isolated-spike rescue (len(neg_idx) == 2, not 1) and
    # instead falls through to the genuine settling check, which correctly
    # reads this as a durable improvement.
    result = classify_ccc_trend(
        [67.2, 66.1, 60.0, 104.5, 138.1, 179.6, 111.5, 119.6, 172.6, -214.5, -252.1]
    )
    assert result == TrendResult("gained_bargaining_power", 100)


# --- score_step4: weight redistribution + hard-fail override ---


def _ratio(label, points, hard_fail=False):
    from scoring.step4 import RatioResult

    return RatioResult(label, points, hard_fail)


def test_all_four_metrics_weighted_roic_highest():
    roe = _ratio("excellent", 100)
    ar = _ratio("healthy", 100)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["weights"] == {"roe": 0.25, "roic": 0.35, "ar": 0.20, "ccc": 0.20}
    assert result["score"] == 100
    assert result["verdict"] == "Strong Pass"
    assert result["hard_fail"] is False


def test_roic_exempt_redistributes_to_remaining_three():
    roe = _ratio("good", 90)
    ar = _ratio("healthy", 90)
    result = score_step4(roe, ar, None, TrendResult("declining_or_stable", 90))
    assert result["weights"] == pytest.approx({"roe": 25 / 65, "ar": 20 / 65, "ccc": 20 / 65})
    assert result["score"] == 90
    assert result["verdict"] == "Pass"  # 90 is not > 90, so not Strong Pass


def test_roic_and_ccc_both_exempt_redistributes_to_remaining_two():
    roe = _ratio("good", 90)
    ar = _ratio("healthy", 90)
    result = score_step4(roe, ar, None, None)
    assert result["weights"] == pytest.approx({"roe": 25 / 45, "ar": 20 / 45})
    assert result["score"] == 90


def test_ar_exempt_reit_redistributes_to_remaining_three():
    # REIT: ROIC and CCC are already exempt (company-type gates), AR is now
    # exempt too -- only ROE is left applicable in the worst case, but this
    # case still has a real CCC-equivalent-free reading via... actually for
    # REIT all three of AR/ROIC/CCC are typically exempt at once (see the
    # all-three-exempt test below); this test isolates AR's own exemption
    # against an otherwise-standard metric set to confirm the redistribution
    # math specifically for ar=None on its own.
    roe = _ratio("good", 90)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("declining_or_stable", 90)
    result = score_step4(roe, None, roic, ccc)
    assert result["weights"] == pytest.approx({"roe": 25 / 80, "roic": 35 / 80, "ccc": 20 / 80})
    assert result["components"]["revenue_vs_ar"] is None


def test_ar_roic_ccc_all_exempt_reit_shape_redistributes_to_roe_alone():
    # REIT's real shape: AR, ROIC, and CCC are all exempt at once -- only
    # ROE is left, at 100% weight.
    roe = _ratio("good", 90)
    result = score_step4(roe, None, None, None)
    assert result["weights"] == {"roe": 1.0}
    assert result["score"] == 90
    assert result["components"]["revenue_vs_ar"] is None
    assert result["components"]["roic"] is None
    assert result["components"]["ccc"] is None


def test_hard_fail_from_roe_overrides_verdict_despite_good_score():
    roe = _ratio("fail", 0, hard_fail=True)
    ar = _ratio("healthy", 100)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["score"] == 75  # 0*0.25 + 100*0.20 + 100*0.35 + 100*0.20 (coincidentally unchanged from equal-weight)
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_hard_fail_from_roic_overrides_verdict():
    roe = _ratio("excellent", 100)
    ar = _ratio("healthy", 100)
    roic = _ratio("fail", 0, hard_fail=True)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["hard_fail"] is True
    assert result["verdict"] == "Fail"


def test_ar_or_ccc_landing_in_their_own_zero_tier_does_not_hard_fail_but_can_still_fail_on_score():
    # AR/CCC's own worst tiers never set hard_fail (confirmed here --
    # unlike ROE/ROIC's below-floor zone, they're not a hard_fail-style
    # gate). But as of the 2026-08-13 companion-floor fix, a low BLENDED
    # score still correctly reads "Fail" via PASS_SCORE_THRESHOLD -- this
    # test previously asserted "Pass" at a score of 60, which was exactly
    # the masked-Pass gap that fix closed (mirrors Step 5's own
    # PASS_SCORE_THRESHOLD, fixed there first).
    roe = _ratio("excellent", 100)
    ar = _ratio("outpacing_majority_or_red_flag", 0)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("sustained_upward", 0)
    result = score_step4(roe, ar, roic, ccc)
    assert result["score"] == 60  # 100*0.25 + 0*0.20 + 100*0.35 + 0*0.20
    assert result["hard_fail"] is False
    assert result["verdict"] == "Fail"


def test_score_step4_surfaces_roe_roic_divergence_note_without_changing_score():
    # The note is informational only -- it rides alongside the blended
    # score/verdict, never altering them (ROIC's own "marginal" tier
    # already pulled the blend down on its own).
    roe = _ratio("excellent", 100)
    ar = _ratio("healthy", 100)
    roic = _ratio("marginal", 60)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["roe_roic_divergence_note"] is not None
    assert result["score"] == 86  # 100*0.25 + 100*0.20 + 60*0.35 + 100*0.20, unaffected by the note
    assert result["verdict"] == "Pass"


def test_score_step4_no_divergence_note_when_not_applicable():
    roe = _ratio("excellent", 100)
    ar = _ratio("healthy", 100)
    roic = _ratio("excellent", 100)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["roe_roic_divergence_note"] is None


# --- Below-floor graduated scale + companion floor (2026-08-13) -------------


def test_roe_roic_graduated_scale_boundaries():
    # At exactly avg=0 (WEAK_FLOOR_SCORE): floor of the graduated range.
    at_zero = score_roe([0.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert at_zero == ("weak_but_positive", 20, False)

    # Just under avg=8.0 (ROE_MARGINAL_AVG): near the graduated ceiling
    # (55, deliberately below "marginal"'s 60 -- never outranks a real
    # Comfortable-zone result).
    near_marginal = score_roe([7.99] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert near_marginal.label == "weak_but_positive"
    assert near_marginal.points == 55
    assert near_marginal.hard_fail is False

    # avg=8.0 itself is already the "marginal" tier, untouched by this fix.
    at_marginal = score_roe([8.0] * 6, POSITIVE_EQUITY, [10.0] * 6)
    assert at_marginal == ("marginal", 60, False)


def test_ccc_upward_graduated_scale_boundaries():
    # Within CCC_UPWARD_MILD_DAYS (10): flat at the mild ceiling (40).
    mild = classify_ccc_trend([30, 30, 30, 30, 30, 35])  # ~4.2 days
    assert mild.pattern == "sustained_upward"
    assert mild.score == 40

    # Beyond CCC_UPWARD_SEVERE_DAYS (50): flat 0, unchanged from before.
    # (direction is the windowed early-vs-late average, not the raw
    # endpoint jump, so this needs a larger/more sustained spike than it
    # might look like to actually clear the 50-day floor.)
    severe = classify_ccc_trend([30, 30, 30, 30, 30, 30, 200])
    assert severe.pattern == "sustained_upward"
    assert severe.score == 0


def test_step4_companion_floor_fails_a_low_score_with_no_hard_fail_anywhere():
    # The non-negotiable companion to the graduated scale above: a blend
    # that's entirely non-hard_fail (every metric graduated, not a single
    # real breach) can still be a real Fail if the number itself is low.
    # ROE weak_but_positive/20 (the graduated floor), ROIC weak_but_
    # positive/20, AR healthy/100, CCC sustained_upward/0 (still-severe) --
    # blend = 20*0.25 + 20*0.35 + 100*0.20 + 0*0.20 = 5+7+20+0 = 32.
    roe = _ratio("weak_but_positive", 20)
    roic = _ratio("weak_but_positive", 20)
    ar = _ratio("healthy", 100)
    ccc = TrendResult("sustained_upward", 0)
    result = score_step4(roe, ar, roic, ccc)
    assert result["hard_fail"] is False
    assert result["score"] == 32
    assert result["verdict"] == "Fail"


def test_step4_companion_floor_does_not_touch_a_genuine_pass():
    # Sanity check: the floor only ever catches scores that were already
    # going to be Fail-range -- a real, non-hard_fail Pass is unaffected.
    roe = _ratio("good", 85)
    roic = _ratio("marginal", 60)
    ar = _ratio("healthy", 100)
    ccc = TrendResult("declining_or_stable", 100)
    result = score_step4(roe, ar, roic, ccc)
    assert result["hard_fail"] is False
    assert result["score"] == 82  # 85*0.25 + 60*0.35 + 100*0.20 + 100*0.20
    assert result["verdict"] == "Pass"


def test_glw_shaped_roic_and_ccc_stay_fail_with_the_companion_floor():
    # GLW's real shape (the ticker that originally motivated this whole
    # investigation): ROIC weak_but_positive/48 (avg 6.42%, never
    # negative), ROE good/85 (unaffected), AR outpacing_isolated/70, CCC
    # sustained_upward/32 (still ~18 days worse than baseline, not yet
    # recovered). Blend = 85*0.25 + 70*0.20 + 48*0.35 + 32*0.20 = 21.25 +
    # 14 + 16.8 + 6.4 = 58.45 -> 58. Confirms the graduated fix's actual
    # point: an honest 58, not a misleading flat-0-driven 35 -- but still
    # correctly Fail (58 < 70), since GLW's ROIC/CCC genuinely are weak,
    # just not capital-destroying. This is NOT a rescue to Pass.
    roe = _ratio("good", 85)
    roic = _ratio("weak_but_positive", 48)
    ar = _ratio("outpacing_isolated", 70)
    ccc = TrendResult("sustained_upward", 32)
    result = score_step4(roe, ar, roic, ccc)
    assert result["score"] == 58
    assert result["hard_fail"] is False
    assert result["verdict"] == "Fail"
