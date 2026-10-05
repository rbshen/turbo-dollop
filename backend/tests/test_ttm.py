from helpers.ttm import (
    FlaggedQuarter,
    is_quarter_content_duplicate_of_annual,
    is_ttm_period_duplicate_of_last_fy,
    sum_last_four_quarters,
)

# 8 stable baseline quarters (all $100M) followed by the 4 "recent" quarters
# under test -- most-recent-first, matching FMP's own ordering.
STABLE_BASELINE = [{"date": f"2024-Q{i}", "value": 100_000_000} for i in range(8)]


def _quarters(recent: list[dict]) -> list[dict]:
    return recent + STABLE_BASELINE


def test_sum_is_unaffected_by_outlier_detection():
    # Confirms the TTM sum always uses the raw data exactly as fetched --
    # detection never alters, excludes, or "corrects" the flagged value.
    recent = [
        {"date": "2026-Q2", "value": 2_300_000_000},
        {"date": "2026-Q1", "value": 100_000_000},
        {"date": "2025-Q4", "value": 100_000_000},
        {"date": "2025-Q3", "value": 100_000_000},
    ]
    result = sum_last_four_quarters(_quarters(recent), "value")
    assert result.total == 2_300_000_000 + 100_000_000 * 3


def test_clear_outlier_is_flagged_pep_q2_2026_case():
    # Real case: PEP's Q2 2026 interestExpense read $2,300M against a
    # ~$226M trailing median -- confirmed a data error, not a real event.
    recent = [
        {"date": "2026-Q2", "value": 2_300_000_000},
        {"date": "2026-Q1", "value": 301_000_000},
        {"date": "2025-Q4", "value": 333_000_000},
        {"date": "2025-Q3", "value": 264_000_000},
    ]
    baseline = [{"date": f"2025-Q{i}", "value": v} for i, v in enumerate([260, 264, 264, 219, 230, 240, 250, 245])]
    baseline = [{"date": q["date"], "value": q["value"] * 1_000_000} for q in baseline]
    result = sum_last_four_quarters(recent + baseline, "value")
    assert result.total is not None
    assert result.flagged == [FlaggedQuarter(date="2026-Q2", value=2_300_000_000, trailing_median=247_500_000.0)]


def test_normal_ticker_data_is_not_flagged():
    # No false positive on ordinary quarter-to-quarter variation.
    recent = [
        {"date": "2026-Q2", "value": 110_000_000},
        {"date": "2026-Q1", "value": 95_000_000},
        {"date": "2025-Q4", "value": 105_000_000},
        {"date": "2025-Q3", "value": 90_000_000},
    ]
    result = sum_last_four_quarters(_quarters(recent), "value")
    assert result.flagged == []


def test_rapid_organic_growth_is_not_flagged_nvda_style():
    # Real NVDA quarterly EBITDA (FMP /income-statement, most-recent-first)
    # -- the most recent quarter is ~3.8x the trailing median, organic
    # AI-driven growth, not a data error -- must stay under the 5x
    # threshold (confirmed: median $18.73B, no flags).
    recent = [
        {"date": "2026-04-26", "value": 71_002_000_000},
        {"date": "2026-01-25", "value": 51_283_000_000},
        {"date": "2025-10-26", "value": 38_748_000_000},
        {"date": "2025-07-27", "value": 31_937_000_000},
    ]
    baseline_values = [22_584_000_000, 25_821_000_000, 22_855_000_000, 19_708_000_000, 17_753_000_000, 14_556_000_000, 10_957_000_000, 7_411_000_000]
    baseline = [{"date": f"baseline-{i}", "value": v} for i, v in enumerate(baseline_values)]
    result = sum_last_four_quarters(recent + baseline, "value")
    assert result.flagged == []


def test_boundary_exactly_at_5x_is_not_flagged():
    recent = [
        {"date": "2026-Q2", "value": 500_000_000},  # exactly 5.0x median -- not "more than"
        {"date": "2026-Q1", "value": 100_000_000},
        {"date": "2025-Q4", "value": 100_000_000},
        {"date": "2025-Q3", "value": 100_000_000},
    ]
    result = sum_last_four_quarters(_quarters(recent), "value")
    assert result.flagged == []


def test_boundary_just_above_5x_is_flagged():
    recent = [
        {"date": "2026-Q2", "value": 500_000_001},
        {"date": "2026-Q1", "value": 100_000_000},
        {"date": "2025-Q4", "value": 100_000_000},
        {"date": "2025-Q3", "value": 100_000_000},
    ]
    result = sum_last_four_quarters(_quarters(recent), "value")
    assert len(result.flagged) == 1
    assert result.flagged[0].value == 500_000_001


