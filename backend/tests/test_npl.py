from npl import compute_npl_ratio

NONACCRUAL_TAG = "financingreceivableexcludingaccruedinterestnonaccrual"
TOTAL_LOANS_TAG = "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss"

EMPTY_ROW = {"date": "2026-03-30", "period": "Q1", "fiscalYear": 2026, "data": {}}


def _row(period: str, fiscal_year: int, date: str, nonaccrual, total_loans) -> dict:
    return {
        "date": date,
        "period": period,
        "fiscalYear": fiscal_year,
        "data": {NONACCRUAL_TAG: nonaccrual, TOTAL_LOANS_TAG: total_loans},
    }


def test_uses_quarterly_when_nonaccrual_present_no_fallback():
    quarterly = _row("Q4", 2025, "2025-12-30", 4_000_000, 1_000_000_000)
    # Deliberately different annual figures -- if the code wrongly preferred
    # annual, this would produce a detectably different ratio/label.
    annual = _row("FY", 2024, "2024-12-30", 999, 999)

    result = compute_npl_ratio(quarterly, annual, total_assets=2_500_000_000)

    assert result.ratio_pct == 0.4
    assert result.as_of == "Q4 2025"


def test_falls_back_to_annual_when_quarterly_nonaccrual_missing():
    # USB/TFC-style: quarterly has total_loans but no nonaccrual tag at all.
    quarterly = {
        "date": "2026-03-30",
        "period": "Q1",
        "fiscalYear": 2026,
        "data": {TOTAL_LOANS_TAG: 399_796_000_000},
    }
    annual = _row("FY", 2024, "2024-12-30", 1_800_000_000, 379_832_000_000)

    result = compute_npl_ratio(quarterly, annual, total_assets=692_345_000_000)

    assert result.ratio_pct is not None
    assert round(result.ratio_pct, 3) == round(1_800_000_000 / 379_832_000_000 * 100, 3)
    assert result.as_of == "FY2024 annual filing"


def test_plausibility_floor_applies_to_annual_fallback_data():
    # Quarterly nonaccrual missing (triggers fallback), and the annual
    # filing's total_loans is implausibly small vs. total_assets -- must
    # still degrade to unavailable, not report a wrong ratio just because
    # it came from the fallback path.
    quarterly = {"date": "2026-03-30", "period": "Q1", "fiscalYear": 2026, "data": {}}
    annual = _row("FY", 2024, "2024-12-30", 100_000, 1_000_000)

    result = compute_npl_ratio(quarterly, annual, total_assets=2_500_000_000)

    assert result.ratio_pct is None
    assert result.as_of is None


def test_unavailable_when_both_quarterly_and_annual_missing_nonaccrual():
    result = compute_npl_ratio(EMPTY_ROW, EMPTY_ROW, total_assets=2_500_000_000)
    assert result.ratio_pct is None
    assert result.as_of is None


def test_no_fallback_when_quarterly_nonaccrual_present_but_total_loans_implausible():
    # BAC/WFC/C/PNC/MTB-style: nonaccrual IS present quarterly, but
    # total_loans resolves to a mis-scoped, too-small value -- this is a
    # different problem than the missing-tag fallback and must NOT trigger
    # falling back to annual; it should just read as unavailable.
    quarterly = _row("Q4", 2025, "2025-12-30", 100_000, 1_000_000)
    annual = _row("FY", 2024, "2024-12-30", 4_000_000, 1_000_000_000)  # plausible, but must be ignored

    result = compute_npl_ratio(quarterly, annual, total_assets=2_500_000_000)

    assert result.ratio_pct is None
    assert result.as_of is None


def test_unavailable_when_total_loans_tag_missing_in_both_periods():
    quarterly = {"date": "2026-03-30", "period": "Q1", "fiscalYear": 2026, "data": {NONACCRUAL_TAG: 4_000_000}}
    annual = {"date": "2024-12-30", "period": "FY", "fiscalYear": 2024, "data": {NONACCRUAL_TAG: 3_000_000}}

    result = compute_npl_ratio(quarterly, annual, total_assets=2_500_000_000)

    assert result.ratio_pct is None


def test_computed_without_a_total_assets_bound_when_assets_unknown():
    quarterly = _row("Q4", 2025, "2025-12-30", 4_000_000, 1_000_000_000)
    annual = EMPTY_ROW

    result = compute_npl_ratio(quarterly, annual, total_assets=None)

    assert result.ratio_pct == 0.4
    assert result.as_of == "Q4 2025"


def test_boundary_exactly_at_min_loans_to_assets_ratio_is_trusted():
    quarterly = _row("Q4", 2025, "2025-12-30", 1_000, 100_000)
    annual = EMPTY_ROW

    result = compute_npl_ratio(quarterly, annual, total_assets=1_000_000)

    assert result.ratio_pct == 1.0


def test_just_below_min_loans_to_assets_ratio_is_unavailable():
    quarterly = _row("Q4", 2025, "2025-12-30", 1_000, 99_999)
    annual = EMPTY_ROW

    result = compute_npl_ratio(quarterly, annual, total_assets=1_000_000)

    assert result.ratio_pct is None
