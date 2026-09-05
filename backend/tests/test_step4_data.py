import asyncio

from sqlmodel import SQLModel, create_engine

import data.step4_data as step4_data
from data.step4_data import get_step4_data

# 10 years total (2016-2025) -- the recent 5 (2021-2025) are the exact same
# values this fixture had before the display/scoring window was extended to
# 10yr+TTM, so any assertion pinned to those years/indices proves what the
# window used to cover. The older 5 (2016-2020) are deliberately BAD (poor
# ROE/ROIC, wildly different revenue/AR/inventory) -- now that scoring uses
# the full 10yr window (matching Step 1), these years DO feed the score;
# tests below exercise that on purpose (see
# test_scoring_now_uses_the_full_10yr_window_including_bad_older_years).
#
# Revenue/AR both compound at 10%/yr across the recent 5 so Metric 3 reads
# "healthy" (0 gap) in the baseline fixture -- tests that care about AR
# outpacing override AR explicitly rather than fighting this baseline.
INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 146.41, "netIncome": 20.0, "costOfRevenue": 87.846},
    {"fiscalYear": "2024", "revenue": 133.1, "netIncome": 18.0, "costOfRevenue": 79.86},
    {"fiscalYear": "2023", "revenue": 121.0, "netIncome": 16.0, "costOfRevenue": 72.6},
    {"fiscalYear": "2022", "revenue": 110.0, "netIncome": 14.0, "costOfRevenue": 66.0},
    {"fiscalYear": "2021", "revenue": 100.0, "netIncome": 12.0, "costOfRevenue": 60.0},
    {"fiscalYear": "2020", "revenue": 500.0, "netIncome": -50.0, "costOfRevenue": 480.0},
    {"fiscalYear": "2019", "revenue": 520.0, "netIncome": -55.0, "costOfRevenue": 500.0},
    {"fiscalYear": "2018", "revenue": 540.0, "netIncome": -60.0, "costOfRevenue": 520.0},
    {"fiscalYear": "2017", "revenue": 560.0, "netIncome": -65.0, "costOfRevenue": 540.0},
    {"fiscalYear": "2016", "revenue": 580.0, "netIncome": -70.0, "costOfRevenue": 560.0},
]

INCOME_QUARTERLY = [
    {"date": "2026-03-28", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
    {"date": "2025-12-27", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
    {"date": "2025-09-27", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
    {"date": "2025-06-28", "revenue": 40.25, "netIncome": 5.5, "costOfRevenue": 24.15},
]

BALANCE_SHEET_ANNUAL = [
    {"fiscalYear": "2025", "totalStockholdersEquity": 100.0, "accountsReceivables": 73.205, "inventory": 29.28, "accountPayables": 43.923},
    {"fiscalYear": "2024", "totalStockholdersEquity": 100.0, "accountsReceivables": 66.55, "inventory": 26.62, "accountPayables": 39.93},
    {"fiscalYear": "2023", "totalStockholdersEquity": 100.0, "accountsReceivables": 60.5, "inventory": 24.2, "accountPayables": 36.3},
    {"fiscalYear": "2022", "totalStockholdersEquity": 100.0, "accountsReceivables": 55.0, "inventory": 22.0, "accountPayables": 33.0},
    {"fiscalYear": "2021", "totalStockholdersEquity": 100.0, "accountsReceivables": 50.0, "inventory": 20.0, "accountPayables": 30.0},
    {"fiscalYear": "2020", "totalStockholdersEquity": 100.0, "accountsReceivables": 500.0, "inventory": 200.0, "accountPayables": 300.0},
    {"fiscalYear": "2019", "totalStockholdersEquity": 100.0, "accountsReceivables": 520.0, "inventory": 210.0, "accountPayables": 310.0},
    {"fiscalYear": "2018", "totalStockholdersEquity": 100.0, "accountsReceivables": 540.0, "inventory": 220.0, "accountPayables": 320.0},
    {"fiscalYear": "2017", "totalStockholdersEquity": 100.0, "accountsReceivables": 560.0, "inventory": 230.0, "accountPayables": 330.0},
    {"fiscalYear": "2016", "totalStockholdersEquity": 100.0, "accountsReceivables": 580.0, "inventory": 240.0, "accountPayables": 340.0},
]

BALANCE_SHEET_QUARTERLY = [
    {
        "date": "2026-03-28",
        "totalStockholdersEquity": 100.0,
        "accountsReceivables": 80.5255,
        "inventory": 30.0,
        "accountPayables": 46.0,
    }
]

KEY_METRICS_ANNUAL = [
    {"fiscalYear": "2025", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2024", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2023", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2022", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    {"fiscalYear": "2021", "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.18},
    # Deliberately terrible -- would hard-fail the verdict (avg ROE <8%) if
    # scoring ever accidentally used the full 10yr display window.
    {"fiscalYear": "2020", "returnOnEquity": 0.02, "returnOnInvestedCapital": 0.02},
    {"fiscalYear": "2019", "returnOnEquity": 0.02, "returnOnInvestedCapital": 0.02},
    {"fiscalYear": "2018", "returnOnEquity": 0.02, "returnOnInvestedCapital": 0.02},
    {"fiscalYear": "2017", "returnOnEquity": 0.02, "returnOnInvestedCapital": 0.02},
    {"fiscalYear": "2016", "returnOnEquity": 0.02, "returnOnInvestedCapital": 0.02},
]

KEY_METRICS_TTM = [{"returnOnEquityTTM": 0.20, "returnOnInvestedCapitalTTM": 0.18}]

# Operating Cash Flow tracking Net Income closely (matches INCOME_ANNUAL's
# netIncome column) -- only used by the AR manual-check note's OCF-vs-NI
# cross-check, so tests that don't care about the note leave this at its
# default (a plausible non-lagging shape) rather than needing to override it.
CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 22.0},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 20.0},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 18.0},
    {"fiscalYear": "2022", "netCashProvidedByOperatingActivities": 16.0},
    {"fiscalYear": "2021", "netCashProvidedByOperatingActivities": 14.0},
    {"fiscalYear": "2020", "netCashProvidedByOperatingActivities": -45.0},
    {"fiscalYear": "2019", "netCashProvidedByOperatingActivities": -50.0},
    {"fiscalYear": "2018", "netCashProvidedByOperatingActivities": -55.0},
    {"fiscalYear": "2017", "netCashProvidedByOperatingActivities": -60.0},
    {"fiscalYear": "2016", "netCashProvidedByOperatingActivities": -65.0},
]

