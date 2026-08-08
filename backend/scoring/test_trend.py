from scoring.trend import classify_trend, most_recent_real_dip_age, resolved_dip_events


def test_insufficient_data():
    assert classify_trend([]) == ("insufficient_data", 0)
    assert classify_trend([100.0]) == ("insufficient_data", 0)


def test_grows_every_year():
    pattern, score = classify_trend([100, 110, 121, 133, 146])
    assert pattern == "grows_every_year"
    assert score == 100


def test_small_dip_recovers():
    # ~-7% dip mid-series, fully recovers and exceeds the pre-dip peak by TTM.
    pattern, score = classify_trend([100, 110, 102, 120, 130])
    assert pattern == "small_dip_recovers"
    assert score == 90


def test_significant_dip_recovers():
    # -20% dip, recovers past the pre-dip peak by TTM.
    pattern, score = classify_trend([100, 110, 88, 105, 115])
    assert pattern == "significant_dip_recovers"
    assert score == 85


def test_multiple_dips():
    pattern, score = classify_trend([100, 90, 95, 85, 92])
    assert pattern == "multiple_dips"
    assert score == 40


def test_dip_without_recovery_counts_as_multiple_dips():
    # A single dip that never gets back to the pre-dip level isn't a clean
    # "recovery" story even though there's only one real decline.
    pattern, score = classify_trend([100, 110, 80, 85, 88])
    assert pattern == "multiple_dips"
    assert score == 40


def test_multiple_dips_resolved_scores_75_when_both_dips_are_old_and_recovered():
    # 2 real dips, both fully recovered by TTM, both several years before
    # the most recent 2 FYs -- a different risk profile than a dip still
    # resolving now, so this shouldn't collapse into the flat 40 tier.
    pattern, score = classify_trend([100, 80, 95, 70, 90, 120, 130, 140, 150])
    assert pattern == "multiple_dips_resolved"
    assert score == 75


def test_multiple_dips_resolved_scores_75_even_when_the_recovered_dip_is_recent():
    # 2 real dips, both fully recovered past their own pre-dip peak by TTM,
    # even though the second one is in the most recent 2 FYs before TTM --
    # recency no longer matters once recovery is confirmed (see CLAUDE.md's
    # Step 1 deviations); this used to score 60 for the recent dip.
    pattern, score = classify_trend([100, 80, 110, 140, 170, 200, 160, 210, 230])
    assert pattern == "multiple_dips_resolved"
    assert score == 75


def test_dip_recovery_measured_against_pre_spike_baseline_not_the_spike_itself():
    # Mirrors MPWR's real shape: a genuine, durable growth trajectory
    # (100 -> 110 -> 120) interrupted by a one-time >100% spike (120 -> 450,
    # a one-off tax benefit) that then reverts (450 -> 200). TTM (210) never
    # climbs back to the fake spike value (450), but comfortably clears the
    # last genuine pre-spike value (120) -- this must read as a real,
    # recovered dip, not a permanently-uncapped "multiple_dips".
    pattern, score = classify_trend([100, 110, 120, 450, 200, 210])
    assert pattern == "significant_dip_recovers"
    assert score == 85


def test_dip_baseline_fallback_requires_more_than_a_100_percent_jump():
    # Boundary: the jump before the dip is EXACTLY +100% (ratio == 1.0, not
    # > 1.0) -- the fallback must not trigger, so recovery is still measured
    # against the (non-fallback) pre-dip value directly, same as before this
    # fix existed.
    pattern, score = classify_trend([50, 60, 100, 200, 90, 95])
    assert pattern == "multiple_dips"
    assert score == 40


def test_multi_dip_path_also_uses_the_spike_aware_baseline():
    # 2 real dips: the first (450 -> 150) follows a genuine >100% spike and
    # should be measured against the pre-spike value (150); the second
    # (300 -> 250) is an ordinary dip. Both recover under the fixed logic.
    pattern, score = classify_trend([100, 150, 450, 150, 300, 250, 400])
    assert pattern == "multiple_dips_resolved"
    assert score == 75


