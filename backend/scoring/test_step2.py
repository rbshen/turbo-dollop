from scoring.step2 import NEGATIVE_MAGNITUDE_CEILING, PASS_SCORE, _verdict_for, score_step2
from scoring.weights import BOUNDS, Step2Weights


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
    # 0.7*22 + 0.3*100 = 45.4 -> 45, which is under the 70 line, so the verdict
    # (which follows the score alone) is Fail.
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
    # is nonzero, which would trip a `magnitude_score > 0` guard on
    # PASS_SCORE_FLOOR and silently push the score to >=70 (the floor is gated
    # on the sign of the growth rate instead). Even with a maximally generous agreement score
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


def test_negative_growth_with_perfect_agreement_scores_under_70_and_fails_without_an_override():
    # Even a perfectly tight analyst spread (agreement 100) can't rescue negative projected growth. There is no negative-growth
    # override (removed 2026-10-08): the verdict follows the score. -1.0% is within the graduated "mildly_negative" band
    # (magnitude 32): score = 0.7*32 + 0.3*100 = 52.4 -> 52, under 70, so the stored verdict is Fail. PASS_SCORE_FLOOR must NOT
    # apply here (its guard is `growth_rate_pct >= MAGNITUDE_BORDERLINE`), so the sub-70 score is shown as it is.
    result = score_step2(growth_rate_pct=-1.0, spread_pct=2.0)
    assert result.agreement_score == 100
    assert result.score == 52
    assert result.verdict == "Fail"


def test_verdict_follows_the_score_line():
    # 70 passes, 69 does not, above 90 is Strong Pass. Reached through the pure helper, since a real input cannot land a
    # sub-70 score on a non-negative rate (the floor) or a 70+ score on a negative one (the ceiling).
    assert _verdict_for(69) == "Fail"
    assert _verdict_for(70) == "Pass"
    assert _verdict_for(90) == "Pass"
    assert _verdict_for(91) == "Strong Pass"


def test_positive_growth_behaviour_unchanged():
    # Weak (0-5%) growth, wide spread: natural blend 0.7*40 + 0.3*20 = 34, floored to 70 and still a Pass; never Strong Pass.
    weak = score_step2(growth_rate_pct=0.1, spread_pct=25.0)
    assert (weak.score, weak.verdict) == (70, "Pass")
    # Exactly 0% is non-negative: floored and Pass.
    zero = score_step2(growth_rate_pct=0.0, spread_pct=25.0)
    assert (zero.score, zero.verdict) == (70, "Pass")
    # A natural 76 stays 76 (the floor only lifts), 100 is Strong Pass.
    assert score_step2(growth_rate_pct=20.0, spread_pct=25.0).verdict == "Pass"
    assert score_step2(growth_rate_pct=20.0, spread_pct=5.0).verdict == "Strong Pass"


def test_every_non_negative_growth_rate_passes_at_every_allowed_weight_set():
    # The other side of the guard below: the 70 floor means a non-negative rate never reads Fail, whatever the spread or weights.
    for magnitude in range(50, 101, 5):
        weights = Step2Weights(magnitude=magnitude, agreement=100 - magnitude)
        for growth in (0.0, 0.1, 2.5, 7.0, 12.0, 20.0):
            for spread in (1.0, 15.0, 40.0):
                assert score_step2(growth, spread, weights).verdict in ("Pass", "Strong Pass")


def test_negative_growth_ceiling_stays_below_pass_line_at_loosest_weights():
    # REGRESSION GUARD for removing the negative-growth hard fail (2026-10-08). The verdict follows the score alone, so the
    # only thing keeping a negative growth rate from passing is that its score cannot reach 70. That rests on the Magnitude
    # curve ceiling for negative rates (NEGATIVE_MAGNITUDE_CEILING = 35) and the weight bounds (Magnitude at least 50,
    # Agreement at most 50). A change to the curve or the bounds that lets a negative rate reach 70 must fail here.
    magnitude_low, magnitude_high = BOUNDS["step2"]["magnitude"]
    agreement_low, agreement_high = BOUNDS["step2"]["agreement"]
    assert (magnitude_low, agreement_high) == (50, 50)
    loosest = Step2Weights(magnitude=magnitude_low, agreement=100 - magnitude_low)
    # Every allowed split, Agreement at its best (spread 0 -> 100 points), growth swept across the whole negative range
    # including the points nearest 0% where Magnitude is highest.
    rates = [-1e-9, -0.001, -0.03, -0.1, -0.5, -1, -2.5, -5, -9.99, -10, -10.01, -25, -60, -99.9]
    for magnitude in range(magnitude_low, magnitude_high + 1):
        weights = Step2Weights(magnitude=magnitude, agreement=100 - magnitude)
        if not agreement_low <= weights.agreement <= agreement_high:
            continue
        for rate in rates:
            result = score_step2(rate, spread_pct=0.0, weights=weights)
            assert result.agreement_score == 100
            assert result.score < 70, (magnitude, rate, result)
            assert result.verdict == "Fail", (magnitude, rate, result)
    # The worst case in numbers: Magnitude 35 (best negative) at 50/50 with Agreement 100 = 67.5, and 54.5 at the 70/30 default.
    worst = score_step2(-1e-9, spread_pct=0.0, weights=loosest)
    assert worst.magnitude_score == NEGATIVE_MAGNITUDE_CEILING == 35
    assert worst.score == 68
    assert score_step2(-1e-9, spread_pct=0.0).score in (54, 55)
    # The curve's own ceiling must stay below the weak tier's 40 and below what could reach 70 at the loosest weights.
    assert NEGATIVE_MAGNITUDE_CEILING * 0.5 + 100 * 0.5 < PASS_SCORE


def test_floor_boundary_just_either_side_of_zero():
    # The 70 floor starts exactly at 0%: +0.1% is lifted to 70, -0.1% keeps its real score.
    assert score_step2(0.1, spread_pct=0.0).score == 70
    below = score_step2(-0.1, spread_pct=0.0)
    assert below.score == 54 and below.verdict == "Fail"