CASH_FLOW_QUARTERLY = [
    {"date": "2026-03-28", "netCashProvidedByOperatingActivities": 6.0},
    {"date": "2025-12-27", "netCashProvidedByOperatingActivities": 6.0},
    {"date": "2025-09-27", "netCashProvidedByOperatingActivities": 6.0},
    {"date": "2025-06-28", "netCashProvidedByOperatingActivities": 6.0},
]


def _patch_fmp(
    monkeypatch,
    sector="Technology",
    industry="Consumer Electronics",
    income_annual=None,
    balance_sheet_annual=None,
    key_metrics_annual=None,
    cash_flow_annual=None,
):
    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_income_statement(ticker, period, limit):
        if period == "annual":
            return income_annual if income_annual is not None else INCOME_ANNUAL
        return INCOME_QUARTERLY

    async def fake_balance_sheet_statement(ticker, period, limit):
        if period == "annual":
            return balance_sheet_annual if balance_sheet_annual is not None else BALANCE_SHEET_ANNUAL
        return BALANCE_SHEET_QUARTERLY

    async def fake_key_metrics(ticker, period, limit):
        return key_metrics_annual if key_metrics_annual is not None else KEY_METRICS_ANNUAL

    async def fake_key_metrics_ttm(ticker):
        return KEY_METRICS_TTM

    async def fake_cash_flow_statement(ticker, period, limit):
        if period == "annual":
            return cash_flow_annual if cash_flow_annual is not None else CASH_FLOW_ANNUAL
        return CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step4_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)
    monkeypatch.setattr(step4_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step4_data, "engine", test_engine)