def test_boundary_exactly_at_one_fifth_is_not_flagged():
    recent = [
        {"date": "2026-Q2", "value": 20_000_000},  # exactly median/5 -- not "less than"
        {"date": "2026-Q1", "value": 100_000_000},
        {"date": "2025-Q4", "value": 100_000_000},
        {"date": "2025-Q3", "value": 100_000_000},
    ]
    result = sum_last_four_quarters(_quarters(recent), "value")
    assert result.flagged == []


def test_boundary_just_below_one_fifth_is_flagged():
    recent = [
        {"date": "2026-Q2", "value": 19_999_999},
        {"date": "2026-Q1", "value": 100_000_000},
        {"date": "2025-Q4", "value": 100_000_000},
        {"date": "2025-Q3", "value": 100_000_000},
    ]
    result = sum_last_four_quarters(_quarters(recent), "value")
    assert len(result.flagged) == 1
    assert result.flagged[0].value == 19_999_999


def test_skips_detection_with_fewer_than_minimum_baseline_quarters():
    # A recent IPO with only 2 quarters of baseline history -- fall back
    # gracefully (skip the check), don't flag off a tiny sample.
    recent = [
        {"date": "2026-Q2", "value": 900_000_000},
        {"date": "2026-Q1", "value": 100_000_000},
        {"date": "2025-Q4", "value": 100_000_000},
        {"date": "2025-Q3", "value": 100_000_000},
    ]
    thin_baseline = [{"date": "2025-Q2", "value": 100_000_000}, {"date": "2025-Q1", "value": 100_000_000}]
    result = sum_last_four_quarters(recent + thin_baseline, "value")
    assert result.total is not None
    assert result.flagged == []


def test_skips_detection_when_baseline_median_is_zero_aapl_style():
    # AAPL's interestExpense reads 0 for years -- a ratio against a zero
    # baseline is undefined, not "infinite"; must not false-flag.
    recent = [
        {"date": "2026-Q2", "value": 5_000_000},
        {"date": "2026-Q1", "value": 0},
        {"date": "2025-Q4", "value": 0},
        {"date": "2025-Q3", "value": 0},
    ]
    baseline = [{"date": f"baseline-{i}", "value": 0} for i in range(8)]
    result = sum_last_four_quarters(recent + baseline, "value")
    assert result.flagged == []


def test_total_is_none_when_fewer_than_four_recent_quarters_have_values():
    recent = [
        {"date": "2026-Q2", "value": 100},
        {"date": "2026-Q1", "value": None},
        {"date": "2025-Q4", "value": 100},
        {"date": "2025-Q3", "value": 100},
    ]
    result = sum_last_four_quarters(recent + STABLE_BASELINE, "value")
    assert result.total is None
    assert result.flagged == []


# --- is_ttm_period_duplicate_of_last_fy -----------------------------------


def test_ttm_period_duplicate_when_no_quarter_reported_since_fy_close():
    # SNDK-shaped: fiscal year just closed, no newer quarter posted yet --
    # the 4 most recent quarters ARE that fiscal year's own Q1-Q4.
    annual = [
        {"fiscalYear": "2025", "netIncome": -1641},
        {"fiscalYear": "2026", "netIncome": 11433},
    ]
    quarterly = [
        {"fiscalYear": "2026", "period": "Q4", "netIncome": 6903},
        {"fiscalYear": "2026", "period": "Q3", "netIncome": 3615},
        {"fiscalYear": "2026", "period": "Q2", "netIncome": 803},
        {"fiscalYear": "2026", "period": "Q1", "netIncome": 112},
        {"fiscalYear": "2025", "period": "Q4", "netIncome": -23},
    ]
    assert is_ttm_period_duplicate_of_last_fy(annual, quarterly) is True


def test_ttm_not_duplicate_when_mid_fiscal_year_aapl_style():
    # AAPL-shaped: TTM window spans 3 quarters of the new FY plus the last
    # quarter of the closed FY -- not a period match.
    annual = [
        {"fiscalYear": "2024", "netIncome": 93736},
        {"fiscalYear": "2025", "netIncome": 112010},
    ]
    quarterly = [
        {"fiscalYear": "2026", "period": "Q3", "netIncome": 29789},
        {"fiscalYear": "2026", "period": "Q2", "netIncome": 29578},
        {"fiscalYear": "2026", "period": "Q1", "netIncome": 42097},
        {"fiscalYear": "2025", "period": "Q4", "netIncome": 27466},
    ]
    assert is_ttm_period_duplicate_of_last_fy(annual, quarterly) is False


