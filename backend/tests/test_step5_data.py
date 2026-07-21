import asyncio

from sqlmodel import SQLModel, create_engine

import step5_data
from step5_data import get_step5_data

PROFILE = [{"sector": "Technology", "industry": "Consumer Electronics"}]

# Deliberately very different from the quarterly figures below -- if the
# code ever mistakenly fetched/used the annual balance sheet instead of
# quarterly, these numbers would produce a hard-fail Current Ratio (0.1)
# instead of the quarterly figures' 1.25, so a regression here is caught by
# the resulting ratio/tier, not just by which endpoint got called.
BALANCE_SHEET_ANNUAL = [
    {
        "date": "2025-09-27",
        "period": "FY",
        "totalCurrentAssets": 100,
        "totalCurrentLiabilities": 1000,
        "shortTermDebt": 500,
        "longTermDebt": 500,
        "totalDebt": 1000,
        "totalAssets": 2000,
        "deferredRevenue": 5,
    }
]

BALANCE_SHEET_QUARTERLY = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "totalCurrentAssets": 500,
        "totalCurrentLiabilities": 400,
        "shortTermDebt": 50,
        "longTermDebt": 150,
        "totalDebt": 200,
        "totalAssets": 1000,
        "deferredRevenue": 20,
    }
]

# 4 quarters with distinct ebitda/netInterestIncome values so a bug that
# uses only the single most recent quarter (rather than summing all 4)
# produces a detectably different, wrong result.
INCOME_QUARTERLY = [
    {"date": "2026-03-28", "ebitda": 100, "operatingIncome": 80, "interestExpense": 10, "netInterestIncome": -10},
    {"date": "2025-12-27", "ebitda": 90, "operatingIncome": 70, "interestExpense": 10, "netInterestIncome": -10},
    {"date": "2025-09-27", "ebitda": 80, "operatingIncome": 60, "interestExpense": 10, "netInterestIncome": -10},
    {"date": "2025-06-28", "ebitda": 70, "operatingIncome": 50, "interestExpense": 10, "netInterestIncome": -10},
]

CASH_FLOW_QUARTERLY = [{"date": "2026-03-28", "netCashProvidedByOperatingActivities": 50} for _ in range(4)]

# No usable NPL tags -- the default for every non-Bank test and any Bank
# test that isn't specifically exercising the NPL computation.
FULL_AS_REPORTED_QUARTERLY_MISSING = [{"date": "2026-03-28", "period": "Q2", "fiscalYear": 2026, "data": {}}]
FULL_AS_REPORTED_ANNUAL_MISSING = [{"date": "2025-12-31", "period": "FY", "fiscalYear": 2025, "data": {}}]

# total_loans (400) is 40% of BALANCE_SHEET_QUARTERLY's totalAssets (1000)
# -- well above the plausibility floor, so this reads as a trustworthy tag
# pair. nonaccrual 8 / total_loans 400 * 100 = 2% ("good" tier).
FULL_AS_REPORTED_QUARTERLY_GOOD = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "fiscalYear": 2026,
        "data": {
            "financingreceivableexcludingaccruedinterestnonaccrual": 8,
            "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 400,
        },
    }
]

# total_loans (50) is only 5% of totalAssets (1000) -- below the 10% floor,
# same failure mode confirmed during investigation for BAC/WFC (the tag
# resolves to a mis-scoped disclosure-table value, not the true total loan
# book).
FULL_AS_REPORTED_QUARTERLY_IMPLAUSIBLE = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "fiscalYear": 2026,
        "data": {
            "financingreceivableexcludingaccruedinterestnonaccrual": 2,
            "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 50,
        },
    }
]

# USB/TFC-style: nonaccrual tag absent from the latest quarter (total_loans
# still present), so the fallback should read from the annual filing below.
FULL_AS_REPORTED_QUARTERLY_MISSING_NONACCRUAL_ONLY = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "fiscalYear": 2026,
        "data": {"financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 400},
    }
]

# The annual-fallback figures: nonaccrual 8 / total_loans 400 -> 2% ("good"),
# same magnitude as FULL_AS_REPORTED_QUARTERLY_GOOD so a test can tell the
# two apart by which as_of label comes back, not just by the ratio value.
FULL_AS_REPORTED_ANNUAL_GOOD = [
    {
        "date": "2025-12-31",
        "period": "FY",
        "fiscalYear": 2025,
        "data": {
            "financingreceivableexcludingaccruedinterestnonaccrual": 8,
            "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 400,
        },
    }
]