def test_standard_company_full_pipeline(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.company_type == "Standard"
    # DISPLAY window is now 10yr+TTM (matching Step 1), not 5yr+TTM.
    assert result.years == ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025", "TTM"]
    assert len(result.roe) == 11
    assert len(result.revenue) == 11
    assert len(result.accounts_receivable) == 11
    # Both the older (deliberately bad) and recent (unchanged) years show up
    # in the DISPLAY series -- proves the extra history is actually there,
    # not just padded nulls.
    assert result.roe[0] == 2.0  # 2016, oldest year now visible
    assert result.roe[-2] == 20.0  # 2025, most recent annual year
    assert result.roic is not None
    assert result.roic[0] == 2.0
    assert result.roic[-2] == 18.0
    assert result.ccc is not None
    assert len(result.ccc) == 11  # DISPLAY: all 10yr+TTM
    assert result.score is not None
    assert result.hard_fail is False
    assert result.components["roic"] is not None
    # Weights key set matches `components`' own key set ("revenue_vs_ar",
    # not scoring/step4.py's internal "ar") and all 4 BASE_WEIGHTS apply
    # unmodified since every metric is applicable for this Standard ticker.
    assert result.weights == {"roe": 0.25, "roic": 0.35, "revenue_vs_ar": 0.20, "ccc": 0.20}


# TEAM Defect B shape (2026-08-16 investigation): the latest quarter (a Q4
# matching the fixture's own most recent annual fiscal year, "2025") is a
# content-duplicate of the annual row for revenue/netIncome/costOfRevenue --
# get_step4_data must correct it via sum_last_four_quarters before TTM.
INCOME_QUARTERLY_TEAM_SHAPED = [
    {"date": "2026-03-28", "period": "Q4", "fiscalYear": "2025", "revenue": 146.41, "netIncome": 20.0, "costOfRevenue": 87.846},
    {"date": "2025-12-27", "period": "Q3", "fiscalYear": "2025", "revenue": 35.0, "netIncome": 4.5, "costOfRevenue": 21.0},
    {"date": "2025-09-27", "period": "Q2", "fiscalYear": "2025", "revenue": 32.0, "netIncome": 4.0, "costOfRevenue": 19.0},
    {"date": "2025-06-28", "period": "Q1", "fiscalYear": "2025", "revenue": 30.0, "netIncome": 3.5, "costOfRevenue": 18.0},
]

CASH_FLOW_QUARTERLY_TEAM_SHAPED = [
    {"date": "2026-03-28", "period": "Q4", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 22.0},
    {"date": "2025-12-27", "period": "Q3", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 5.0},
    {"date": "2025-09-27", "period": "Q2", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 4.5},
    {"date": "2025-06-28", "period": "Q1", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 4.0},
]


def test_get_step4_data_corrects_team_shaped_duplicate_annual_quarter(monkeypatch):
    _fresh_engine(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY_TEAM_SHAPED

    async def fake_balance_sheet_statement(ticker, period, limit):
        return BALANCE_SHEET_ANNUAL if period == "annual" else BALANCE_SHEET_QUARTERLY

    async def fake_key_metrics(ticker, period, limit):
        return KEY_METRICS_ANNUAL

    async def fake_key_metrics_ttm(ticker):
        return KEY_METRICS_TTM

    async def fake_cash_flow_statement(ticker, period, limit):
        return CASH_FLOW_ANNUAL if period == "annual" else CASH_FLOW_QUARTERLY_TEAM_SHAPED

    monkeypatch.setattr(step4_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)
    monkeypatch.setattr(step4_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step4_data("team"))

    # TTM revenue/net_income/ocf all resolve to the annual figure itself --
    # not the raw, inflated double-count a pre-fix Fathom would have shown.
    assert result.revenue[-1] == 146.41
    flagged_metrics = {w.metric for w in result.outlier_warnings}
    assert "revenue" not in flagged_metrics
    assert "net_income" not in flagged_metrics
    assert "ocf" not in flagged_metrics


def test_scoring_now_uses_the_full_10yr_window_including_bad_older_years(monkeypatch):
    # The older 5 years (2016-2020) have deliberately terrible ROE/ROIC (2%)
    # blended in with the recent 5's excellent 20%/18%. Scoring now uses the
    # full 10yr+TTM window (matching Step 1), so the 10-year average (11%)
    # lands ROE/ROIC in the "marginal" tier instead of "excellent" -- proof
    # the extra years actually feed the tier classification, not just the
    # display arrays.
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.hard_fail is False  # 11% avg is still above the 8% fail floor
    assert result.components["roe"]["label"] == "marginal"
    assert result.components["roic"]["label"] == "marginal"
    # Revenue and AR move in lockstep in both windows of this fixture, so
    # Metric 3 is unaffected by which years are included.
    assert result.components["revenue_vs_ar"]["label"] == "healthy"


def test_score_differs_between_5yr_only_and_full_10yr_scoring_data(monkeypatch):
    """Before/after comparison proving the scoring window extension actually
    changes real scores now (unlike the earlier display-only change): run
    the same ticker once with only the recent 5yr+TTM data (the exact shape
    this fixture had before either window was extended) and once with the
    full 10yr+TTM fixture (older 5 years deliberately bad) -- ROE/ROIC drop
    from "excellent" to "marginal" once the bad older years are included,
    while Revenue-vs-AR and CCC (unaffected by the bad older years in this
    fixture) stay the same."""
    _fresh_engine(monkeypatch)
    _patch_fmp(
        monkeypatch,
        income_annual=INCOME_ANNUAL[:5],
        balance_sheet_annual=BALANCE_SHEET_ANNUAL[:5],
        key_metrics_annual=KEY_METRICS_ANNUAL[:5],
    )
    baseline = asyncio.run(get_step4_data("aapl"))

    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)  # full 10-year fixture
    extended = asyncio.run(get_step4_data("aapl"))

    assert baseline.score == 100
    assert baseline.verdict == "Strong Pass"
    assert baseline.components["roe"]["label"] == "excellent"
    assert baseline.components["roic"]["label"] == "excellent"

    assert extended.score == 76  # 60*0.25(roe) + 60*0.35(roic) + 100*0.20(ar) + 100*0.20(ccc)
    assert extended.verdict == "Pass"
    assert extended.components["roe"]["label"] == "marginal"
    assert extended.components["roic"]["label"] == "marginal"
    # Metrics not affected by the bad older years in this fixture stay put.
    assert extended.components["revenue_vs_ar"] == baseline.components["revenue_vs_ar"]
    assert extended.components["ccc"] == baseline.components["ccc"]

    # The window genuinely differs -- not just a no-op change. Both arrays
    # pad to the same length (11) regardless of how much real history is
    # available, so the real difference is content: the 5yr-only baseline
    # pads the older slots with placeholders, while the extended fixture has
    # real (if deliberately bad) data there instead.
    assert baseline.years[0] == "—"
    assert extended.years[0] == "2016"


def test_roic_exempt_for_bank(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step4_data("jpm"))

    assert result.company_type == "Bank"
    assert result.roic is None
    assert result.roic_exempt_reason is not None
    assert "Bank" in result.roic_exempt_reason
    assert result.components["roic"] is None


def test_roic_exempt_for_reit(monkeypatch):
    # Bug fix: REIT/Property Developer was missing from ROIC_EXEMPT_TYPES --
    # structurally high leverage is core to the REIT business model too, same
    # rationale as Bank/Insurance/Utility.
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Real Estate", industry="REIT - Industrial")

    result = asyncio.run(get_step4_data("pld"))

    assert result.company_type == "REIT/Property Developer"
    assert result.roic is None
    assert result.roic_exempt_reason is not None
    assert "REIT/Property Developer" in result.roic_exempt_reason
    assert result.components["roic"] is None

    # CCC is now a hard company-type gate for REIT (see
    # test_ccc_exempt_for_reit_regardless_of_inventory_data below) -- this
    # fixture's balance sheet happens to carry non-zero inventory, but that
    # no longer matters for a REIT: CCC must still read exempt.
    assert result.ccc is None
    assert result.ccc_exempt_reason is not None
    assert result.components["ccc"] is None

    # Revenue-vs-AR is also exempt for REIT -- no comparable "selling on
    # credit" concept for a rental-income business model.
    assert result.revenue_vs_ar_exempt_reason is not None
    assert result.components["revenue_vs_ar"] is None

    # ROIC/CCC/Revenue-vs-AR all exempt -> ROE alone renormalizes to 100% of
    # the blend (proportional renormalization, not a fixed reassignment
    # table -- see CLAUDE.md's Profitability deviations).
    assert result.weights == {"roe": 1.0}


def test_ccc_exempt_for_reit_regardless_of_inventory_data(monkeypatch):
    # Real-world finding (O/Realty Income): the data-driven "no physical
    # inventory" heuristic isn't reliable for every REIT -- FMP can report a
    # non-null/non-zero inventory-tagged figure despite CCC being
    # conceptually meaningless for a rental-income business. This fixture
    # deliberately uses the Standard-company BALANCE_SHEET_ANNUAL fixture
    # (real non-zero inventory throughout) with a REIT sector/industry to
    # prove the exemption is now unconditional for this company type.
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, sector="Real Estate", industry="REIT - Retail")

    result = asyncio.run(get_step4_data("o"))

    assert result.company_type == "REIT/Property Developer"
    assert result.ccc is None
    assert "REIT/Property Developer" in result.ccc_exempt_reason
    assert result.components["ccc"] is None


def test_ccc_hard_gate_applies_to_bank_insurance_utility_too(monkeypatch):
    _fresh_engine(monkeypatch)
    for ticker, sector, industry, expected_type in [
        ("jpm2", "Financial Services", "Banks - Diversified", "Bank"),
        ("met2", "Financial Services", "Insurance - Life", "Insurance"),
        ("duk2", "Utilities", "Regulated Electric", "Utility"),
    ]:
        # Distinct tickers per iteration -- same cache key would otherwise
        # serve the first iteration's fixture for every subsequent one.
        _patch_fmp(monkeypatch, sector=sector, industry=industry)
        result = asyncio.run(get_step4_data(ticker))
        assert result.company_type == expected_type
        assert result.ccc is None
        assert result.ccc_exempt_reason is not None
        assert expected_type in result.ccc_exempt_reason


def test_revenue_vs_ar_exempt_for_bank_insurance_utility(monkeypatch):
    # AR_EXEMPT_TYPES now matches CCC_EXEMPT_TYPES/ROIC_EXEMPT_TYPES --
    # Bank/Insurance/Utility are exempt from Revenue-vs-AR the same way
    # REIT already is (2026-09-04 design change, see CLAUDE.md's Step 4
    # deviations).
    _fresh_engine(monkeypatch)
    for ticker, sector, industry, expected_type in [
        ("jpm3", "Financial Services", "Banks - Diversified", "Bank"),
        ("met3", "Financial Services", "Insurance - Life", "Insurance"),
        ("duk3", "Utilities", "Regulated Electric", "Utility"),
    ]:
        # Distinct tickers per iteration -- same cache key would otherwise
        # serve the first iteration's fixture for every subsequent one.
        _patch_fmp(monkeypatch, sector=sector, industry=industry)
        result = asyncio.run(get_step4_data(ticker))
        assert result.company_type == expected_type
        assert result.revenue_vs_ar_exempt_reason is not None
        assert expected_type in result.revenue_vs_ar_exempt_reason
        assert result.components["revenue_vs_ar"] is None


