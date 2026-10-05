from helpers.balance_sheet_gate import (
    CURRENT_ASSETS_REMAP,
    DEBT_BASIS_SHORT_PLUS_LONG,
    DEBT_BASIS_TOTAL_DEBT,
    DEBT_REMAP,
    align_quarters_to_balance_sheet,
    select_complete_balance_sheet,
)


def _bs(
    date, short=0, long=0, total_debt=None, liabilities=10_000, assets=20_000, current_assets=5_000, current_liabilities=2_000
):
    return {
        "date": date,
        "shortTermDebt": short,
        "longTermDebt": long,
        "totalDebt": short + long if total_debt is None else total_debt,
        "totalLiabilities": liabilities,
        "totalAssets": assets,
        "totalCurrentAssets": current_assets,
        "totalCurrentLiabilities": current_liabilities,
    }


def _select(newest, prior, basis=DEBT_BASIS_SHORT_PLUS_LONG, check_current_assets=True):
    return select_complete_balance_sheet([newest, prior], basis, check_current_assets)


# ---- debt rule: drop of >= 65% AND total liabilities fall by < half the debt decline ----


def test_debt_drop_at_exactly_65_percent_with_flat_liabilities_falls_back():
    prior = _bs("2026-03-31", long=1000)
    newest = _bs("2026-06-30", long=350)  # exactly -65%

    result = _select(newest, prior)

    assert result.reason == DEBT_REMAP
    assert result.row is prior
    assert result.incomplete_date == "2026-06-30"
    assert result.used_date == "2026-03-31"


def test_debt_drop_just_below_65_percent_keeps_newest():
    prior = _bs("2026-03-31", long=1000)
    newest = _bs("2026-06-30", long=351)  # -64.9%

    result = _select(newest, prior)

    assert result.reason is None
    assert result.row is newest


def test_total_liabilities_falling_just_under_half_of_debt_decline_falls_back():
    # debt decline 650 -> half is 325; liabilities fall 324.
    prior = _bs("2026-03-31", long=1000, liabilities=10_000)
    newest = _bs("2026-06-30", long=350, liabilities=9_676)

    assert _select(newest, prior).reason == DEBT_REMAP


def test_total_liabilities_falling_exactly_half_or_more_is_a_real_paydown():
    prior = _bs("2026-03-31", long=1000, liabilities=10_000)

    exactly_half = _bs("2026-06-30", long=350, liabilities=9_675)
    just_over_half = _bs("2026-06-30", long=350, liabilities=9_674)

    assert _select(exactly_half, prior).reason is None
    assert _select(just_over_half, prior).reason is None


def test_fslr_type_genuine_paydown_does_not_trigger():
    # FSLR 2026-06-30: short+long 426 -> 38 (-91%), but total liabilities fell
    # 3,473 -> 3,068 (405, more than half of the 388 debt decline).
    prior = _bs("2026-03-31", short=189, long=237, liabilities=3473, assets=13351, current_assets=5646)
    newest = _bs("2026-06-30", short=38, long=0, liabilities=3068, assets=13389, current_assets=5317)

    result = _select(newest, prior)

    assert result.reason is None
    assert result.row is newest


def test_zts_shaped_debt_remap_falls_back():
    prior = _bs("2026-03-31", long=9045, liabilities=11921, assets=15154, current_assets=6474)
    newest = _bs("2026-06-30", long=190, liabilities=11929, assets=15077, current_assets=6356)

    result = _select(newest, prior)

    assert result.reason == DEBT_REMAP
    assert result.detail is not None and "9,045" in result.detail


def test_immaterial_debt_going_to_zero_does_not_trigger():
    # SHOP-shaped: 16 of debt on 14,167 of assets (0.11%) really went to zero.
    prior = _bs("2026-03-31", long=16, liabilities=1625, assets=14167)
    newest = _bs("2026-06-30", long=0, liabilities=1786, assets=14470)

    assert _select(newest, prior).reason is None


