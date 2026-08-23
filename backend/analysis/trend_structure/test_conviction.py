import pytest

from analysis.trend_structure.conviction import compute_bar_level, compute_blended_score


def test_blended_score_max_uptrend_conviction_reaches_positive_ceiling():
    score = compute_blended_score(
        trend_state="uptrend",
        magnitude_tier="strong",
        persistence_count=10,
        bars_since_confirmation=0,
        regime="trending",
        warning_flag=False,
    )
    # tier_score=1.0, persistence_score=1.0, recency_score=1.0 ->
    # conviction = 0.5+0.3+0.2 = 1.0, no discounts -> blended = +1 * 1.0 * 10
    assert score == pytest.approx(10.0)


def test_blended_score_max_downtrend_conviction_reaches_negative_floor():
    score = compute_blended_score(
        trend_state="downtrend",
        magnitude_tier="strong",
        persistence_count=10,
        bars_since_confirmation=0,
        regime="trending",
        warning_flag=False,
    )
    assert score == pytest.approx(-10.0)


def test_blended_score_applies_regime_and_warning_discounts():
    score = compute_blended_score(
        trend_state="uptrend",
        magnitude_tier="weak",
        persistence_count=1,
        bars_since_confirmation=30,
        regime="range-bound",
        warning_flag=True,
    )
    # tier_score=0.33, persistence_score=0.1, recency_score=0 (30/30 -> max(0, 1-1)=0)
    # conviction = 0.5*0.33 + 0.3*0.1 + 0.2*0 = 0.195
    # *0.7 (range-bound) *0.7 (warning) = 0.09555 -> *10 = 0.9555
    assert score == pytest.approx(0.9555, abs=1e-4)


def test_blended_score_persistence_count_is_capped_at_ten():
    score_at_cap = compute_blended_score(
        trend_state="uptrend", magnitude_tier="weak", persistence_count=10, bars_since_confirmation=None, regime="trending", warning_flag=False
    )
    score_above_cap = compute_blended_score(
        trend_state="uptrend", magnitude_tier="weak", persistence_count=50, bars_since_confirmation=None, regime="trending", warning_flag=False
    )
    assert score_at_cap == pytest.approx(score_above_cap)


def test_blended_score_none_magnitude_tier_and_none_bars_since_confirmation_score_zero_contribution():
    score = compute_blended_score(
        trend_state="uptrend", magnitude_tier=None, persistence_count=0, bars_since_confirmation=None, regime=None, warning_flag=False
    )
    assert score == pytest.approx(0.0)


def test_ad_bullish_divergence_boosts_score_only_on_uptrend():
    base_kwargs = dict(magnitude_tier="strong", persistence_count=10, bars_since_confirmation=0, regime="trending", warning_flag=False)

    boosted = compute_blended_score(trend_state="uptrend", ad_bullish_divergence=True, **base_kwargs)
    unboosted = compute_blended_score(trend_state="uptrend", ad_bullish_divergence=False, **base_kwargs)

    assert boosted == pytest.approx(unboosted * 1.15)


def test_ad_bullish_divergence_never_boosts_downtrend():
    base_kwargs = dict(magnitude_tier="strong", persistence_count=10, bars_since_confirmation=0, regime="trending", warning_flag=False)

    with_divergence = compute_blended_score(trend_state="downtrend", ad_bullish_divergence=True, **base_kwargs)
    without_divergence = compute_blended_score(trend_state="downtrend", ad_bullish_divergence=False, **base_kwargs)

    assert with_divergence == pytest.approx(without_divergence)


def test_ad_bullish_divergence_defaults_to_no_boost_when_omitted():
    base_kwargs = dict(
        trend_state="uptrend", magnitude_tier="strong", persistence_count=10, bars_since_confirmation=0, regime="trending", warning_flag=False
    )

    assert compute_blended_score(**base_kwargs) == pytest.approx(compute_blended_score(ad_bullish_divergence=False, **base_kwargs))


def test_ad_bullish_divergence_boost_applies_after_regime_and_warning_dampeners():
    """The booster must multiply the FINAL (regime- and warning-discounted)
    blended score, not an intermediate value -- confirmed by checking the
    boosted/unboosted ratio stays exactly 1.15x even with both dampeners
    active."""
    dampened_kwargs = dict(
        trend_state="uptrend", magnitude_tier="weak", persistence_count=1, bars_since_confirmation=30, regime="range-bound", warning_flag=True
    )

    boosted = compute_blended_score(ad_bullish_divergence=True, **dampened_kwargs)
    unboosted = compute_blended_score(ad_bullish_divergence=False, **dampened_kwargs)

    assert boosted == pytest.approx(unboosted * 1.15, rel=1e-9)


@pytest.mark.parametrize(
    "score,expected_bar_level",
    [
        (-10.0, 1),
        (-8.0, 1),
        (-6.0001, 1),
        (-6.0, 2),  # exact table boundary -- belongs to band 2 per the corrected formula
        (-4.0, 2),
        (-2.0001, 2),
        (-2.0, 3),
        (0.0, 3),
        (1.9999, 3),
        (2.0, 4),
        (4.0, 4),
        (5.9999, 4),
        (6.0, 5),
        (8.0, 5),
        (10.0, 5),
    ],
)
def test_bar_level_bands_match_the_reference_table(score, expected_bar_level):
    assert compute_bar_level(score) == expected_bar_level