def test_roe_roic_divergence_note_surfaces_on_the_full_pipeline(monkeypatch):
    # Flat ROE (25%, "excellent") vs flat ROIC (10%, "marginal") -- a stable
    # shape with no decline-durability-gate interaction, isolating just the
    # divergence check's own behavior end-to-end.
    _fresh_engine(monkeypatch)
    key_metrics_annual = [{**row, "returnOnEquity": 0.25, "returnOnInvestedCapital": 0.10} for row in KEY_METRICS_ANNUAL]
    _patch_fmp(monkeypatch, key_metrics_annual=key_metrics_annual)

    async def fake_key_metrics_ttm(ticker):
        return [{"returnOnEquityTTM": 0.25, "returnOnInvestedCapitalTTM": 0.10}]

    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.components["roe"]["label"] == "excellent"
    assert result.components["roic"]["label"] == "marginal"
    assert result.roe_roic_divergence_note is not None
    assert "excellent" in result.roe_roic_divergence_note
    assert "marginal" in result.roe_roic_divergence_note
    # Informational only -- score/verdict are unaffected by the note.
    assert result.hard_fail is False


def test_ccc_exempt_when_no_inventory_across_window(monkeypatch):
    _fresh_engine(monkeypatch)
    no_inventory_annual = [{**row, "inventory": 0} for row in BALANCE_SHEET_ANNUAL]
    no_inventory_quarterly = [{**BALANCE_SHEET_QUARTERLY[0], "inventory": 0}]
    _patch_fmp(monkeypatch, balance_sheet_annual=no_inventory_annual)

    # Latest-quarter snapshot must also read as no-inventory for the
    # exemption to hold across "the recent reporting window", not just the
    # annual history.
    async def fake_balance_sheet_statement(ticker, period, limit):
        return no_inventory_annual if period == "annual" else no_inventory_quarterly

    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step4_data("crm"))

    assert result.ccc is None
    assert result.ccc_exempt_reason is not None
    assert result.components["ccc"] is None


def test_ccc_exemption_now_requires_zero_inventory_across_the_full_10yr_history(monkeypatch):
    # Only the recent 5 years (2021-2025) read as zero-inventory here; the
    # older 5 (2016-2020) carry real inventory. Now that scoring uses the
    # full 10yr window, the exemption must NOT fire -- a mixed history no
    # longer qualifies as "no physical inventory across the reporting
    # window" just because the most recent years happen to be clean.
    _fresh_engine(monkeypatch)
    mixed_inventory_annual = [
        {**row, "inventory": 0} if row["fiscalYear"] in {"2021", "2022", "2023", "2024", "2025"} else row
        for row in BALANCE_SHEET_ANNUAL
    ]
    zero_inventory_quarterly = [{**BALANCE_SHEET_QUARTERLY[0], "inventory": 0}]
    _patch_fmp(monkeypatch, balance_sheet_annual=mixed_inventory_annual)

    async def fake_balance_sheet_statement(ticker, period, limit):
        return mixed_inventory_annual if period == "annual" else zero_inventory_quarterly

    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step4_data("crm"))

    assert result.ccc is not None
    assert result.ccc_exempt_reason is None
    assert result.components["ccc"] is not None


def test_ccc_exemption_survives_a_noisy_latest_quarter_inventory_figure(monkeypatch):
    # Real-world finding (MA, NOW): FMP's latest-quarter inventory can be a
    # nonzero/negative data artifact even when all 5 annual filings show a
    # clean 0 -- the exemption must be driven by the stable annual history,
    # not a single noisy quarter.
    _fresh_engine(monkeypatch)
    no_inventory_annual = [{**row, "inventory": 0} for row in BALANCE_SHEET_ANNUAL]
    noisy_quarterly = [{**BALANCE_SHEET_QUARTERLY[0], "inventory": -28_000_000}]
    _patch_fmp(monkeypatch, balance_sheet_annual=no_inventory_annual)

    async def fake_balance_sheet_statement(ticker, period, limit):
        return no_inventory_annual if period == "annual" else noisy_quarterly

    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)

    result = asyncio.run(get_step4_data("now"))

    assert result.ccc is None
    assert result.ccc_exempt_reason is not None


def test_fail_from_persistently_poor_but_never_negative_roe(monkeypatch):
    # 2026-08-13 graduated-scale fix: a persistently poor but never-once-
    # negative ROE/ROIC (3% average) is no longer flattened into the same
    # hard_fail as a company actively destroying capital -- both grade
    # "weak_but_positive"/33. The verdict is still correctly Fail, though,
    # via the companion PASS_SCORE_THRESHOLD floor (score 60 < 70) --
    # confirming that fix's whole point: hard_fail is no longer the only
    # thing keeping a chronically-weak ticker from a false Pass.
    _fresh_engine(monkeypatch)
    poor_roe_metrics = [{**row, "returnOnEquity": 0.03, "returnOnInvestedCapital": 0.03} for row in KEY_METRICS_ANNUAL]
    _patch_fmp(monkeypatch, key_metrics_annual=poor_roe_metrics)

    async def fake_key_metrics_ttm(ticker):
        return [{"returnOnEquityTTM": 0.03, "returnOnInvestedCapitalTTM": 0.03}]

    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.hard_fail is False
    assert result.score == 60
    assert result.verdict == "Fail"
    assert result.components["roe"]["label"] == "weak_but_positive"
    assert result.components["roic"]["label"] == "weak_but_positive"


def test_hard_fail_from_negative_roe(monkeypatch):
    # Companion regression guard: a genuinely negative ROE/ROIC average
    # still hard_fails exactly as before this fix.
    _fresh_engine(monkeypatch)
    negative_roe_metrics = [{**row, "returnOnEquity": -0.03, "returnOnInvestedCapital": -0.03} for row in KEY_METRICS_ANNUAL]
    _patch_fmp(monkeypatch, key_metrics_annual=negative_roe_metrics)

    async def fake_key_metrics_ttm(ticker):
        return [{"returnOnEquityTTM": -0.03, "returnOnInvestedCapitalTTM": -0.03}]

    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.hard_fail is True
    assert result.verdict == "Fail"


