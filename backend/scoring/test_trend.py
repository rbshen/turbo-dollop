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
