from scoring.trend import classify_trend


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
    assert score == 70


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


def test_multiple_dips_recent_scores_60_when_a_dip_is_in_the_last_two_fys():
    # 2 real dips, both fully recovered, but the second one lands in the
    # most recent 2 FYs before TTM -- still resolving recently enough to
    # score lower than a long-resolved dip.
    pattern, score = classify_trend([100, 80, 110, 140, 170, 200, 160, 210, 230])
    assert pattern == "multiple_dips_recent"
    assert score == 60


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