# Fallback-eligible (nonaccrual missing quarterly) but the annual filing's
# total_loans is itself implausibly small -- the floor must still apply.
FULL_AS_REPORTED_ANNUAL_IMPLAUSIBLE = [
    {
        "date": "2025-12-31",
        "period": "FY",
        "fiscalYear": 2025,
        "data": {
            "financingreceivableexcludingaccruedinterestnonaccrual": 2,
            "financingreceivableexcludingaccruedinterestbeforeallowanceforcreditloss": 50,
        },
    }
]


def _patch_fmp(
    monkeypatch,
    sector="Technology",
    industry="Consumer Electronics",
    income_quarterly=None,
    full_as_reported_quarterly=None,
    full_as_reported_annual=None,
):
    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY if period == "quarter" else BALANCE_SHEET_ANNUAL

    async def fake_income_statement(ticker, period, limit):
        return income_quarterly if income_quarterly is not None else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_QUARTERLY

    async def fake_full_as_reported(ticker, period, limit):
        if period == "quarter":
            return full_as_reported_quarterly if full_as_reported_quarterly is not None else FULL_AS_REPORTED_QUARTERLY_MISSING
        return full_as_reported_annual if full_as_reported_annual is not None else FULL_AS_REPORTED_ANNUAL_MISSING

    monkeypatch.setattr(step5_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_financial_statement_full_as_reported", fake_full_as_reported)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step5_data, "engine", test_engine)


def test_uses_quarterly_balance_sheet_not_annual(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step5_data("aapl"))

    # 500/400 = 1.25 (acceptable) -- not the annual fixture's 100/1000 = 0.1
    # (which would hard-fail).
    assert result.ratios["current_ratio"].value == 1.25
    assert result.ratios["current_ratio"].label == "acceptable"
    assert result.hard_fail is False


def test_ebitda_and_net_interest_expense_are_ttm_summed(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step5_data("aapl"))

    # debt = 50 + 150 = 200; ebitda TTM = 100+90+80+70 = 340 -- not just the
    # latest quarter's 100, which would understate the denominator ~3.4x.
    assert result.ratios["debt_to_ebitda"].value == 200 / 340
    assert result.ratios["debt_to_ebitda"].label == "excellent"

    # net interest expense TTM = -(-10*4) = 40; CFO TTM = 50*4 = 200 ->
    # 40/200*100 = 20% -- not a single quarter's 10/50*100 = 20% (same in
    # this fixture by design of equal quarters, so this test also pins the
    # exact score/tier which would shift if only 1 quarter were summed
    # incorrectly, e.g. 3 quarters).
    assert result.ratios["debt_servicing_ratio"].value == 20.0
    assert result.ratios["debt_servicing_ratio"].label == "approaching_limit"


def test_interest_coverage_ratio_is_ebit_ttm_over_interest_expense_ttm(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step5_data("aapl"))

    # ebit (operatingIncome) TTM = 80+70+60+50 = 260; interest_expense_ttm
    # = 10*4 = 40 -> 260/40 = 6.5x ("safe"), shown regardless of whether it
    # ends up mattering (debt_to_ebitda/DSR are both Comfortable here).
    assert result.ratios["interest_coverage_ratio"].value == 6.5
    assert result.ratios["interest_coverage_ratio"].label == "safe"
    assert result.pass_with_caution is False


# Deliberately larger debt so Debt/EBITDA lands Borderline (3.0-4.0), and a
# healthy EBIT/interest-expense ratio so Interest Coverage is "safe" --
# end-to-end proof that a real Borderline breach gets excused and the
# overall verdict reads "Pass with caution", not silently "Pass".
BALANCE_SHEET_QUARTERLY_BORDERLINE_DEBT = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "totalCurrentAssets": 500,
        "totalCurrentLiabilities": 400,
        "shortTermDebt": 250,
        "longTermDebt": 800,
        "totalDebt": 1050,
        "totalAssets": 3000,
        "deferredRevenue": 20,
    }
]

INCOME_QUARTERLY_BORDERLINE_DEBT = [
    {"date": "2026-03-28", "ebitda": 100, "operatingIncome": 80, "interestExpense": 5, "netInterestIncome": -5},
    {"date": "2025-12-27", "ebitda": 90, "operatingIncome": 70, "interestExpense": 5, "netInterestIncome": -5},
    {"date": "2025-09-27", "ebitda": 80, "operatingIncome": 60, "interestExpense": 5, "netInterestIncome": -5},
    {"date": "2025-06-28", "ebitda": 70, "operatingIncome": 50, "interestExpense": 5, "netInterestIncome": -5},
]