def test_flat_then_spike():
    pattern, score = classify_trend([100, 90, 106, 88, 103, 145])
    assert pattern == "flat_then_spike"
    assert score == 20


def test_declining_including_ttm():
    pattern, score = classify_trend([100, 110, 121, 133, 100])
    assert pattern == "declining"
    assert score == 0


def test_ttm_decline_overrides_otherwise_clean_growth():
    # 4 clean growth years, then TTM drops -- disqualifying regardless of history.
    pattern, score = classify_trend([100, 110, 121, 133, 110])
    assert pattern == "declining"
    assert score == 0


def test_noise_floor_ignores_tiny_moves():
    pattern, score = classify_trend([100, 100.5, 100.2, 100.8, 101])
    assert pattern == "grows_every_year"
    assert score == 100


def test_negative_base_value_handled_without_crashing():
    pattern, score = classify_trend([-10, 5, 10, 15])
    assert score >= 0


def test_most_recent_real_dip_age_no_dips():
    assert most_recent_real_dip_age([100, 110, 121, 133, 146]) is None


def test_most_recent_real_dip_age_dip_lands_in_ttm_transition():
    assert most_recent_real_dip_age([100, 110, 90]) == 0


def test_most_recent_real_dip_age_dip_several_years_back():
    assert most_recent_real_dip_age([100, 40, 45, 50, 55]) == 3


def test_most_recent_real_dip_age_insufficient_data():
    assert most_recent_real_dip_age([]) is None
    assert most_recent_real_dip_age([100]) is None


def test_most_recent_real_dip_age_ignores_sub_noise_floor_wobbles():
    assert most_recent_real_dip_age([100, 100.5, 99, 105]) is None


# --- Dip-event merging + age-aware durable resolution (2026-08-08 fix) -----


def test_contiguous_dip_transitions_merge_into_one_event():
    # HWM-shaped: a 3-transition decline (140 -> 120 -> 95 -> 50) is ONE
    # real economic event, not three independent dips each needing its own
    # recovery. Old enough (age=4) with a long enough clean recovery run
    # (4 periods) and genuine improvement since the trough -- durably
    # resolved even though TTM (90) never re-exceeds the pre-decline
    # baseline (140).
    pattern, score = classify_trend([140, 120, 95, 50, 60, 70, 80, 90])
    assert pattern == "dip_durably_resolved"
    assert score == 75


def test_merged_dip_event_still_multiple_dips_when_too_recent():
    # Same shape as above, one year short -- age=3 fails
    # DIP_RESOLUTION_MIN_AGE, so it's too recent to durably resolve.
    pattern, score = classify_trend([140, 120, 95, 50, 60, 70, 80])
    assert pattern == "multiple_dips"
    assert score == 40


def test_merged_dip_event_still_multiple_dips_when_recovery_run_too_short():
    # The original 2018-shaped decline is comfortably old, but a fresh,
    # real (>5%) relapse lands right before TTM -- breaks the trailing
    # clean-run requirement, so the old event can't be excused even though
    # its own age would otherwise qualify.
    pattern, score = classify_trend([140, 120, 95, 50, 60, 70, 80, 90, 100, 92])
    assert pattern == "multiple_dips"
    assert score == 40


def test_merged_dip_event_literal_recovery_uses_aggregate_magnitude():
    # A merged (start != end) event that DOES literally recover by TTM
    # (150 >= the pre-decline baseline of 140) must grade its severity off
    # the aggregate baseline-vs-trough magnitude (-64.3%), not any single
    # transition within the run -- no single transition represents a
    # merged, multi-leg decline.
    pattern, score = classify_trend([140, 120, 95, 50, 60, 70, 80, 150])
    assert pattern == "significant_dip_recovers"
    assert score == 85


