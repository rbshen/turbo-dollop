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
