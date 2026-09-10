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
    # Two non-contiguous dip events (100->90, then 95->85); the loop
    # resolves against the FIRST unresolved one it hits (baseline=100 at
    # index 0). TTM (92) vs that baseline is an 8% shortfall, graduated
    # rather than a flat 40 (see MULTIPLE_DIPS_CEILING's own comment in
    # scoring/trend.py).
    pattern, score = classify_trend([100, 90, 95, 85, 92])
    assert pattern == "multiple_dips"
    assert score == 62  # shortfall_frac=8% -> 70 - 30*(0.08/0.30) = 62


def test_dip_without_recovery_counts_as_multiple_dips():
    # A single dip that never gets back to the pre-dip level isn't a clean
    # "recovery" story even though there's only one real decline. baseline
    # (110) vs TTM (88) is a ~20% shortfall -- past the ceiling but still
    # short of MULTIPLE_DIPS_SEVERE_FRAC, so it's graduated between the
    # ceiling and the old flat floor, not pinned to either.
    pattern, score = classify_trend([100, 110, 80, 85, 88])
    assert pattern == "multiple_dips"
    assert score == 50


def test_multiple_dips_graduated_near_ceiling_for_a_near_recovered_dip():
    # Motivating case (see CLAUDE.md's Step 1 deviations): a dip event
    # whose TTM sits only ~1% below its own baseline (100 -> 99) reads as
    # nearly fully recovered in every way that matters, and should score
    # close to MULTIPLE_DIPS_CEILING (70), not the old flat 40 a company
    # in genuine ongoing crisis would also have scored.
    pattern, score = classify_trend([100, 100, 80, 100, 99])
    assert pattern == "multiple_dips"
    assert score == 69  # shortfall_frac=1% -> 70 - 30*(0.01/0.30) = 69


def test_multiple_dips_graduated_mid_range_shortfall():
    # Halfway to MULTIPLE_DIPS_SEVERE_FRAC (15% of a 30% cutoff) lands
    # halfway between the ceiling and floor.
    pattern, score = classify_trend([100, 80, 82, 83, 85])
    assert pattern == "multiple_dips"
    assert score == 55  # shortfall_frac=15% -> 70 - 30*(0.15/0.30) = 55


def test_multiple_dips_graduated_floors_at_the_old_flat_value_beyond_severe_cutoff():
    # At or beyond MULTIPLE_DIPS_SEVERE_FRAC (30% shortfall), the score
    # floors at MULTIPLE_DIPS_FLOOR (40) -- the OLD flat value, preserved
    # so a genuinely severe, still-unresolved dip (SMCI/MRNA/PARA-shaped
    # real cases) never scores BETTER than it did before this fix.
    pattern, score = classify_trend([100, 50, 60, 65, 69])  # exactly at the 30% cutoff
    assert pattern == "multiple_dips"
    assert score == 40

    pattern, score = classify_trend([100, 65, 66, 67, 68])  # well beyond it (32%)
    assert pattern == "multiple_dips"
    assert score == 40


def test_multiple_dips_resolved_scores_below_ceiling_when_both_dips_are_old_and_recovered():
    # 2 real dips, both fully recovered by TTM, both several years before
    # the most recent 2 FYs -- a different risk profile than a dip still
    # resolving now, so this shouldn't collapse into the flat 40 tier.
    # Worst dip depth (95->70, then 70 vs TTM 150) is graduated (2026-09-10)
    # rather than a flat 75 -- see RESOLVED_CEILING's own comment.
    pattern, score = classify_trend([100, 80, 95, 70, 90, 120, 130, 140, 150])
    assert pattern == "multiple_dips_resolved"
    assert score == 73


def test_multiple_dips_resolved_recency_still_irrelevant_once_recovered():
    # 2 real dips, both fully recovered past their own pre-dip peak by TTM,
    # even though the second one is in the most recent 2 FYs before TTM --
    # recency still doesn't matter once recovery is confirmed (see
    # CLAUDE.md's Step 1 deviations); severity (not recency) is what's now
    # graduated, as of 2026-09-10.
    pattern, score = classify_trend([100, 80, 110, 140, 170, 200, 160, 210, 230])
    assert pattern == "multiple_dips_resolved"
    assert score == 73


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
    # fix existed. baseline=200 vs TTM=95 is a 52.5% shortfall -- well
    # beyond MULTIPLE_DIPS_SEVERE_FRAC, so this still floors at 40.
    pattern, score = classify_trend([50, 60, 100, 200, 90, 95])
    assert pattern == "multiple_dips"
    assert score == 40


