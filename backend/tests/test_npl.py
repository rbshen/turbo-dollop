from npl import compute_npl_ratio

NONACCRUAL_TAG = "financingreceivableexcludingaccruedinterestnonaccrual"
TOTAL_LOANS_TAG = "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss"


def test_computes_ratio_when_loans_are_a_plausible_share_of_assets():
    # JPM-style: total_loans is 40% of total_assets, well above the 10% floor.
    raw = {NONACCRUAL_TAG: 4_000_000, TOTAL_LOANS_TAG: 1_000_000_000}
    result = compute_npl_ratio(raw, total_assets=2_500_000_000)
    assert result.ratio_pct == 0.4


def test_unavailable_when_total_loans_implausibly_small_vs_total_assets():
    # BAC/WFC-style: the tag resolves to a mis-scoped, far-too-small value
    # (a disclosure-table line, not the consolidated total) -- degrades to
    # unavailable rather than reporting a wrong ratio.
    raw = {NONACCRUAL_TAG: 100_000, TOTAL_LOANS_TAG: 1_000_000}
    result = compute_npl_ratio(raw, total_assets=2_500_000_000)
    assert result.ratio_pct is None


def test_unavailable_when_nonaccrual_tag_missing():
    raw = {TOTAL_LOANS_TAG: 1_000_000_000}
    result = compute_npl_ratio(raw, total_assets=2_500_000_000)
    assert result.ratio_pct is None


def test_unavailable_when_total_loans_tag_missing():
    raw = {NONACCRUAL_TAG: 4_000_000}
    result = compute_npl_ratio(raw, total_assets=2_500_000_000)
    assert result.ratio_pct is None


def test_unavailable_when_both_tags_missing_gs_style():
    result = compute_npl_ratio({}, total_assets=1_800_000_000_000)
    assert result.ratio_pct is None


def test_computed_without_a_total_assets_bound_when_assets_unknown():
    # If total_assets itself is unavailable, the plausibility check can't
    # run -- fall back to trusting the tag pair rather than blocking on it.
    raw = {NONACCRUAL_TAG: 4_000_000, TOTAL_LOANS_TAG: 1_000_000_000}
    result = compute_npl_ratio(raw, total_assets=None)
    assert result.ratio_pct == 0.4


def test_boundary_exactly_at_min_loans_to_assets_ratio_is_trusted():
    # total_loans exactly 10% of total_assets -- the floor is inclusive.
    raw = {NONACCRUAL_TAG: 1_000, TOTAL_LOANS_TAG: 100_000}
    result = compute_npl_ratio(raw, total_assets=1_000_000)
    assert result.ratio_pct == 1.0


def test_just_below_min_loans_to_assets_ratio_is_unavailable():
    raw = {NONACCRUAL_TAG: 1_000, TOTAL_LOANS_TAG: 99_999}
    result = compute_npl_ratio(raw, total_assets=1_000_000)
    assert result.ratio_pct is None
