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
    # -3.0% is within the graduated "mildly_negative" band (>= -10.0%) as of
    # 2026-08-13 -- no longer a flat 0. See the graduated-scale tests below
    # for the severe (still-flat-0) side of the boundary.
    result = score_step2(growth_rate_pct=-3.0, spread_pct=5.0)
    assert result.magnitude_score == 28
    assert result.magnitude_tier == "mildly_negative"


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
    # -5.0% growth is within the graduated "mildly_negative" band -- no
    # longer a flat magnitude 0. magnitude 22 (graduated), agreement 100 ->
    # 0.7*22 + 0.3*100 = 45.4 -> 45. Verdict stays Fail regardless (gated on
    # growth_rate_pct's sign directly, not magnitude_score).
    result = score_step2(growth_rate_pct=-5.0, spread_pct=5.0)
    assert result.magnitude_score == 22
    assert result.score == 45
    assert result.verdict == "Fail"


def test_severely_negative_growth_still_flat_zero():
    # Beyond MAGNITUDE_SEVERE_NEGATIVE (-10.0%), the graduated scale doesn't
    # apply at all -- a genuine projected collapse (SNDK-shaped, -60.0%)
    # must stay at a flat 0, unchanged from before the fix. 0.7*0+0.3*100=30.
    result = score_step2(growth_rate_pct=-60.0, spread_pct=5.0)
    assert result.magnitude_score == 0
    assert result.magnitude_tier == "negative"
    assert result.score == 30
    assert result.verdict == "Fail"


def test_negative_magnitude_graduated_scale_boundaries():
    # At exactly -10.0% (MAGNITUDE_SEVERE_NEGATIVE): floor of the graduated
    # range, 10 points. At -0.03% (DVN-shaped, essentially breakeven):
    # ceiling of the graduated range, 35 points -- deliberately still below
    # the "weak" tier's 40, so a mildly-negative ticker can never outscore a
    # genuinely-positive-but-weak one on magnitude alone.
    at_floor = score_step2(growth_rate_pct=-10.0, spread_pct=5.0)
    assert at_floor.magnitude_score == 10
    assert at_floor.magnitude_tier == "mildly_negative"

    near_zero = score_step2(growth_rate_pct=-0.03, spread_pct=5.0)
    assert near_zero.magnitude_score == 35
    assert near_zero.magnitude_tier == "mildly_negative"

    just_beyond_floor = score_step2(growth_rate_pct=-10.01, spread_pct=5.0)
    assert just_beyond_floor.magnitude_score == 0
    assert just_beyond_floor.magnitude_tier == "negative"


def test_mildly_negative_growth_never_auto_promoted_by_pass_score_floor():
    # Companion-dependency guard: a mildly-negative ticker's magnitude_score
    # is now nonzero, which would trip the OLD `magnitude_score > 0` guard
    # on PASS_SCORE_FLOOR and silently push the score to >=70 ("Pass"-range)
    # -- exactly the false-Pass risk found during the cliff-flattening
    # investigation (the same class of bug Step 4's ROIC/ROE fix needed a
    # companion floor for). Even with a maximally generous agreement score
    # (100, tight spread), DVN-shaped near-zero growth (-0.03%, magnitude
    # 35) must stay well under 70 and Fail: 0.7*35+0.3*100=54.5->54.
    result = score_step2(growth_rate_pct=-0.03, spread_pct=5.0)
    assert result.score == 54
    assert result.score < 70
    assert result.verdict == "Fail"


def test_score_clamped_to_valid_range():
    result = score_step2(growth_rate_pct=50.0, spread_pct=5.0)
    assert 0 <= result.score <= 100


def test_positive_growth_with_low_natural_blend_is_floored_to_70():
    # Solid positive growth (magnitude 85) dragged under 70 by a wide
    # analyst spread (agreement 20) -- natural blend = 0.7*85 + 0.3*20 =
    # 65.5 -> 66, but per the source doc, only negative growth is a fail
    # condition: analyst disagreement alone must never turn this into a
    # Fail. This is the exact AAPL/LRCX scenario that originally motivated
    # that fix -- PASS_SCORE_FLOOR now additionally guarantees the *score*
    # itself can't display a Fail-range number (66) next to a "Pass" verdict
    # (this was FTNT's real shape: score 58, "Pass").
    result = score_step2(growth_rate_pct=13.5, spread_pct=22.2)
    assert result.score == 70
    assert result.verdict == "Pass"


def test_negative_growth_still_fails_regardless_of_agreement():
    # Even a perfectly tight analyst spread (agreement 100) can't rescue
    # negative projected growth -- Fail is gated on growth_rate_pct's sign,
    # not the blended score. -1.0% is within the graduated "mildly_negative"
    # band (magnitude 32): score = 0.7*32 + 0.3*100 = 52.4 -> 52, well above
    # 0, but still Fail. PASS_SCORE_FLOOR must NOT apply here (its guard is
    # `growth_rate_pct >= MAGNITUDE_BORDERLINE`) -- a Fail must still be
    # able to display its real sub-70 score, only a Pass gets floored.
    result = score_step2(growth_rate_pct=-1.0, spread_pct=2.0)
    assert result.score == 52
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


def test_pass_tier_floored_to_70_not_left_below():
    # magnitude 65 (5-10% growth), agreement 20 (wide) -> natural blend
    # 0.7*65+0.3*20=51.5 -> 52, floored to 70 -- a Pass can no longer
    # display a score this low (previously asserted `score < 70`, which
    # was exactly the display-consistency problem PASS_SCORE_FLOOR fixes).
    result = score_step2(growth_rate_pct=7.0, spread_pct=25.0)
    assert result.score == 70
    assert result.verdict == "Pass"


def test_worst_case_weakest_growth_and_widest_spread_still_floors_to_70():
    # The absolute floor of the "score = max(0, min(100, round(...)))"
    # non-negative-growth space: magnitude 40 (the "weak" 0-5% tier, the
    # lowest tier that isn't a Fail) combined with agreement 20 (the widest
    # "wide" spread tier) -- natural blend = 0.7*40+0.3*20 = 34, the lowest
    # a genuinely-positive-growth ticker's raw score can ever be. Confirms
    # the floor catches this extreme, not just FTNT/AAPL's milder cases.
    result = score_step2(growth_rate_pct=1.0, spread_pct=30.0)
    assert result.magnitude_score == 40
    assert result.agreement_score == 20
    assert result.score == 70
    assert result.verdict == "Pass"
