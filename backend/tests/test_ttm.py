from ttm import FlaggedQuarter, sum_last_four_quarters

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
