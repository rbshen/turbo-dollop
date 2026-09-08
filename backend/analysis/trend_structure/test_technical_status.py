from analysis.trend_structure.technical_status import (
    REVERSAL_STALE_THRESHOLD_BARS,
    compute_pullback_status,
    compute_reversal_status,
)


class TestComputeReversalStatus:
    def test_confirmed_ll_with_divergence_and_confirmed_tier_reads_confirmed(self):
        assert compute_reversal_status("confirmed", "LL", True, bars_since_confirmation=5) == "confirmed"

    def test_strong_tier_also_qualifies(self):
        assert compute_reversal_status("strong", "LL", True, bars_since_confirmation=5) == "confirmed"

    def test_weak_tier_does_not_qualify_even_with_divergence(self):
        assert compute_reversal_status("weak", "LL", True, bars_since_confirmation=5) == "not_present"

    def test_non_ll_swing_reads_not_present(self):
        assert compute_reversal_status("confirmed", "HH", True, bars_since_confirmation=5) == "not_present"

    def test_no_divergence_reads_not_present(self):
        assert compute_reversal_status("confirmed", "LL", False, bars_since_confirmation=5) == "not_present"

    def test_null_divergence_reads_not_present_same_as_false(self):
        assert compute_reversal_status("confirmed", "LL", None, bars_since_confirmation=5) == "not_present"

    def test_null_classification_reads_not_present(self):
        assert compute_reversal_status("confirmed", None, True, bars_since_confirmation=5) == "not_present"

    def test_past_stale_threshold_downgrades_to_confirmed_stale(self):
        assert (
            compute_reversal_status("confirmed", "LL", True, bars_since_confirmation=REVERSAL_STALE_THRESHOLD_BARS)
            == "confirmed_stale"
        )

    def test_just_under_stale_threshold_stays_confirmed(self):
        assert (
            compute_reversal_status("confirmed", "LL", True, bars_since_confirmation=REVERSAL_STALE_THRESHOLD_BARS - 1)
            == "confirmed"
        )

    def test_null_bars_since_confirmation_never_reads_stale(self):
        assert compute_reversal_status("confirmed", "LL", True, bars_since_confirmation=None) == "confirmed"


class TestComputePullbackStatus:
    def test_downtrend_reads_invalidated_regardless_of_warning_flag(self):
        assert compute_pullback_status("downtrend", warning_flag=False, pullback_occurred_since_flip=None) == "invalidated"
        assert compute_pullback_status("downtrend", warning_flag=True, pullback_occurred_since_flip=True) == "invalidated"

    def test_uptrend_with_warning_flag_reads_pending(self):
        assert compute_pullback_status("uptrend", warning_flag=True, pullback_occurred_since_flip=False) == "pending"

    def test_uptrend_no_warning_with_prior_pullback_reads_recovered(self):
        assert compute_pullback_status("uptrend", warning_flag=False, pullback_occurred_since_flip=True) == "recovered"

    def test_uptrend_no_warning_no_prior_pullback_reads_no_pullback(self):
        assert compute_pullback_status("uptrend", warning_flag=False, pullback_occurred_since_flip=False) == "no_pullback"

    def test_uptrend_no_warning_null_prior_pullback_reads_no_pullback(self):
        # None reads the same as False -- a row computed before this field
        # existed shouldn't be misread as "Recovered".
        assert compute_pullback_status("uptrend", warning_flag=False, pullback_occurred_since_flip=None) == "no_pullback"