def test_ttm_period_duplicate_uses_period_identity_not_value_equality():
    # A genuine period match whose value differs slightly (a post-annual-
    # filing restatement) must still read as a duplicate -- value equality
    # would false-miss this.
    annual = [{"fiscalYear": "2025", "netIncome": 1000}, {"fiscalYear": "2026", "netIncome": 500}]
    quarterly = [
        {"fiscalYear": "2026", "period": "Q4", "netIncome": 120},
        {"fiscalYear": "2026", "period": "Q3", "netIncome": 130},
        {"fiscalYear": "2026", "period": "Q2", "netIncome": 140},
        {"fiscalYear": "2026", "period": "Q1", "netIncome": 111},  # sums to 501, not 500 -- restated
    ]
    assert is_ttm_period_duplicate_of_last_fy(annual, quarterly) is True


def test_ttm_period_duplicate_annual_rows_order_agnostic():
    # annual_rows given most-recent-first (FMP's own order) instead of
    # chronological -- the latest fiscalYear must still be resolved
    # correctly (by label, not position).
    annual = [{"fiscalYear": "2026", "netIncome": 500}, {"fiscalYear": "2025", "netIncome": 1000}]
    quarterly = [
        {"fiscalYear": "2026", "period": "Q4", "netIncome": 125},
        {"fiscalYear": "2026", "period": "Q3", "netIncome": 125},
        {"fiscalYear": "2026", "period": "Q2", "netIncome": 125},
        {"fiscalYear": "2026", "period": "Q1", "netIncome": 125},
    ]
    assert is_ttm_period_duplicate_of_last_fy(annual, quarterly) is True


def test_ttm_period_duplicate_false_with_fewer_than_four_quarters():
    annual = [{"fiscalYear": "2026", "netIncome": 500}]
    quarterly = [
        {"fiscalYear": "2026", "period": "Q4", "netIncome": 500},
        {"fiscalYear": "2026", "period": "Q3", "netIncome": 0},
    ]
    assert is_ttm_period_duplicate_of_last_fy(annual, quarterly) is False


def test_ttm_period_duplicate_false_with_no_annual_rows():
    quarterly = [
        {"fiscalYear": "2026", "period": "Q4", "netIncome": 1},
        {"fiscalYear": "2026", "period": "Q3", "netIncome": 1},
        {"fiscalYear": "2026", "period": "Q2", "netIncome": 1},
        {"fiscalYear": "2026", "period": "Q1", "netIncome": 1},
    ]
    assert is_ttm_period_duplicate_of_last_fy([], quarterly) is False


# --- is_quarter_content_duplicate_of_annual / TEAM Defect B ---------------

# TEAM's actual FY2026/Q4 FY2026 shape (2026-08-16 investigation): the
# quarterly income_statement/cash_flow_statement rows for the just-closed
# fiscal year's Q4 are byte-identical to the annual row for revenue/CFO/
# FCF/netIncome, but NOT for ebitda -- confirming the defect is per-field,
# not a blanket row-level copy.
TEAM_ANNUAL_INCOME = [{"fiscalYear": "2026", "revenue": 6_572_308_000, "netIncome": -53_828_000, "ebitda": -323_037_000}]

TEAM_QUARTERLY_INCOME = [
    {
        "date": "2026-06-30",
        "period": "Q4",
        "fiscalYear": "2026",
        "revenue": 6_572_308_000,  # duplicate of annual
        "netIncome": -53_828_000,  # duplicate of annual
        "ebitda": 212_168_000,  # NOT a duplicate -- annual ebitda is -323,037,000
    },
    {"date": "2026-03-31", "period": "Q3", "fiscalYear": "2026", "revenue": 1_786_971_000, "netIncome": -98_389_000, "ebitda": 10_000_000},
    {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "revenue": 1_586_315_000, "netIncome": -42_645_000, "ebitda": 8_000_000},
    {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "revenue": 1_432_553_000, "netIncome": -51_870_000, "ebitda": 6_000_000},
]


def test_quarter_content_duplicate_detected_team_shaped_revenue():
    assert is_quarter_content_duplicate_of_annual(TEAM_ANNUAL_INCOME, TEAM_QUARTERLY_INCOME, "revenue") is True


def test_quarter_content_duplicate_detected_team_shaped_net_income():
    assert is_quarter_content_duplicate_of_annual(TEAM_ANNUAL_INCOME, TEAM_QUARTERLY_INCOME, "netIncome") is True


def test_quarter_content_duplicate_not_detected_for_non_duplicated_field():
    # ebitda genuinely differs between the Q4 row and the annual row --
    # must not false-positive just because OTHER fields on the same row
    # are duplicated.
    assert is_quarter_content_duplicate_of_annual(TEAM_ANNUAL_INCOME, TEAM_QUARTERLY_INCOME, "ebitda") is False


