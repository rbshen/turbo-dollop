from scoring.step2 import score_step2


def test_magnitude_high_growth():
    result = score_step2(growth_rate_pct=20.0, spread_pct=5.0)
    assert result.magnitude_score == 100


def test_magnitude_solid_growth_boundary_inclusive():
    # Exactly 15% falls in the 10-15 bucket (85), not the >15 bucket (100).
    result = score_step2(growth_rate_pct=15.0, spread_pct=5.0)
    assert result.magnitude_score == 85


def test_magnitude_modest_growth():
    result = score_step2(growth_rate_pct=7.0, spread_pct=5.0)
    assert result.magnitude_score == 65


def test_magnitude_borderline_growth():
    result = score_step2(growth_rate_pct=2.0, spread_pct=5.0)
    assert result.magnitude_score == 40


def test_magnitude_negative_growth():
    result = score_step2(growth_rate_pct=-3.0, spread_pct=5.0)
    assert result.magnitude_score == 0


def test_agreement_tight_spread():
    result = score_step2(growth_rate_pct=20.0, spread_pct=9.0)
    assert result.agreement_score == 100


def test_agreement_moderate_spread_boundaries_inclusive():
    result = score_step2(growth_rate_pct=20.0, spread_pct=10.0)
    assert result.agreement_score == 60
    result = score_step2(growth_rate_pct=20.0, spread_pct=20.0)
    assert result.agreement_score == 60


def test_agreement_wide_spread():
    result = score_step2(growth_rate_pct=20.0, spread_pct=25.0)
    assert result.agreement_score == 20


def test_combined_weighting_strong_pass():
    # magnitude 100, agreement 100 -> 0.7*100 + 0.3*100 = 100
    result = score_step2(growth_rate_pct=20.0, spread_pct=5.0)
    assert result.score == 100
    assert result.verdict == "Strong Pass"


def test_combined_weighting_pass():
    # magnitude 100, agreement 20 -> 0.7*100 + 0.3*20 = 76
    result = score_step2(growth_rate_pct=20.0, spread_pct=25.0)
    assert result.score == 76
    assert result.verdict == "Pass"


def test_combined_weighting_fail():
    # magnitude 0, agreement 100 -> 0.7*0 + 0.3*100 = 30
    result = score_step2(growth_rate_pct=-5.0, spread_pct=5.0)
    assert result.score == 30
    assert result.verdict == "Fail"


def test_score_clamped_to_valid_range():
    result = score_step2(growth_rate_pct=50.0, spread_pct=5.0)
    assert 0 <= result.score <= 100


def test_positive_growth_with_low_score_still_passes():
    # Solid positive growth (magnitude 85) dragged under 70 by a wide
    # analyst spread (agreement 20) -- score = 0.7*85 + 0.3*20 = 65.5 -> 66,
    # but per the source doc, only negative growth is a fail condition:
    # analyst disagreement alone must never turn this into a Fail. This is
    # the exact AAPL/LRCX scenario that motivated the fix.
    result = score_step2(growth_rate_pct=13.5, spread_pct=22.2)
    assert result.score < 70
    assert result.verdict == "Pass"


def test_negative_growth_still_fails_regardless_of_agreement():
    # Even a perfectly tight analyst spread (agreement 100) can't rescue
    # negative projected growth -- Fail is gated on the magnitude tier, not
    # the blended score. score = 0.7*0 + 0.3*100 = 30, well above 0, but
    # still Fail.
    result = score_step2(growth_rate_pct=-1.0, spread_pct=2.0)
    assert result.verdict == "Fail"


def test_zero_growth_is_borderline_not_fail():
    # Exactly 0% growth is the boundary of the doc's "borderline" tier
    # (0-5%), not negative -- must not fail.
    result = score_step2(growth_rate_pct=0.0, spread_pct=50.0)
    assert result.verdict == "Pass"


def test_pass_tier_strong_pass_above_90():
    result = score_step2(growth_rate_pct=20.0, spread_pct=5.0)  # score 100
    assert result.verdict == "Strong Pass"


def test_pass_tier_pass_at_75_to_90():
    result = score_step2(growth_rate_pct=20.0, spread_pct=25.0)  # score 76
    assert 75 <= result.score <= 90
    assert result.verdict == "Pass"


def test_pass_tier_pass_below_70():
    # magnitude 65 (5-10% growth), agreement 20 (wide) -> 0.7*65+0.3*20=51.5 -> 52
    result = score_step2(growth_rate_pct=7.0, spread_pct=25.0)
    assert result.score < 70
    assert result.verdict == "Pass"