def test_debt_decline_materiality_boundary_is_2_percent_of_prior_total_assets():
    # prior assets 20,000 -> 2% is 400. A 100% drop of 400 qualifies, of 399 does not.
    at_boundary = _select(_bs("2026-06-30", long=0), _bs("2026-03-31", long=400))
    just_below = _select(_bs("2026-06-30", long=0), _bs("2026-03-31", long=399))

    assert at_boundary.reason == DEBT_REMAP
    assert just_below.reason is None


def test_debt_rule_ignores_a_rise_and_a_zero_or_missing_prior_debt():
    assert _select(_bs("2026-06-30", long=2000), _bs("2026-03-31", long=1000)).reason is None
    assert _select(_bs("2026-06-30", long=0), _bs("2026-03-31", long=0)).reason is None
    missing_prior = {"date": "2026-03-31", "totalLiabilities": 10_000, "totalAssets": 20_000}
    assert _select(_bs("2026-06-30", long=0), missing_prior).reason is None


def test_debt_rule_needs_total_liabilities_on_both_quarters():
    prior = _bs("2026-03-31", long=1000)
    newest = _bs("2026-06-30", long=0)
    newest["totalLiabilities"] = None

    assert _select(newest, prior).reason is None


# ---- debt basis: Standard reads short+long, REIT gearing reads totalDebt ----


def test_standard_basis_ignores_total_debt_field_and_reit_basis_ignores_short_long():
    # GEV-shaped: short+long collapses while FMP's totalDebt line actually rose.
    prior = _bs("2026-03-31", short=51, long=2554, total_debt=2857, liabilities=60547)
    newest = _bs("2026-06-30", short=0, long=0, total_debt=3960, liabilities=67685)

    assert _select(newest, prior, DEBT_BASIS_SHORT_PLUS_LONG).reason == DEBT_REMAP
    assert _select(newest, prior, DEBT_BASIS_TOTAL_DEBT).reason is None

    # FANG-shaped: totalDebt line collapsed to the short-term piece only while
    # short+long is intact -- only the REIT (totalDebt) basis sees it.
    prior = _bs("2026-03-31", short=749, long=13149, total_debt=13898, liabilities=27440)
    newest = _bs("2026-06-30", short=1548, long=11066, total_debt=1548, liabilities=26233)

    assert _select(newest, prior, DEBT_BASIS_SHORT_PLUS_LONG).reason is None
    assert _select(newest, prior, DEBT_BASIS_TOTAL_DEBT).reason == DEBT_REMAP


def test_doc_shaped_reit_total_debt_remap_falls_back():
    prior = _bs("2026-03-31", short=893, long=9530, total_debt=10713, liabilities=12556, assets=21616)
    newest = _bs("2026-06-30", short=0, long=0, total_debt=0, liabilities=12182, assets=21680)

    result = _select(newest, prior, DEBT_BASIS_TOTAL_DEBT, check_current_assets=False)

    assert result.reason == DEBT_REMAP
    assert result.row is prior


# ---- current-assets rule: > 60% drop with total assets and liabilities roughly flat (+-5%) ----


def test_current_assets_drop_at_exactly_60_percent_does_not_trigger():
    prior = _bs("2026-03-31", current_assets=10_000)
    newest = _bs("2026-06-30", current_assets=4_000)  # exactly -60%

    assert _select(newest, prior).reason is None


def test_current_assets_drop_just_over_60_percent_with_flat_totals_falls_back():
    prior = _bs("2026-03-31", current_assets=10_000)
    newest = _bs("2026-06-30", current_assets=3_999)

    result = _select(newest, prior)

    assert result.reason == CURRENT_ASSETS_REMAP
    assert result.row is prior