def test_quarter_content_duplicate_false_when_latest_quarter_not_q4():
    mid_year = [{**TEAM_QUARTERLY_INCOME[0], "period": "Q2"}, *TEAM_QUARTERLY_INCOME[1:]]
    assert is_quarter_content_duplicate_of_annual(TEAM_ANNUAL_INCOME, mid_year, "revenue") is False


def test_quarter_content_duplicate_false_with_no_matching_fiscal_year():
    assert is_quarter_content_duplicate_of_annual([{"fiscalYear": "2025", "revenue": 1}], TEAM_QUARTERLY_INCOME, "revenue") is False


def test_quarter_content_duplicate_false_with_empty_inputs():
    assert is_quarter_content_duplicate_of_annual([], TEAM_QUARTERLY_INCOME, "revenue") is False
    assert is_quarter_content_duplicate_of_annual(TEAM_ANNUAL_INCOME, [], "revenue") is False


def test_sum_last_four_quarters_corrects_team_shaped_revenue_when_annual_rows_passed():
    result = sum_last_four_quarters(TEAM_QUARTERLY_INCOME, "revenue", annual_rows=TEAM_ANNUAL_INCOME)
    # True isolated Q4 = annual (6,572,308,000) - (Q1+Q2+Q3) = 1,766,469,000.
    # TTM = corrected_Q4 + Q1+Q2+Q3 = the annual total itself, exactly --
    # the isolated quarter and the other 3 always sum back to the annual
    # figure by construction.
    assert result.total == 6_572_308_000
    # No longer an outlier once corrected -- it's a true, in-trend value now.
    assert result.flagged == []


def test_sum_last_four_quarters_skips_team_net_income_correction_because_q4_flips_sign():
    # Changed deliberately with the Defect-B plausibility check (2026-10-05):
    # TEAM's derived Q4 net income is -53.8M - (-192.9M) = +139.1M against
    # three loss quarters -- a sign flip, so the correction is skipped and the
    # quarters are summed as reported. (Before the check this asserted the
    # corrected -53,828,000.) A genuine loss-to-profit quarter is
    # indistinguishable from a stub annual row here; see the spec.
    result = sum_last_four_quarters(TEAM_QUARTERLY_INCOME, "netIncome", annual_rows=TEAM_ANNUAL_INCOME)
    assert result.total == -53_828_000 - 98_389_000 - 42_645_000 - 51_870_000


def test_sum_last_four_quarters_does_not_correct_non_duplicated_field():
    # ebitda isn't duplicated -- summing proceeds on the raw, untouched values.
    result = sum_last_four_quarters(TEAM_QUARTERLY_INCOME, "ebitda", annual_rows=TEAM_ANNUAL_INCOME)
    assert result.total == 212_168_000 + 10_000_000 + 8_000_000 + 6_000_000


def test_sum_last_four_quarters_unaffected_when_annual_rows_omitted():
    # Backward compatibility: a call site that doesn't pass annual_rows
    # (e.g. ticker_summary.py's header tiles) behaves exactly as before --
    # the raw, uncorrected (and still-flagged-if-applicable) total.
    result = sum_last_four_quarters(TEAM_QUARTERLY_INCOME, "revenue")
    assert result.total == 6_572_308_000 + 1_786_971_000 + 1_586_315_000 + 1_432_553_000


def test_sum_last_four_quarters_does_not_correct_normal_ticker_data():
    # No duplicate-annual shape at all -- annual_rows being passed must
    # never alter an otherwise-normal ticker's TTM sum.
    quarterly = [
        {"date": "2026-Q2", "period": "Q2", "fiscalYear": "2026", "value": 110_000_000},
        {"date": "2026-Q1", "period": "Q1", "fiscalYear": "2026", "value": 95_000_000},
        {"date": "2025-Q4", "period": "Q4", "fiscalYear": "2025", "value": 105_000_000},
        {"date": "2025-Q3", "period": "Q3", "fiscalYear": "2025", "value": 90_000_000},
    ]
    annual = [{"fiscalYear": "2025", "value": 400_000_000}]
    result = sum_last_four_quarters(_quarters(quarterly), "value", annual_rows=annual)
    assert result.total == 110_000_000 + 95_000_000 + 105_000_000 + 90_000_000


# --- Defect B plausibility check (is_plausible_isolated_quarter) -----------