def test_ttm_decline_within_graduated_band_flows_through_as_ordinary_dip():
    # 4 clean growth years then a -7.5% TTM dip -- inside the graduated
    # band (NOISE_FLOOR < decline < SEVERE_TTM_DECLINE) and too recent
    # (age=0) to durably resolve, so it lands on the ordinary unrecovered-
    # dip tier instead of the old flat, unconditional 0.
    pattern, score = classify_trend([100, 110, 121, 133, 146, 135])
    assert pattern == "multiple_dips"
    assert score == 40


def test_ttm_decline_inside_graduated_band_not_forced_to_zero():
    # -14%, comfortably inside the graduated band -- must not hit the
    # SEVERE_TTM_DECLINE hard override.
    pattern, score = classify_trend([100, 110, 121, 133, 133 * 0.86])
    assert pattern != "declining"


def test_ttm_decline_beyond_severe_threshold_still_declining():
    # -16%, beyond SEVERE_TTM_DECLINE -- the hard override still applies
    # unconditionally, same as the pre-existing behavior for a severe drop.
    pattern, score = classify_trend([100, 110, 121, 133, 133 * 0.84])
    assert pattern == "declining"
    assert score == 0


def test_flat_then_spike_narrowed_by_robust_late_direction():
    # HON-shaped: arr[0] vs arr[-2] reads flat (the old 2-point check would
    # fire flat_then_spike), but the robust late-window average (single
    # most extreme point excluded) is ~11% above the early window even
    # setting the terminal jump aside -- genuine multi-year improvement the
    # 2-point check can't see, so it falls through to ordinary dip-event
    # resolution instead of the flat 20.
    pattern, score = classify_trend([100, 40, 130, 90, 105, 95, 210])
    assert pattern != "flat_then_spike"


def test_flat_then_spike_still_fires_when_no_meaningful_prior_improvement():
    # Existing fixture, unchanged: robust-late-vs-early is slightly
    # NEGATIVE here even excluding the terminal spike, so the narrowing
    # doesn't rescue it -- still genuinely "flat, then a lone spike".
    pattern, score = classify_trend([100, 90, 106, 88, 103, 145])
    assert pattern == "flat_then_spike"
    assert score == 20


def test_resolved_dip_events_hwm_shaped_merged_event():
    # Same fixture as test_contiguous_dip_transitions_merge_into_one_event
    # -- classify_trend reads this whole series as one durably-resolved
    # merged event; resolved_dip_events should return that exact event.
    events = resolved_dip_events([140, 120, 95, 50, 60, 70, 80, 90])
    assert len(events) == 1
    assert events[0].start == 0 and events[0].end == 2
    assert events[0].baseline == 140.0
    assert events[0].trough == 50.0


def test_resolved_dip_events_returns_only_the_resolved_event_not_all_events():
    # Two independent, non-contiguous dip events: an early, deep dip off a
    # small baseline (TTM comfortably clears it -- literally resolved) and
    # a recent, shallow dip off a much higher baseline (age=1, far too
    # recent to durably resolve, and TTM never comes close to clearing it
    # literally either). classify_trend gives up entirely on this series
    # (multiple_dips/40, since it early-exits at the first unresolved
    # event) -- resolved_dip_events must NOT share that early-exit: it
    # should still surface the one event that genuinely did resolve.
    series = [10, 4, 50, 48, 46, 44, 42, 40, 20, 21]
    assert classify_trend(series).pattern == "multiple_dips"
    events = resolved_dip_events(series)
    assert len(events) == 1
    assert events[0].start == 0 and events[0].end == 0
    assert events[0].baseline == 10.0


def test_resolved_dip_events_no_dips_returns_empty():
    assert resolved_dip_events([100, 110, 120, 130]) == []


def test_resolved_dip_events_insufficient_data_returns_empty():
    assert resolved_dip_events([100]) == []
    assert resolved_dip_events([]) == []