def test_borderline_debt_to_ebitda_saved_by_icr_reads_pass_with_caution_end_to_end(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, income_quarterly=INCOME_QUARTERLY_BORDERLINE_DEBT)

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY_BORDERLINE_DEBT if period == "quarter" else BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step5_data("aapl"))

    # debt_to_ebitda = 1050 / 340 = 3.088x -- Borderline (3.0-4.0).
    assert result.ratios["debt_to_ebitda"].label == "borderline_saved_by_icr"
    assert result.ratios["debt_to_ebitda"].saved_by_tiebreaker is True
    # ICR = 260 / 20 = 13x -- safe.
    assert result.ratios["interest_coverage_ratio"].label == "safe"
    assert result.pass_with_caution is True
    assert result.verdict == "Pass with caution"
    assert result.hard_fail is False


# A raw Current Ratio below 1.0, resolved to >=1.0 once deferred revenue is
# subtracted from current liabilities -- end-to-end proof this is now wired
# into the verdict, not just an informational note.
BALANCE_SHEET_QUARTERLY_DEFERRED_REVENUE_RESCUE = [
    {
        "date": "2026-03-28",
        "period": "Q2",
        "totalCurrentAssets": 500,
        "totalCurrentLiabilities": 600,
        "shortTermDebt": 50,
        "longTermDebt": 150,
        "totalDebt": 200,
        "totalAssets": 1000,
        "deferredRevenue": 200,
    }
]


def test_current_ratio_rescued_by_deferred_revenue_reads_pass_with_caution_end_to_end(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY_DEFERRED_REVENUE_RESCUE if period == "quarter" else BALANCE_SHEET_ANNUAL

    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step5_data("aapl"))

    # raw = 500/600 = 0.833 (Borderline); adjusted = 500/(600-200) = 1.25
    # (Comfortable) -- rescued.
    assert result.ratios["current_ratio"].value == 500 / 600
    assert result.ratios["current_ratio"].adjusted_value == 1.25
    assert result.ratios["current_ratio"].saved_by_tiebreaker is True
    assert result.pass_with_caution is True
    assert result.verdict == "Pass with caution"
    assert result.hard_fail is False


def test_insufficient_data_when_fewer_than_four_quarters_available(monkeypatch):
    _fresh_engine(monkeypatch)
    # Only 3 quarters -- sum_last_four_quarters requires 4 non-null values,
    # so ebitda_ttm is None and the ticker should read as insufficient data
    # rather than silently summing a partial year.
    _patch_fmp(monkeypatch, income_quarterly=INCOME_QUARTERLY[:3])

    result = asyncio.run(get_step5_data("aapl"))

    assert result.verdict == "insufficient_data"
    assert result.score is None
    assert result.ratios == {}