def _defect_b_quarters(q4, others):
    # Q4 row duplicates the annual total (`q4`), the other three quarters carry `others`.
    periods = [("Q4", "2026-06-30"), ("Q3", "2026-03-31"), ("Q2", "2025-12-31"), ("Q1", "2025-09-30")]
    return [
        {"date": d, "period": p, "fiscalYear": "2026", "value": v} for (p, d), v in zip(periods, [q4, *others])
    ]


def _annual(total):
    return [{"fiscalYear": "2026", "value": total}]


def test_defect_b_correction_applies_when_isolated_q4_is_plausible():
    # others 100/100/100 (mean 100); annual 520 -> corrected Q4 = 220.
    result = sum_last_four_quarters(_defect_b_quarters(520, [100, 100, 100]), "value", _annual(520))

    assert result.total == 520  # corrected Q4 220 + 300


def test_defect_b_correction_boundary_exactly_4x_the_mean_is_still_plausible():
    # corrected Q4 = 400 = 4 x mean(100). Annual = 700.
    result = sum_last_four_quarters(_defect_b_quarters(700, [100, 100, 100]), "value", _annual(700))

    assert result.total == 700


def test_defect_b_correction_skipped_just_above_4x_the_mean():
    # corrected Q4 = 401 > 4 x 100 -> skipped, quarters used as reported (Q4 = 701).
    result = sum_last_four_quarters(_defect_b_quarters(701, [100, 100, 100]), "value", _annual(701))

    assert result.total == 701 + 300


def test_defect_b_correction_boundary_exactly_a_quarter_of_the_mean_is_still_plausible():
    # corrected Q4 = 25 = mean(100) / 4. Annual = 325.
    result = sum_last_four_quarters(_defect_b_quarters(325, [100, 100, 100]), "value", _annual(325))

    assert result.total == 325


def test_defect_b_correction_skipped_just_below_a_quarter_of_the_mean():
    # corrected Q4 = 24 < 25 -> skipped.
    result = sum_last_four_quarters(_defect_b_quarters(324, [100, 100, 100]), "value", _annual(324))

    assert result.total == 324 + 300


def test_defect_b_correction_skipped_when_isolated_q4_flips_sign():
    # FERG/AZO-shaped: a stub annual (150) smaller than the three quarters it
    # should contain (300) -> corrected Q4 = -150. Skipped, Q4 stays 150.
    result = sum_last_four_quarters(_defect_b_quarters(150, [100, 100, 100]), "value", _annual(150))

    assert result.total == 150 + 300


def test_defect_b_correction_skipped_for_a_zero_annual_row_azo_shaped():
    # All-zero annual and Q4 (AZO's FY2026 cash-flow row): the "correction"
    # would make Q4 = -sum(others) and the TTM exactly 0. Skipped instead.
    result = sum_last_four_quarters(_defect_b_quarters(0, [700, 700, 700]), "value", _annual(0))

    assert result.total == 2100


def test_defect_b_correction_with_a_negative_mean_keeps_the_same_sign_rule():
    # Loss-making line: others -100 each; corrected Q4 = -220 is plausible,
    # +220 would be a sign flip.
    plausible = sum_last_four_quarters(_defect_b_quarters(-520, [-100, -100, -100]), "value", _annual(-520))
    flipped = sum_last_four_quarters(_defect_b_quarters(80, [-100, -100, -100]), "value", _annual(80))

    assert plausible.total == -520
    assert flipped.total == 80 - 300  # corrected Q4 would be +380 -> skipped


def test_defect_b_check_is_per_line_item_so_one_bad_line_does_not_block_a_good_one():
    # Same Q4 rows for two fields: "revenue" is a clean duplicate of a sane annual,
    # "interestIncome" is the harmless 0 == 0 stub shape that would flip sign.
    quarters = [
        {"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "revenue": 520, "interestIncome": 0},
        {"date": "2026-03-31", "period": "Q3", "fiscalYear": "2026", "revenue": 100, "interestIncome": 3},
        {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "revenue": 100, "interestIncome": 3},
        {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "revenue": 100, "interestIncome": 3},
    ]
    annual = [{"fiscalYear": "2026", "revenue": 520, "interestIncome": 0}]

    assert sum_last_four_quarters(quarters, "revenue", annual).total == 520  # corrected
    assert sum_last_four_quarters(quarters, "interestIncome", annual).total == 9  # skipped, raw


def test_defect_b_zero_mean_is_never_corrected_and_changes_nothing():
    # Other three quarters sum to 0 -> no scale to judge; the corrected Q4
    # equals the uncorrected one anyway.
    result = sum_last_four_quarters(_defect_b_quarters(500, [0, 0, 0]), "value", _annual(500))

    assert result.total == 500