def test_insufficient_data_when_no_annual_history(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, balance_sheet_annual=[], income_annual=[])

    result = asyncio.run(get_step4_data("aapl"))

    assert result.verdict == "insufficient_data"
    assert result.score is None


# --- AR manual-check reasoning note (2026-08-01) ------------------------------
# Purpose-built fixture (not the shared baseline above, whose revenue/AR
# shape is tuned for the ROE-window tests) with a clean, easy-to-verify DSO
# trajectory: revenue grows steadily ~5%/yr while AR's DSO ramps from ~100
# days (2016-2018) to ~160 days (2024-2025-TTM) -- a genuine +62 day
# aggregate gap, well past AR_DSO_TREND_MATERIALITY_DAYS (15).
_AR_NOTE_YEARS = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025"]
_AR_NOTE_REVENUE = [100, 105, 110, 116, 122, 128, 135, 142, 149, 156]
_AR_NOTE_DSO = [100, 100, 100, 120, 130, 140, 145, 150, 155, 160]


def _ar_note_fixtures(ocf_lagging: bool):
    # FMP returns annual rows MOST-RECENT-FIRST (step4_data._annual_series
    # reverses internally to get chronological) -- build these fixtures in
    # that same order, reversing our chronological source arrays.
    years_desc = list(reversed(_AR_NOTE_YEARS))
    revenue_desc = list(reversed(_AR_NOTE_REVENUE))
    dso_desc = list(reversed(_AR_NOTE_DSO))
    income_annual = [
        {"fiscalYear": y, "revenue": rev, "netIncome": rev * 0.15, "costOfRevenue": rev * 0.6}
        for y, rev in zip(years_desc, revenue_desc)
    ]
    balance_sheet_annual = [
        {
            "fiscalYear": y,
            "totalStockholdersEquity": 100.0,
            "accountsReceivables": rev * dso / 365,
            "inventory": rev * 0.1,
            "accountPayables": rev * 0.3,
        }
        for y, rev, dso in zip(years_desc, revenue_desc, dso_desc)
    ]
    # OCF flat (lagging a growing Net Income) vs. OCF scaling with revenue
    # like Net Income does (tracking) -- isolates the note's OCF-vs-NI
    # sentence branch independent of which AR signal drove the flag.
    cash_flow_annual = [
        {"fiscalYear": y, "netCashProvidedByOperatingActivities": 15.0 if ocf_lagging else rev * 0.15}
        for y, rev in zip(years_desc, revenue_desc)
    ]
    return income_annual, balance_sheet_annual, cash_flow_annual


def _ar_note_quarterly(revenue_ttm: float, ocf_ttm: float):
    income_quarterly = [{"date": "2026-03-28", "revenue": revenue_ttm / 4, "netIncome": revenue_ttm / 4 * 0.15, "costOfRevenue": revenue_ttm / 4 * 0.6}] * 4
    balance_sheet_quarterly = [
        {
            "date": "2026-03-28",
            "totalStockholdersEquity": 100.0,
            "accountsReceivables": revenue_ttm * 165 / 365,
            "inventory": revenue_ttm * 0.1,
            "accountPayables": revenue_ttm * 0.3,
        }
    ]
    cash_flow_quarterly = [{"date": "2026-03-28", "netCashProvidedByOperatingActivities": ocf_ttm / 4}] * 4
    return income_quarterly, balance_sheet_quarterly, cash_flow_quarterly


def test_ar_note_dso_driven_signal_and_lagging_ocf(monkeypatch):
    _fresh_engine(monkeypatch)
    income_annual, balance_sheet_annual, cash_flow_annual = _ar_note_fixtures(ocf_lagging=True)
    revenue_ttm = 164.0
    income_quarterly, balance_sheet_quarterly, cash_flow_quarterly = _ar_note_quarterly(revenue_ttm, ocf_ttm=15.0)

    async def fake_income_statement(ticker, period, limit):
        return income_annual if period == "annual" else income_quarterly

    async def fake_balance_sheet_statement(ticker, period, limit):
        return balance_sheet_annual if period == "annual" else balance_sheet_quarterly

    async def fake_cash_flow_statement(ticker, period, limit):
        return cash_flow_annual if period == "annual" else cash_flow_quarterly

    _patch_fmp(monkeypatch, income_annual=income_annual, balance_sheet_annual=balance_sheet_annual, cash_flow_annual=cash_flow_annual)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step4_data("arnote1"))

    ar = result.components["revenue_vs_ar"]
    assert ar["label"] == "outpacing_majority_or_red_flag"
    note = ar["note"]
    assert note is not None
    # The DSO-driven sentence, not the individual-year-count framing.
    assert "Days Sales Outstanding rose from" in note
    # OCF (flat at 15/yr) growing far slower than Net Income (scaling with
    # revenue) over the same window -- the lagging-OCF sentence, with real
    # computed numbers, not boilerplate.
    assert "worth double-checking whether revenue is being recognized before cash actually arrives" in note
    assert "Operating Cash Flow grew" in note and "Net Income grew" in note
    assert "business-model" not in note.lower() or "shifted toward longer-payment-term" in note


def test_ar_note_ocf_tracking_net_income_reads_less_concerning(monkeypatch):
    _fresh_engine(monkeypatch)
    income_annual, balance_sheet_annual, cash_flow_annual = _ar_note_fixtures(ocf_lagging=False)
    revenue_ttm = 164.0
    income_quarterly, balance_sheet_quarterly, cash_flow_quarterly = _ar_note_quarterly(revenue_ttm, ocf_ttm=164.0 * 0.15)

    async def fake_income_statement(ticker, period, limit):
        return income_annual if period == "annual" else income_quarterly

    async def fake_balance_sheet_statement(ticker, period, limit):
        return balance_sheet_annual if period == "annual" else balance_sheet_quarterly

    async def fake_cash_flow_statement(ticker, period, limit):
        return cash_flow_annual if period == "annual" else cash_flow_quarterly

    _patch_fmp(monkeypatch, income_annual=income_annual, balance_sheet_annual=balance_sheet_annual, cash_flow_annual=cash_flow_annual)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step4_data("arnote2"))

    note = result.components["revenue_vs_ar"]["note"]
    assert note is not None
    assert "roughly tracking Net Income's" in note
    assert "worth double-checking" not in note