def test_bank_overall_verdict_stays_not_supported_regardless_of_npl(monkeypatch):
    # CET1 is still unavailable -- NPL is a partial signal only, must never
    # by itself produce a scored Bank verdict.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported_quarterly=FULL_AS_REPORTED_QUARTERLY_GOOD,
    )

    result = asyncio.run(get_step5_data("jpm"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.score is None


def test_bank_npl_ratio_computed_when_tags_present_and_plausible(monkeypatch):
    # JPM-style: quarterly nonaccrual is present, so no fallback should be
    # needed -- the annual fixture here is deliberately empty to prove that.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported_quarterly=FULL_AS_REPORTED_QUARTERLY_GOOD,
        full_as_reported_annual=FULL_AS_REPORTED_ANNUAL_MISSING,
    )

    result = asyncio.run(get_step5_data("jpm"))

    assert result.ratios["npl_ratio"].value == 2.0  # 8 / 400 * 100
    assert result.ratios["npl_ratio"].label == "good"
    assert result.npl_as_of == "Q2 2026"


def test_bank_npl_ratio_unavailable_when_total_loans_implausibly_small(monkeypatch):
    # BAC/WFC/C/PNC/MTB-style: nonaccrual IS present quarterly, just paired
    # with an implausible total_loans -- must NOT trigger the annual
    # fallback (that's a different problem), so a plausible-looking annual
    # fixture here must still be ignored.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported_quarterly=FULL_AS_REPORTED_QUARTERLY_IMPLAUSIBLE,
        full_as_reported_annual=FULL_AS_REPORTED_ANNUAL_GOOD,
    )

    result = asyncio.run(get_step5_data("bac"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.ratios == {}
    assert result.npl_as_of is None


def test_bank_npl_ratio_unavailable_when_tags_missing_in_both_periods(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step5_data("gs"))

    assert result.company_type == "Bank"
    assert result.verdict == "not_supported"
    assert result.ratios == {}
    assert result.npl_as_of is None


def test_bank_npl_falls_back_to_annual_when_quarterly_nonaccrual_missing(monkeypatch):
    # USB/TFC-style: the nonaccrual tag is a genuine 10-K-only disclosure
    # gap for this filer -- absent from the latest quarter, present in the
    # annual filing. The fallback must use the annual filing's own
    # total_loans too (not mix it with the quarterly total_loans), and the
    # response must clearly label which filing it's actually as-of.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported_quarterly=FULL_AS_REPORTED_QUARTERLY_MISSING_NONACCRUAL_ONLY,
        full_as_reported_annual=FULL_AS_REPORTED_ANNUAL_GOOD,
    )

    result = asyncio.run(get_step5_data("usb"))

    assert result.ratios["npl_ratio"].value == 2.0  # 8 / 400 * 100, both from the annual filing
    assert result.ratios["npl_ratio"].label == "good"
    assert result.npl_as_of == "FY2025 annual filing"


def test_bank_npl_annual_fallback_still_respects_plausibility_floor(monkeypatch):
    # Quarterly nonaccrual missing (fallback triggers), but the annual
    # filing's total_loans is itself implausibly small -- must still
    # degrade to unavailable rather than trust it just because it's the
    # fallback path.
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        sector="Financial Services",
        industry="Banks - Diversified",
        full_as_reported_quarterly=FULL_AS_REPORTED_QUARTERLY_MISSING_NONACCRUAL_ONLY,
        full_as_reported_annual=FULL_AS_REPORTED_ANNUAL_IMPLAUSIBLE,
    )

    result = asyncio.run(get_step5_data("xyz"))

    assert result.ratios == {}
    assert result.npl_as_of is None


# --- SEC EDGAR cross-check wiring (Debt Servicing Ratio's own two inputs) --
# The cross-check logic itself (candidate-tag fallback, YTD subtraction,
# CIK lookup, caching, graceful degradation) is covered by test_sec_edgar.py
# against real fixture data -- these tests only confirm get_step5_data
# wires it in correctly: right metrics, right sign, right on-demand scoping.

INCOME_QUARTERLY_WITH_INTEREST_OUTLIER = [
    {"date": "2026-06-13", "ebitda": 5_000_000_000, "interestExpense": 2_300_000_000, "interestIncome": 0, "netInterestIncome": -2_300_000_000},
    {"date": "2026-03-21", "ebitda": 4_800_000_000, "interestExpense": 301_000_000, "interestIncome": 0, "netInterestIncome": -301_000_000},
    {"date": "2025-12-27", "ebitda": 4_700_000_000, "interestExpense": 333_000_000, "interestIncome": 0, "netInterestIncome": -333_000_000},
    {"date": "2025-09-06", "ebitda": 4_600_000_000, "interestExpense": 264_000_000, "interestIncome": 0, "netInterestIncome": -264_000_000},
] + [
    {"date": f"baseline-{i}", "ebitda": 4_500_000_000, "interestExpense": 260_000_000, "interestIncome": 0, "netInterestIncome": -260_000_000}
    for i in range(8)
]

CASH_FLOW_QUARTERLY_WITH_CFO_OUTLIER = [
    {"date": "2026-03-21", "netCashProvidedByOperatingActivities": 41_000_000},
    {"date": "2025-12-27", "netCashProvidedByOperatingActivities": 5_000_000_000},
    {"date": "2025-09-06", "netCashProvidedByOperatingActivities": 5_000_000_000},
    {"date": "2025-06-14", "netCashProvidedByOperatingActivities": 5_000_000_000},
] + [{"date": f"baseline-{i}", "netCashProvidedByOperatingActivities": 5_000_000_000} for i in range(8)]


def _patch_fmp_with_outliers(monkeypatch):
    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_QUARTERLY

    async def fake_income_statement(ticker, period, limit):
        return INCOME_QUARTERLY_WITH_INTEREST_OUTLIER

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_QUARTERLY_WITH_CFO_OUTLIER

    monkeypatch.setattr(step5_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step5_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step5_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)