def test_adp_shaped_current_assets_remap_falls_back():
    prior = _bs("2026-03-31", current_assets=54234, liabilities=58134, assets=64484, current_liabilities=52020)
    newest = _bs("2026-06-30", current_assets=8603, liabilities=57162, assets=63193, current_liabilities=50025)

    assert _select(newest, prior).reason == CURRENT_ASSETS_REMAP


def test_current_assets_drop_with_non_flat_totals_is_not_a_remap():
    prior = _bs("2026-03-31", current_assets=10_000, liabilities=10_000, assets=20_000)

    assets_not_flat = _bs("2026-06-30", current_assets=3_000, liabilities=10_000, assets=18_900)  # -5.5%
    liabilities_not_flat = _bs("2026-06-30", current_assets=3_000, liabilities=9_400, assets=20_000)  # -6%
    at_tolerance = _bs("2026-06-30", current_assets=3_000, liabilities=9_500, assets=19_000)  # exactly -5%

    assert _select(assets_not_flat, prior).reason is None
    assert _select(liabilities_not_flat, prior).reason is None
    assert _select(at_tolerance, prior).reason == CURRENT_ASSETS_REMAP


def test_current_assets_drop_with_a_big_current_liabilities_move_is_not_a_remap():
    # NDAQ-shaped: current assets -60.5% with total assets / liabilities flat,
    # but current liabilities rose 8x -- a real restructuring, not a remap.
    prior = _bs("2026-03-31", current_assets=4374, liabilities=15263, assets=27301, current_liabilities=431)
    newest = _bs("2026-06-30", current_assets=1728, liabilities=15348, assets=27341, current_liabilities=3574)

    assert _select(newest, prior).reason is None


def test_current_assets_rule_is_skipped_when_the_path_does_not_read_current_assets():
    prior = _bs("2026-03-31", current_assets=10_000)
    newest = _bs("2026-06-30", current_assets=1_000)

    assert _select(newest, prior, check_current_assets=False).reason is None


# ---- degenerate inputs ----


def test_empty_and_single_row_inputs_never_fall_back():
    assert select_complete_balance_sheet([], DEBT_BASIS_SHORT_PLUS_LONG, True).row == {}
    only = _bs("2026-06-30", long=0)
    result = select_complete_balance_sheet([only], DEBT_BASIS_SHORT_PLUS_LONG, True)
    assert result.row is only and result.reason is None


def test_fallback_is_one_step_only():
    # The prior quarter itself looks incomplete against the one before it --
    # the gate still only steps back once and never walks on to the third.
    third = _bs("2025-12-31", long=10_000)
    prior = _bs("2026-03-31", long=1_000)
    newest = _bs("2026-06-30", long=0)

    result = select_complete_balance_sheet([newest, prior, third], DEBT_BASIS_SHORT_PLUS_LONG, True)

    assert result.row is prior
    assert result.used_date == "2026-03-31"


# ---- aligning income / cash-flow quarters to the balance sheet actually used ----


def test_align_drops_only_quarters_ending_after_the_used_balance_sheet():
    rows = [{"date": "2026-06-30"}, {"date": "2026-03-31"}, {"date": "2025-12-31"}]

    assert align_quarters_to_balance_sheet(rows, "2026-03-31") == rows[1:]


def test_align_keeps_a_row_within_the_date_tolerance():
    rows = [{"date": "2026-04-03"}, {"date": "2026-01-02"}]

    assert align_quarters_to_balance_sheet(rows, "2026-03-31") == rows


def test_align_is_a_no_op_without_a_balance_sheet_date_or_with_a_bad_one():
    rows = [{"date": "2026-06-30"}]

    assert align_quarters_to_balance_sheet(rows, None) == rows
    assert align_quarters_to_balance_sheet(rows, "not-a-date") == rows


def test_align_stops_at_the_first_row_that_is_not_newer():
    rows = [{"date": "2026-06-30"}, {"date": "2026-03-31"}, {"date": "2026-09-30"}]

    assert align_quarters_to_balance_sheet(rows, "2026-03-31") == rows[1:]