def test_ar_note_missing_ocf_data_says_so_explicitly(monkeypatch):
    _fresh_engine(monkeypatch)
    income_annual, balance_sheet_annual, _ = _ar_note_fixtures(ocf_lagging=True)
    revenue_ttm = 164.0
    income_quarterly, balance_sheet_quarterly, _ = _ar_note_quarterly(revenue_ttm, ocf_ttm=15.0)

    async def fake_income_statement(ticker, period, limit):
        return income_annual if period == "annual" else income_quarterly

    async def fake_balance_sheet_statement(ticker, period, limit):
        return balance_sheet_annual if period == "annual" else balance_sheet_quarterly

    async def fake_cash_flow_statement(ticker, period, limit):
        return []  # simulates a cache/fetch gap -- no cash flow data at all

    _patch_fmp(monkeypatch, income_annual=income_annual, balance_sheet_annual=balance_sheet_annual, cash_flow_annual=[])
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step4_data("arnote3"))

    note = result.components["revenue_vs_ar"]["note"]
    assert note is not None
    assert "Operating Cash Flow data wasn't available" in note


def test_ar_note_absent_when_healthy(monkeypatch):
    _fresh_engine(monkeypatch)
    # Baseline fixture's recent-5yr AR/Revenue both compound at 10%/yr --
    # "healthy" -- and the full-10yr aggregate stays within materiality too.
    _patch_fmp(monkeypatch)

    result = asyncio.run(get_step4_data("aapl"))

    assert result.components["revenue_vs_ar"]["label"] == "healthy"
    assert result.components["revenue_vs_ar"]["note"] is None


# --- ROE negative-equity reasoning note ---------------------------------------
# Equity negative in FY2022-FY2023 only, recovered by TTM -- Net Income
# always positive and growing throughout (annual + TTM), Retained Earnings
# negative every year, buybacks recorded in 5 of 6 annual periods plus TTM.
# FMP-style rows are most-recent-first, matching this file's existing
# top-level fixtures (_annual_series reverses internally to chronological).
_NEG_EQ_INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 150.0, "netIncome": 20.0, "costOfRevenue": 90.0},
    {"fiscalYear": "2024", "revenue": 140.0, "netIncome": 18.0, "costOfRevenue": 84.0},
    {"fiscalYear": "2023", "revenue": 130.0, "netIncome": 16.0, "costOfRevenue": 78.0},
    {"fiscalYear": "2022", "revenue": 120.0, "netIncome": 14.0, "costOfRevenue": 72.0},
    {"fiscalYear": "2021", "revenue": 110.0, "netIncome": 12.0, "costOfRevenue": 66.0},
    {"fiscalYear": "2020", "revenue": 100.0, "netIncome": 10.0, "costOfRevenue": 60.0},
]

_NEG_EQ_BALANCE_SHEET_ANNUAL = [
    {"fiscalYear": "2025", "totalStockholdersEquity": 100.0, "accountsReceivables": 50.0, "inventory": 20.0, "accountPayables": 30.0, "retainedEarnings": -40.0},
    {"fiscalYear": "2024", "totalStockholdersEquity": 100.0, "accountsReceivables": 45.0, "inventory": 18.0, "accountPayables": 27.0, "retainedEarnings": -45.0},
    {"fiscalYear": "2023", "totalStockholdersEquity": -30.0, "accountsReceivables": 40.0, "inventory": 16.0, "accountPayables": 24.0, "retainedEarnings": -50.0},
    {"fiscalYear": "2022", "totalStockholdersEquity": -20.0, "accountsReceivables": 35.0, "inventory": 14.0, "accountPayables": 21.0, "retainedEarnings": -55.0},
    {"fiscalYear": "2021", "totalStockholdersEquity": 100.0, "accountsReceivables": 30.0, "inventory": 12.0, "accountPayables": 18.0, "retainedEarnings": -30.0},
    {"fiscalYear": "2020", "totalStockholdersEquity": 100.0, "accountsReceivables": 25.0, "inventory": 10.0, "accountPayables": 15.0, "retainedEarnings": -20.0},
]

_NEG_EQ_CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 22.0, "commonStockRepurchased": -30.0},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 20.0, "commonStockRepurchased": -25.0},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 18.0, "commonStockRepurchased": -20.0},
    {"fiscalYear": "2022", "netCashProvidedByOperatingActivities": 16.0, "commonStockRepurchased": -15.0},
    {"fiscalYear": "2021", "netCashProvidedByOperatingActivities": 14.0, "commonStockRepurchased": -10.0},
    {"fiscalYear": "2020", "netCashProvidedByOperatingActivities": 12.0, "commonStockRepurchased": 0.0},
]

_NEG_EQ_KEY_METRICS_ANNUAL = [
    {"fiscalYear": y, "returnOnEquity": 0.20, "returnOnInvestedCapital": 0.15}
    for y in ("2025", "2024", "2023", "2022", "2021", "2020")
]

# TTM: equity recovered to positive, Net Income keeps growing (22 > 20).
_NEG_EQ_INCOME_QUARTERLY = [{"date": "2026-03-28", "revenue": 40.0, "netIncome": 5.5, "costOfRevenue": 24.0}] * 4
_NEG_EQ_BALANCE_SHEET_QUARTERLY = [
    {
        "date": "2026-03-28",
        "totalStockholdersEquity": 110.0,
        "accountsReceivables": 52.0,
        "inventory": 21.0,
        "accountPayables": 31.0,
        "retainedEarnings": -35.0,
    }
]
_NEG_EQ_CASH_FLOW_QUARTERLY = [
    {"date": "2026-03-28", "netCashProvidedByOperatingActivities": 5.75, "commonStockRepurchased": -8.0}
] * 4
_NEG_EQ_KEY_METRICS_TTM = [{"returnOnEquityTTM": 0.20, "returnOnInvestedCapitalTTM": 0.15}]


