from helpers.ttm import (
    clean_cash_flow_statements,
    is_scale_broken_row,
    drop_placeholder_cash_flow_rows,
    is_placeholder_cash_flow_row,
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


# --- Placeholder cash-flow rows ------------------------------------------------


def _cf(date, cfo=0, fcf=0, capex=0, investing=0, financing=0, **extra):
    return {
        "date": date,
        "period": "Q",
        "fiscalYear": "2026",
        "netCashProvidedByOperatingActivities": cfo,
        "freeCashFlow": fcf,
        "capitalExpenditure": capex,
        "netCashProvidedByInvestingActivities": investing,
        "netCashProvidedByFinancingActivities": financing,
        **extra,
    }


def _real_cf(date, cfo=100, capex=-30):
    return _cf(date, cfo=cfo, fcf=cfo + capex, capex=capex, investing=capex, financing=-20)


def _inc(date, net_income=50):
    return {"date": date, "period": "Q", "fiscalYear": "2026", "netIncome": net_income}


def test_all_zero_cash_flow_row_with_nonzero_income_net_income_is_a_placeholder():
    # AZO FY2026-shaped: every cash-flow line 0, the income statement real.
    assert is_placeholder_cash_flow_row(_cf("2026-08-29"), [_inc("2026-08-29", 931_603_000)]) is True


def test_skeleton_row_with_only_net_income_and_an_offsetting_plug_is_a_placeholder():
    # ITW/LEN/ECL-shaped: netIncome and an otherNonCashItems plug are the only
    # non-zero lines (CFO sums to 0), plus AZO's one stray tiny inventory line.
    row = _cf("2026-06-30", netIncome=815, otherNonCashItems=-815, inventory=-337_600)

    assert is_placeholder_cash_flow_row(row, [_inc("2026-06-30", 815)]) is True


def test_a_legitimately_zero_capex_line_beside_a_real_cfo_is_not_a_placeholder():
    # An asset-light company: capex and its FCF-inclusive lines can be 0, but a
    # real CFO, investing or financing total means the row is genuine.
    assert is_placeholder_cash_flow_row(_cf("d", cfo=500, fcf=500, capex=0), [_inc("d")]) is False
    assert is_placeholder_cash_flow_row(_cf("d", cfo=500, fcf=500, financing=-100), [_inc("d")]) is False


def test_zero_cfo_with_any_investing_or_financing_activity_is_not_a_placeholder():
    # RJF-shaped: CFO exactly 0 but a (tiny) investing total is reported.
    assert is_placeholder_cash_flow_row(_cf("d", investing=5), [_inc("d")]) is False
    assert is_placeholder_cash_flow_row(_cf("d", financing=-5), [_inc("d")]) is False
    assert is_placeholder_cash_flow_row(_cf("d", capex=-5), [_inc("d")]) is False
    assert is_placeholder_cash_flow_row(_cf("d", fcf=5), [_inc("d")]) is False


def test_all_zero_row_is_not_a_placeholder_without_a_nonzero_income_net_income():
    assert is_placeholder_cash_flow_row(_cf("d"), [_inc("d", 0)]) is False  # genuinely nothing happened
    unrelated = {"date": "other-date", "period": "Q1", "fiscalYear": "2025", "netIncome": 50}
    assert is_placeholder_cash_flow_row(_cf("d"), [unrelated]) is False  # no income row for the period
    assert is_placeholder_cash_flow_row(_cf("d"), []) is False
    assert is_placeholder_cash_flow_row({"date": "d", "netIncome": 5}, [_inc("d")]) is False  # lines absent, not zero


def test_income_row_is_matched_by_fiscal_year_and_period_when_dates_differ():
    row = {**_cf("2026-08-29"), "period": "Q4", "fiscalYear": "2026"}
    income = [{"date": "2026-08-30", "period": "Q4", "fiscalYear": "2026", "netIncome": 10}]

    assert is_placeholder_cash_flow_row(row, income) is True


def test_leading_placeholder_quarter_is_dropped_and_ttm_covers_the_last_four_valid_quarters():
    dates = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    cash_flow = [_cf(dates[0]), *[_real_cf(d, cfo=100 + i) for i, d in enumerate(dates[1:])]]
    income = [_inc(d) for d in dates]

    cleaned = drop_placeholder_cash_flow_rows(cash_flow, income)

    assert [r["date"] for r in cleaned] == dates[1:]
    # The window slides back one quarter: 100 + 101 + 102 + 103.
    assert sum_last_four_quarters(cleaned, "netCashProvidedByOperatingActivities").total == 406


def test_ttm_is_missing_not_partial_when_fewer_than_four_valid_quarters_remain():
    dates = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31"]
    cash_flow = [_cf(dates[0]), *[_real_cf(d) for d in dates[1:]]]

    cleaned = drop_placeholder_cash_flow_rows(cash_flow, [_inc(d) for d in dates])

    assert len(cleaned) == 3
    assert sum_last_four_quarters(cleaned, "netCashProvidedByOperatingActivities").total is None


def test_an_interior_placeholder_blanks_the_window_instead_of_stretching_it():
    dates = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    cash_flow = [_real_cf(dates[0]), _cf(dates[1]), *[_real_cf(d) for d in dates[2:]]]

    cleaned = drop_placeholder_cash_flow_rows(cash_flow, [_inc(d) for d in dates])

    assert len(cleaned) == 6  # nothing removed...
    assert cleaned[1]["netCashProvidedByOperatingActivities"] is None  # ...the gap is blank
    assert cleaned[1]["date"] == dates[1] and cleaned[1]["fiscalYear"] == "2026"  # identity kept
    assert sum_last_four_quarters(cleaned, "netCashProvidedByOperatingActivities").total is None


def test_annual_placeholder_is_blanked_in_place_never_removed():
    annual = [_cf("2026-08-29"), _real_cf("2025-08-30", cfo=3_000), _real_cf("2024-08-31", cfo=2_900)]
    annual[0]["fiscalYear"] = "2026"
    annual[1]["fiscalYear"] = "2025"
    income = [_inc("2026-08-29", 2_572), _inc("2025-08-30"), _inc("2024-08-31")]

    cleaned = drop_placeholder_cash_flow_rows(annual, income, drop_leading=False)

    assert len(cleaned) == 3
    assert cleaned[0]["netCashProvidedByOperatingActivities"] is None
    assert cleaned[0]["fiscalYear"] == "2026"
    assert cleaned[1]["netCashProvidedByOperatingActivities"] == 3_000


def test_clean_rows_pass_through_untouched_and_the_input_is_not_mutated():
    dates = ["2026-06-30", "2026-03-31"]
    cash_flow = [_real_cf(d) for d in dates]
    before = [dict(r) for r in cash_flow]

    cleaned = drop_placeholder_cash_flow_rows(cash_flow, [_inc(d) for d in dates])

    assert cleaned == before and cash_flow == before


def test_a_blanked_annual_row_stops_the_defect_b_correction_from_using_a_zero_total():
    # AZO-shaped end to end: zero annual + zero Q4 placeholder. Cleaned, the
    # newest quarter is gone and the blanked annual row is no duplicate source.
    dates = ["2026-08-29", "2026-05-09", "2026-02-14", "2025-11-22", "2025-08-30"]
    quarterly = [_cf(dates[0]), *[_real_cf(d, cfo=700) for d in dates[1:]]]
    for row in quarterly:
        row["fiscalYear"] = "2026"
    quarterly[0]["period"] = "Q4"
    annual = [{**_cf("2026-08-29"), "period": "FY", "fiscalYear": "2026"}]
    income_q = [_inc(d) for d in dates]
    income_a = [{"date": "2026-08-29", "period": "FY", "fiscalYear": "2026", "netIncome": 2_572}]

    q = drop_placeholder_cash_flow_rows(quarterly, income_q)
    a = drop_placeholder_cash_flow_rows(annual, income_a, drop_leading=False)

    assert sum_last_four_quarters(q, "netCashProvidedByOperatingActivities", a).total == 2_800


# --- Whole-row scale breaks ----------------------------------------------------

# 12 monetary lines, each with its own magnitude (1e6..1e11) so a row-wide
# shift is visible on every line.
LINES = [f"line{i}" for i in range(12)]


def _row(scale=1.0, growth=1.0, only=None):
    row = {"date": "d", "period": "FY", "fiscalYear": "2026"}
    for i, key in enumerate(LINES):
        factor = scale if only is None or key in only else 1.0
        row[key] = (10 ** (6 + i % 6)) * (1 + i / 10) * growth * factor
    return row


def _series(target_index, target_row):
    rows = [_row(growth=1.0 + 0.05 * i) for i in range(6)]
    rows[target_index] = target_row
    return rows


def test_a_whole_row_in_unscaled_millions_is_a_scale_break_amcr_shaped():
    rows = _series(0, _row(scale=1e-6, growth=1.6))

    assert is_scale_broken_row(rows, 0) is True
    # ... and none of its (consistent) neighbours is flagged because of it.
    assert [is_scale_broken_row(rows, i) for i in range(1, 6)] == [False] * 5


def test_a_scale_consistent_row_is_not_flagged_even_when_it_grew_a_lot():
    # 10x year-on-year growth on every line is real, not a unit break.
    rows = _series(0, _row(growth=10.0))

    assert is_scale_broken_row(rows, 0) is False


def test_a_shift_of_100x_is_below_the_threshold_but_1000x_is_not():
    assert is_scale_broken_row(_series(0, _row(scale=1e-2)), 0) is False
    assert is_scale_broken_row(_series(0, _row(scale=1e-3)), 0) is True
    assert is_scale_broken_row(_series(0, _row(scale=1e3)), 0) is True  # either direction


def test_one_tiny_line_in_an_otherwise_consistent_row_is_not_a_scale_break():
    # EME / MCHP / POOL / SYM-shaped: a single line is off by 1000x or more.
    assert is_scale_broken_row(_series(0, _row(scale=1e-6, only={"line3"})), 0) is False


def test_the_line_fraction_boundary_is_80_percent():
    # 12 comparable lines: 10 broken = 83% -> flagged; 9 broken = 75% -> not.
    ten = {f"line{i}" for i in range(10)}
    nine = {f"line{i}" for i in range(9)}

    assert is_scale_broken_row(_series(0, _row(scale=1e-4, only=ten)), 0) is True
    assert is_scale_broken_row(_series(0, _row(scale=1e-4, only=nine)), 0) is False


def test_far_off_lines_spread_over_many_decades_are_a_young_company_not_a_unit_break():
    # VRT-shaped pre-merger year: most lines far smaller than the neighbours but by
    # wildly different factors, not one common unit factor.
    row = _row()
    for i, key in enumerate(LINES):
        row[key] = row[key] * 10 ** (-3 - i * 0.4)
    rows = _series(0, row)

    assert is_scale_broken_row(rows, 0) is False


def test_too_few_comparable_lines_or_neighbours_is_never_a_scale_break():
    few_lines = [{"a": 1.0, "b": 2.0}, {"a": 1e6, "b": 2e6}, {"a": 1e6, "b": 2e6}]
    assert is_scale_broken_row(few_lines, 0) is False
    two_rows = [_row(scale=1e-6), _row()]
    assert is_scale_broken_row(two_rows, 0) is False  # a line needs two non-zero neighbours


def _amcr_cash_flow(date, period, year, cfo, net_income):
    row = {"date": date, "period": period, "fiscalYear": year}
    for i, key in enumerate(LINES):
        row[key] = 1.0 + i  # filler lines so the row has enough monetary lines
    row["netCashProvidedByOperatingActivities"] = cfo
    row["netIncome"] = net_income
    return row


def test_scale_broken_annual_row_blanks_it_and_drops_its_derived_q4_so_ttm_uses_the_last_four_valid_quarters():
    # AMCR FY2026: annual row in unscaled millions (CFO 2,151), and FMP's
    # derived Q4 (= annual - Q1..Q3) is garbage (-556M). Everything else is in dollars.
    def line_row(date, period, year, scale, growth):
        row = {**_row(scale=scale, growth=growth), "date": date, "period": period, "fiscalYear": year}
        row["netCashProvidedByOperatingActivities"] = 2_000_000_000 * growth * scale
        return row

    annual = [line_row("2026-06-30", "FY", "2026", 1e-6, 1.6)] + [
        line_row(f"{2025 - i}-06-30", "FY", str(2025 - i), 1.0, 1.0 + 0.05 * i) for i in range(5)
    ]
    quarterly = [
        {"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": -556_000_000},
        {"date": "2026-03-05", "period": "Q3", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 208_000_000},
        {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 504_000_000},
        {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": -133_000_000},
        {"date": "2025-06-30", "period": "Q4", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 1_114_000_000},
        {"date": "2025-03-31", "period": "Q3", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 300_000_000},
    ]

    clean_annual, clean_quarterly = clean_cash_flow_statements(annual, quarterly, [], [])

    assert len(clean_annual) == len(annual)  # blanked in place, never removed
    assert clean_annual[0]["netCashProvidedByOperatingActivities"] is None
    assert clean_annual[0]["fiscalYear"] == "2026"
    assert clean_annual[1] == annual[1]
    # The poisoned Q4 FY2026 is dropped; TTM = Q3 + Q2 + Q1 FY26 + Q4 FY25 (not the 22.7M-style sum).
    assert [q["date"] for q in clean_quarterly][:4] == ["2026-03-05", "2025-12-31", "2025-09-30", "2025-06-30"]
    assert sum_last_four_quarters(clean_quarterly, "netCashProvidedByOperatingActivities").total == 208_000_000 + 504_000_000 - 133_000_000 + 1_114_000_000


def test_a_q4_row_is_only_dropped_when_its_own_fiscal_years_annual_row_is_the_scale_break():
    annual = [_row(growth=1.0 + 0.05 * i) for i in range(6)]  # nothing broken
    for i, row in enumerate(annual):
        row["fiscalYear"] = str(2026 - i)
    quarterly = [{"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 5}]

    clean_annual, clean_quarterly = clean_cash_flow_statements(annual, quarterly, [], [])

    assert clean_annual == annual and clean_quarterly == quarterly


def test_clean_cash_flow_statements_still_applies_the_placeholder_rule():
    dates = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30"]
    quarterly = [_cf(dates[0]), *[_real_cf(d) for d in dates[1:]]]
    income = [_inc(d) for d in dates]

    _, clean_quarterly = clean_cash_flow_statements([], quarterly, [], income)

    assert [q["date"] for q in clean_quarterly] == dates[1:]