def test_sec_cross_check_attached_only_to_its_two_scoped_metrics(monkeypatch):
    # interest_expense_ttm also flags here (same root-cause anomaly as
    # net_interest_expense_ttm, since interestIncome is a constant 0), but
    # it's not one of the Debt Servicing Ratio's own two inputs -- only
    # net_interest_expense_ttm and cfo_ttm should get a cross-check.
    _fresh_engine(monkeypatch)
    _patch_fmp_with_outliers(monkeypatch)

    calls = []

    async def fake_cross_check_interest_expense(session, ticker, target_end, fmp_value, staleness_days):
        calls.append(("interest_expense", ticker, target_end, fmp_value))
        return step5_data.sec_edgar.CrossCheckResult(True, 230_000_000.0, "InterestExpense", False, "FMP's figure appears to be a data error -- SEC EDGAR's filed value differs significantly.")

    async def fake_cross_check_cfo(session, ticker, target_end, fmp_value, staleness_days):
        calls.append(("cfo", ticker, target_end, fmp_value))
        return step5_data.sec_edgar.CrossCheckResult(True, 41_000_000.0, "NetCashProvidedByUsedInOperatingActivities", True, "SEC EDGAR confirms FMP's figure.")

    monkeypatch.setattr(step5_data.sec_edgar, "cross_check_interest_expense", fake_cross_check_interest_expense)
    monkeypatch.setattr(step5_data.sec_edgar, "cross_check_cfo", fake_cross_check_cfo)

    result = asyncio.run(get_step5_data("pep"))

    warnings_by_metric = {w.metric: w for w in result.outlier_warnings}
    assert set(warnings_by_metric) == {"interest_expense_ttm", "net_interest_expense_ttm", "cfo_ttm"}

    assert warnings_by_metric["interest_expense_ttm"].sec_cross_check is None

    nie = warnings_by_metric["net_interest_expense_ttm"].sec_cross_check
    assert nie is not None
    assert nie.available is True
    assert nie.sec_value == 230_000_000.0
    assert nie.matches_fmp is False

    cfo = warnings_by_metric["cfo_ttm"].sec_cross_check
    assert cfo is not None
    assert cfo.matches_fmp is True

    # Both scoped metrics were actually cross-checked, exactly once each.
    assert {c[0] for c in calls} == {"interest_expense", "cfo"}


def test_sec_cross_check_receives_sign_flipped_positive_expense_value(monkeypatch):
    # warning.value for net_interest_expense_ttm is the raw quarterly
    # netInterestIncome figure (-2,300,000,000, negative = net expense) --
    # the wiring must flip it to a positive expense value before calling
    # the cross-check, to match SEC's positive-expense tag convention.
    _fresh_engine(monkeypatch)
    _patch_fmp_with_outliers(monkeypatch)

    received = {}

    async def fake_cross_check_interest_expense(session, ticker, target_end, fmp_value, staleness_days):
        received["value"] = fmp_value
        received["target_end"] = target_end
        return step5_data.sec_edgar.CrossCheckResult(True, 230_000_000.0, "InterestExpense", False, "note")

    async def fake_cross_check_cfo(session, ticker, target_end, fmp_value, staleness_days):
        return step5_data.sec_edgar.CrossCheckResult(True, fmp_value, "tag", True, "SEC EDGAR confirms FMP's figure.")

    monkeypatch.setattr(step5_data.sec_edgar, "cross_check_interest_expense", fake_cross_check_interest_expense)
    monkeypatch.setattr(step5_data.sec_edgar, "cross_check_cfo", fake_cross_check_cfo)

    asyncio.run(get_step5_data("pep"))

    assert received["value"] == 2_300_000_000.0  # positive, not the raw -2,300,000,000
    assert received["target_end"].isoformat() == "2026-06-13"


def test_sec_cross_check_never_attempted_when_nothing_is_flagged(monkeypatch):
    # The on-demand-only guarantee: for the vast majority of tickers with no
    # outlier, SEC EDGAR must never be touched at all.
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)  # baseline fixtures, no anomalies

    calls = []

    async def fake_cross_check_interest_expense(*args, **kwargs):
        calls.append("interest_expense")
        return step5_data.sec_edgar.CrossCheckResult(True, 0.0, "tag", True, "note")

    async def fake_cross_check_cfo(*args, **kwargs):
        calls.append("cfo")
        return step5_data.sec_edgar.CrossCheckResult(True, 0.0, "tag", True, "note")

    monkeypatch.setattr(step5_data.sec_edgar, "cross_check_interest_expense", fake_cross_check_interest_expense)
    monkeypatch.setattr(step5_data.sec_edgar, "cross_check_cfo", fake_cross_check_cfo)

    result = asyncio.run(get_step5_data("aapl"))

    assert result.outlier_warnings == []
    assert calls == []