def _patch_neg_equity_fmp(
    monkeypatch,
    sector="Technology",
    industry="Consumer Electronics",
    income_annual=None,
    balance_sheet_annual=None,
    cash_flow_annual=None,
    income_quarterly=None,
    cash_flow_quarterly=None,
):
    """Full quarterly control (unlike _patch_fmp's annual-only overrides) --
    every ROE-note test below needs a specific TTM shape (recovered equity,
    a specific Net Income shape, buybacks on/off), same reason the AR note
    tests layer custom quarterly fakes on top of _patch_fmp."""
    income_annual = income_annual if income_annual is not None else _NEG_EQ_INCOME_ANNUAL
    balance_sheet_annual = balance_sheet_annual if balance_sheet_annual is not None else _NEG_EQ_BALANCE_SHEET_ANNUAL
    cash_flow_annual = cash_flow_annual if cash_flow_annual is not None else _NEG_EQ_CASH_FLOW_ANNUAL
    income_quarterly = income_quarterly if income_quarterly is not None else _NEG_EQ_INCOME_QUARTERLY
    cash_flow_quarterly = cash_flow_quarterly if cash_flow_quarterly is not None else _NEG_EQ_CASH_FLOW_QUARTERLY

    async def fake_profile(ticker):
        return [{"sector": sector, "industry": industry}]

    async def fake_income_statement(ticker, period, limit):
        return income_annual if period == "annual" else income_quarterly

    async def fake_balance_sheet_statement(ticker, period, limit):
        return balance_sheet_annual if period == "annual" else _NEG_EQ_BALANCE_SHEET_QUARTERLY

    async def fake_key_metrics(ticker, period, limit):
        return _NEG_EQ_KEY_METRICS_ANNUAL

    async def fake_key_metrics_ttm(ticker):
        return _NEG_EQ_KEY_METRICS_TTM

    async def fake_cash_flow_statement(ticker, period, limit):
        return cash_flow_annual if period == "annual" else cash_flow_quarterly

    monkeypatch.setattr(step4_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)
    monkeypatch.setattr(step4_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)


