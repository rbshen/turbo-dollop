from helpers.shares import compute_shares_outstanding, is_implausible_magnitude_shift


def test_prefers_market_cap_over_price():
    quote = {"marketCap": 3_000_000_000_000, "price": 190.5}
    shares, source = compute_shares_outstanding(quote, [])
    assert shares == 3_000_000_000_000 / 190.5
    assert source == "marketCap / price (latest quote)"


def test_falls_back_to_weighted_average_shares_when_quote_incomplete():
    quote = {"marketCap": None, "price": 190.5}
    income_quarterly = [{"weightedAverageShsOutDil": 15_000_000_000}]
    shares, source = compute_shares_outstanding(quote, income_quarterly)
    assert shares == 15_000_000_000
    assert source == "weightedAverageShsOutDil (latest quarter, diluted)"


def test_returns_none_when_neither_source_available():
    assert compute_shares_outstanding({}, []) == (None, None)


def test_falls_back_when_price_is_zero():
    quote = {"marketCap": 3_000_000_000_000, "price": 0}
    income_quarterly = [{"weightedAverageShsOutDil": 15_000_000_000}]
    shares, source = compute_shares_outstanding(quote, income_quarterly)
    assert shares == 15_000_000_000
    assert source == "weightedAverageShsOutDil (latest quarter, diluted)"


# --- is_implausible_magnitude_shift ---------------------------------------


def test_team_shaped_1000x_drop_is_flagged():
    # Real case: TEAM's Q4 FY2026 weightedAverageShsOutDil read 260163
    # instead of ~260,163,000 -- a ~1000x drop off the prior quarter.
    assert is_implausible_magnitude_shift(260_163, 260_964_999) is True


def test_ordinary_quarter_to_quarter_drift_is_not_flagged():
    assert is_implausible_magnitude_shift(262_674_315, 260_964_999) is False


def test_shift_in_either_direction_is_flagged():
    assert is_implausible_magnitude_shift(260_964_999, 260_163) is True


def test_boundary_exactly_at_100x_is_not_flagged():
    assert is_implausible_magnitude_shift(10_000_000_000, 100_000_000) is False


def test_boundary_just_above_100x_is_flagged():
    assert is_implausible_magnitude_shift(10_000_000_001, 100_000_000) is True


def test_none_or_zero_current_is_not_flagged():
    # Missing/zero data isn't a magnitude defect -- it's just absent, and
    # every call site already handles a None/0 value on its own terms.
    assert is_implausible_magnitude_shift(None, 260_964_999) is False
    assert is_implausible_magnitude_shift(0, 260_964_999) is False


def test_none_or_zero_reference_is_not_flagged():
    # No prior-period baseline to compare against -- e.g. a recent IPO's
    # first reported quarter.
    assert is_implausible_magnitude_shift(260_163, None) is False
    assert is_implausible_magnitude_shift(260_163, 0) is False