def test_multi_dip_path_also_uses_the_spike_aware_baseline():
    # 2 real dips: the first (450 -> 150) follows a genuine >100% spike and
    # should be measured against the pre-spike value (150); the second
    # (300 -> 250) is an ordinary dip. Both recover under the fixed logic.
    # Score graduated (2026-09-10) by whichever event's depth is worst
    # relative to current (TTM) scale, rather than a flat 75.
    pattern, score = classify_trend([100, 150, 450, 150, 300, 250, 400])
    assert pattern == "multiple_dips_resolved"
    assert score == 74


def test_flat_then_spike():
    # Terminal jump (103 -> 210, +103.9%) is deliberately just past
    # DIP_BASELINE_SPIKE_RATIO -- past the fix below, a jump this large gets
    # NO protect_terminal benefit (still excluded as the late window's own
    # outlier), so this keeps testing the original "flat, then an
    # untrusted spike" shape unchanged. A more modest jump (<=100%) that
    # also shows real underlying improvement is now handled differently --
    # see test_flat_then_spike_protects_a_plausible_ttm_jump_that_clears_
    # its_own_prior_peak (2026-08-13 fix).
    pattern, score = classify_trend([100, 90, 106, 88, 103, 210])
    assert pattern == "flat_then_spike"
    assert score == 20


def test_declining_including_ttm():
    # TTM decline is -24.8% -- within the graduated zone (2026-08-13 fix:
    # 15%-50%), so no longer a flat 0. See the graduated-scale tests below
    # for the boundary/floor behavior.
    pattern, score = classify_trend([100, 110, 121, 133, 100])
    assert pattern == "declining"
    assert score == 11


def test_ttm_decline_overrides_otherwise_clean_growth():
    # 4 clean growth years, then TTM drops -- disqualifying regardless of
    # history. -17.3% is within the graduated zone (2026-08-13 fix), so no
    # longer a flat 0 -- still the lowest tier available, just an honest
    # near-boundary number.
    pattern, score = classify_trend([100, 110, 121, 133, 110])
    assert pattern == "declining"
    assert score == 14


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
    # Worst (only) event's depth (140->50) equals TTM (90) itself -- a
    # worst_frac of exactly 1.0, clipped at RESOLVED_SEVERE_FRAC, so this
    # floors at RESOLVED_FLOOR (65) rather than the old flat 75.
    pattern, score = classify_trend([140, 120, 95, 50, 60, 70, 80, 90])
    assert pattern == "dip_durably_resolved"
    assert score == 65


def test_merged_dip_event_still_multiple_dips_when_too_recent():
    # Same shape as above, one year short -- age=3 fails
    # DIP_RESOLUTION_MIN_AGE, so it's too recent to durably resolve.
    # baseline=140 vs TTM=80 is a 42.9% shortfall -- beyond
    # MULTIPLE_DIPS_SEVERE_FRAC, so this still floors at the old flat 40.
    pattern, score = classify_trend([140, 120, 95, 50, 60, 70, 80])
    assert pattern == "multiple_dips"
    assert score == 40


def test_merged_dip_event_still_multiple_dips_when_recovery_run_too_short():
    # The original 2018-shaped decline is comfortably old, but a fresh,
    # real (>5%) relapse lands right before TTM -- breaks the trailing
    # clean-run requirement, so the old event can't be excused even though
    # its own age would otherwise qualify. baseline=140 vs TTM=92 is a
    # 34.3% shortfall -- still beyond MULTIPLE_DIPS_SEVERE_FRAC, floors at 40.
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
    # dip tier instead of the old flat, unconditional 0. baseline=146 vs
    # TTM=135 is an 8% shortfall -- since 2026-09-10, graduated rather
    # than a flat 40 (see MULTIPLE_DIPS_CEILING's own comment).
    pattern, score = classify_trend([100, 110, 121, 133, 146, 135])
    assert pattern == "multiple_dips"
    assert score == 62  # shortfall_frac=8% -> 70 - 30*(0.08/0.30) = 62


def test_ttm_decline_inside_graduated_band_not_forced_to_zero():
    # -14%, comfortably inside the graduated band -- must not hit the
    # SEVERE_TTM_DECLINE hard override.
    pattern, score = classify_trend([100, 110, 121, 133, 133 * 0.86])
    assert pattern != "declining"


def test_ttm_decline_beyond_severe_threshold_still_declining():
    # -16%, beyond SEVERE_TTM_DECLINE -- the `declining` override still
    # applies unconditionally (a milder decline flows through as an
    # ordinary dip transition instead, see the graduated-band tests
    # above). Points are graduated as of 2026-08-13 -- -16% sits just past
    # the 15% boundary, near the graduated ceiling (15), not a flat 0.
    pattern, score = classify_trend([100, 110, 121, 133, 133 * 0.84])
    assert pattern == "declining"
    assert score == 15