def test_roe_note_positive_case_cites_equity_history_income_shape_and_buybacks(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_neg_equity_fmp(monkeypatch)

    result = asyncio.run(get_step4_data("negeq1"))

    roe = result.components["roe"]
    assert roe["label"] == "positive_despite_negative_equity"
    note = roe["note"]
    assert note is not None
    # Equity history: negative in FY2022-FY2023 (contiguous run), recovered
    # by TTM.
    assert "negative in 2022–2023" in note
    assert "recovered to positive" in note
    # Income shape: positive throughout and growing -- names the actual
    # driver, not just "equity was negative."
    assert "Net Income has been positive throughout the window and grew from" in note
    # Retained Earnings cited as informational context, not a cause.
    assert "Retained Earnings is currently negative" in note
    assert "doesn't indicate whether the negative equity above reflects accumulated losses" in note
    # Buybacks recorded in 5 of 6 annual periods + TTM = 6 of 7 reported
    # periods, framed as "consistent with," never "caused by."
    assert "share repurchases in 6 of the last 7 reported periods" in note
    assert "consistent with an active repurchase program" in note
    assert "caused by" not in note
    # 100pt research pointer.
    assert "shareholders'-equity note in the most recent 10-K" in note


def test_roe_note_60pt_case_flags_recovery_recency_and_alternate_pointer(monkeypatch):
    _fresh_engine(monkeypatch)
    # Same equity/RE/buyback shape as the 100pt case, but TTM Net Income is
    # a fresh loss -- a "recent_dip" shape (within DIP_RECOVERY_RECENCY_YEARS)
    # rather than "always_positive_growing".
    income_quarterly = [{"date": "2026-03-28", "revenue": 40.0, "netIncome": -5.0, "costOfRevenue": 24.0}] * 4
    _patch_neg_equity_fmp(monkeypatch, income_quarterly=income_quarterly)

    result = asyncio.run(get_step4_data("negeq2"))

    roe = result.components["roe"]
    assert roe["label"] == "negative_equity_inconsistent_income"
    note = roe["note"]
    assert note is not None
    assert "hasn't had time to clear the recovery-recency check yet" in note
    # 60pt research pointer, not the 100pt one.
    assert "structural/recurring" in note
    assert "shareholders'-equity note in the most recent 10-K" not in note


def test_roe_note_no_buybacks_states_so_explicitly(monkeypatch):
    _fresh_engine(monkeypatch)
    no_buyback_cash_flow = [{**row, "commonStockRepurchased": 0.0} for row in _NEG_EQ_CASH_FLOW_ANNUAL]
    no_buyback_quarterly = [{"date": "2026-03-28", "netCashProvidedByOperatingActivities": 5.75, "commonStockRepurchased": 0.0}] * 4
    _patch_neg_equity_fmp(monkeypatch, cash_flow_annual=no_buyback_cash_flow, cash_flow_quarterly=no_buyback_quarterly)

    result = asyncio.run(get_step4_data("negeq3"))

    note = result.components["roe"]["note"]
    assert note is not None
    assert "No material share repurchases were recorded over this window." in note
    assert "consistent with an active repurchase program" not in note


def test_roe_note_roic_exempt_company_type_states_plainly_not_silently(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_neg_equity_fmp(monkeypatch, sector="Financial Services", industry="Insurance - Life")

    result = asyncio.run(get_step4_data("negeq4"))

    assert result.company_type == "Insurance"
    assert result.components["roic"] is None
    note = result.components["roe"]["note"]
    assert note is not None
    assert "ROIC isn't computed for Insurance companies, so it isn't available as a cross-check here." in note


def test_roe_note_absent_when_equity_never_negative(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch)  # baseline fixture -- equity is always 100.0

    result = asyncio.run(get_step4_data("aapl"))

    assert result.components["roe"]["label"] not in (
        "positive_despite_negative_equity",
        "negative_equity_inconsistent_income",
    )
    assert result.components["roe"]["note"] is None


# REIT-only ROA/Gearing leverage note (see data/step4_data.py::
# _reit_leverage_note_sentence) -- reuses _NEG_EQ_BALANCE_SHEET_ANNUAL's
# equity/retainedEarnings/AR/inventory/AP shape (still negative equity in
# FY2022-2023, recovered by TTM) with totalAssets/totalDebt added. Chosen so
# Gearing (totalDebt/totalAssets) rises monotonically 40% -> 90% in both
# fixtures below, while Net Income (and therefore ROA) differs between them
# -- proving the warning clause requires BOTH signals to diverge, not
# gearing alone.
_REIT_LEVERAGE_BALANCE_SHEET_ANNUAL = [
    {**row, "totalAssets": assets, "totalDebt": debt}
    for row, assets, debt in zip(
        _NEG_EQ_BALANCE_SHEET_ANNUAL,
        [1400.0, 1000.0, 700.0, 400.0, 200.0, 100.0],  # newest (2025) first
        [1260.0, 800.0, 490.0, 240.0, 100.0, 40.0],
    )
]


def test_reit_roe_note_flags_declining_roa_and_rising_gearing_divergence(monkeypatch):
    # Net Income grows steadily (10 -> 20, same as _NEG_EQ_INCOME_ANNUAL) but
    # Total Assets grows far faster (100 -> 1400) -- ROA genuinely declines
    # (10% -> ~1.4%) even though Net Income itself looks fine, the exact IRM
    # pattern the investigation found: the NI-only substitute reads "fine"
    # while ROA quietly deteriorates and leverage climbs every year.
    _fresh_engine(monkeypatch)
    _patch_neg_equity_fmp(
        monkeypatch,
        sector="Real Estate",
        industry="REIT - Specialty",
        balance_sheet_annual=_REIT_LEVERAGE_BALANCE_SHEET_ANNUAL,
    )

    result = asyncio.run(get_step4_data("reitneg1"))

    assert result.company_type == "REIT/Property Developer"
    roe = result.components["roe"]
    assert roe["label"] == "positive_despite_negative_equity"
    note = roe["note"]
    assert note is not None
    assert "Return on Assets has declined" in note
    assert "Gearing has risen" in note
    assert "may warrant a closer look" in note


def test_reit_roe_note_shows_context_without_warning_when_roa_improves(monkeypatch):
    # Same Gearing trend (rising 40% -> 90%) as the declining case above, but
    # Net Income grows much faster than Total Assets so ROA improves despite
    # rising leverage -- the SBAC pattern. Proves the warning clause needs
    # BOTH ROA declining AND Gearing rising, not gearing alone.
    _fresh_engine(monkeypatch)
    improving_roa_income_annual = [
        {**row, "netIncome": ni}
        for row, ni in zip(_NEG_EQ_INCOME_ANNUAL, [112.0, 50.0, 21.0, 4.0, 2.0, 1.0])  # newest (2025) first
    ]
    _patch_neg_equity_fmp(
        monkeypatch,
        sector="Real Estate",
        industry="REIT - Specialty",
        income_annual=improving_roa_income_annual,
        balance_sheet_annual=_REIT_LEVERAGE_BALANCE_SHEET_ANNUAL,
    )

    result = asyncio.run(get_step4_data("reitneg2"))

    assert result.company_type == "REIT/Property Developer"
    roe = result.components["roe"]
    assert roe["label"] == "positive_despite_negative_equity"
    note = roe["note"]
    assert note is not None
    assert "Return on Assets has improved" in note
    assert "Gearing has risen" in note
    assert "may warrant a closer look" not in note


def test_reit_leverage_note_absent_for_non_reit_even_with_the_same_data(monkeypatch):
    # Same declining-ROA/rising-gearing balance sheet data as the divergence
    # test above, but a Standard company type -- proves the sentence is
    # gated on company_type, not just on data availability.
    _fresh_engine(monkeypatch)
    _patch_neg_equity_fmp(monkeypatch, balance_sheet_annual=_REIT_LEVERAGE_BALANCE_SHEET_ANNUAL)

    result = asyncio.run(get_step4_data("stdneg1"))

    assert result.company_type == "Standard"
    note = result.components["roe"]["note"]
    assert note is not None
    assert "Return on Assets" not in note
    assert "Gearing" not in note


# HWM's real ROE/ROIC shape (as percentages -> converted to FMP's fractional
# convention below): an early crash (2016-2017) that durably recovers,
# with recent (2021-2025+TTM) performance comfortably strong on its own --
# this is the exact motivating case for recovery-aware exclusion (Candidate
# C-broad). Equity stays flat/positive throughout so the negative-equity
# substitute never engages, isolating the exclusion mechanism's own note.
_HWM_SHAPED_KEY_METRICS_ANNUAL = [
    {"fiscalYear": "2025", "returnOnEquity": 0.282, "returnOnInvestedCapital": 0.182},
    {"fiscalYear": "2024", "returnOnEquity": 0.254, "returnOnInvestedCapital": 0.155},
    {"fiscalYear": "2023", "returnOnEquity": 0.189, "returnOnInvestedCapital": 0.110},
    {"fiscalYear": "2022", "returnOnEquity": 0.130, "returnOnInvestedCapital": 0.091},
    {"fiscalYear": "2021", "returnOnEquity": 0.074, "returnOnInvestedCapital": 0.077},
    {"fiscalYear": "2020", "returnOnEquity": 0.059, "returnOnInvestedCapital": 0.083},
    {"fiscalYear": "2019", "returnOnEquity": 0.102, "returnOnInvestedCapital": 0.049},
    {"fiscalYear": "2018", "returnOnEquity": 0.115, "returnOnInvestedCapital": 0.064},
    {"fiscalYear": "2017", "returnOnEquity": -0.015, "returnOnInvestedCapital": -0.014},
    {"fiscalYear": "2016", "returnOnEquity": -0.183, "returnOnInvestedCapital": -0.180},
]
_HWM_SHAPED_KEY_METRICS_TTM = [{"returnOnEquityTTM": 0.344, "returnOnInvestedCapitalTTM": 0.186}]


def test_recovery_exclusion_note_on_hwm_shaped_roe_and_roic(monkeypatch):
    _fresh_engine(monkeypatch)
    _patch_fmp(monkeypatch, key_metrics_annual=_HWM_SHAPED_KEY_METRICS_ANNUAL)

    async def fake_key_metrics_ttm(ticker):
        return _HWM_SHAPED_KEY_METRICS_TTM

    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)

    result = asyncio.run(get_step4_data("hwm"))

    roe = result.components["roe"]
    assert roe["label"] == "excellent"
    assert roe["note"] is not None
    assert "5 early year(s) (2016–2020) excluded from this average" in roe["note"]
    assert "durably recovered" in roe["note"]

    roic = result.components["roic"]
    assert roic["label"] == "good"
    assert roic["note"] is not None
    assert "6 early year(s) (2016–2021) excluded from this average" in roic["note"]

    # Neither note should read as if the exclusion made things better --
    # the wording is mechanism-only, never a claimed improvement.
    assert "improve" not in roe["note"]
    assert "improve" not in roic["note"]