def test_declining_graduated_scale_boundaries():
    # 2026-08-13 fix: `declining`'s points are no longer a flat 0. Just
    # past SEVERE_TTM_DECLINE (-15.1%, since exactly -15.0% doesn't trigger
    # `declining` at all -- the check is strictly-less-than): ceiling of
    # the graduated range, 15 points. Beyond DECLINING_FLOOR_DECLINE
    # (-50%): flat 0, unchanged -- a genuinely severe collapse must stay
    # maximally bad.
    at_boundary = classify_trend([100, 100, 100, 100, 84.9])
    assert at_boundary.pattern == "declining"
    assert at_boundary.score == 15

    beyond_floor = classify_trend([100, 100, 100, 100, 40.0])  # -60%
    assert beyond_floor.pattern == "declining"
    assert beyond_floor.score == 0

    at_floor = classify_trend([100, 100, 100, 100, 50.0])  # exactly -50%
    assert at_floor.pattern == "declining"
    assert at_floor.score == 0


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
    # Same fixture as test_flat_then_spike (jump kept past
    # DIP_BASELINE_SPIKE_RATIO so protect_terminal doesn't engage): robust-
    # late-vs-early is slightly NEGATIVE here even excluding the terminal
    # spike, so the narrowing doesn't rescue it -- still genuinely "flat,
    # then a lone spike".
    pattern, score = classify_trend([100, 90, 106, 88, 103, 210])
    assert pattern == "flat_then_spike"
    assert score == 20


def test_flat_then_spike_protects_a_plausible_ttm_jump_that_clears_its_own_prior_peak():
    # GLW's real CFO shape (2026-08-13 investigation): flat arr[0] vs
    # arr[-2] (+7.8%) and a +45.3% TTM jump both trip the flat_then_spike
    # entry gate, and the unprotected robust_late_direction check discards
    # TTM as the late window's own outlier -- throwing out the one number
    # that's actual evidence of recovery. TTM (3915) is a LITERAL new high
    # above the 2021 peak (3412, +14.7%), and the jump into it (+45.3%)
    # isn't itself spike-sized, so it should be protected and the series
    # should fall through to ordinary dip-event resolution instead.
    # Score graduated (2026-09-10) by dip-depth-vs-current-scale severity
    # rather than a flat 75 -- see RESOLVED_CEILING's own comment.
    pattern, score = classify_trend([2500, 2004, 2919, 2031, 2180, 3412, 2615, 2005, 1939, 2695, 3915])
    assert pattern != "flat_then_spike"
    assert pattern == "multiple_dips_resolved"
    assert score == 71


# --- Resolved-bucket (multiple_dips_resolved/dip_durably_resolved)
# graduated severity (2026-09-10) --------------------------------------


def test_resolved_graduated_near_ceiling_for_a_dip_trivial_relative_to_current_scale():
    # Two non-contiguous, fully-recovered dips (worst depth 70, vs TTM
    # 1000) -- a mild historical dip relative to today's scale, so this
    # should land close to RESOLVED_CEILING (75), not far below it.
    pattern, score = classify_trend([1000, 930, 970, 920, 999, 1000, 1010, 1000])
    assert pattern == "multiple_dips_resolved"
    assert score == 74  # worst_frac=7% -> 75 - 10*(0.07/1.0) = 74


def test_resolved_graduated_mid_range_severity():
    # Worst dip depth (100->50) is exactly 50% of TTM (100) -- halfway
    # between RESOLVED_CEILING and RESOLVED_FLOOR.
    pattern, score = classify_trend([100, 50, 60, 55, 70, 80, 100])
    assert pattern == "multiple_dips_resolved"
    assert score == 70  # worst_frac=50% -> 75 - 10*(0.50/1.0) = 70


def test_resolved_graduated_floors_at_resolved_floor_for_abnb_bkr_shaped_severity():
    # ABNB/BKR-shaped: a historical loss (trough -50) deeper than the
    # company's own current (TTM) scale (100) -- worst_frac=150%, clipped
    # to RESOLVED_SEVERE_FRAC (100%), so this floors at RESOLVED_FLOOR (65)
    # -- the same floor a trivially-mild resolved dip would never reach.
    pattern, score = classify_trend([100, -50, 80, 90, 70, 100])
    assert pattern == "multiple_dips_resolved"
    assert score == 65


def test_flat_then_spike_stays_unprotected_for_a_jump_with_no_precedent_in_the_series():
    # NBIS's real CFO shape: TTM (3011.9) is a 682.9% jump over the prior
    # year (384.8), itself a >=100% one-off-sized move with zero precedent
    # anywhere in 10 years of history (prior range: 124.6-829.8) -- exactly
    # the "spurious terminal spike" flat_then_spike exists to catch. The
    # jump-size gate must NOT protect TTM here; must still read
    # flat_then_spike/20, unchanged from before the fix.
    pattern, score = classify_trend([412.958731, 412.206457, 405.970699, 715.833272, 438.197771, 124.619122, 697.0, 829.8, 245.6, 384.8, 3011.9])
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
