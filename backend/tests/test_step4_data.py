import asyncio

from sqlmodel import SQLModel, create_engine

import step4_data
from step4_data import get_step4_data

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


def _patch_fmp(
    monkeypatch,
    sector="Technology",
    industry="Consumer Electronics",
    income_annual=None,
    balance_sheet_annual=None,
    key_metrics_annual=None,
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

    monkeypatch.setattr(step4_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step4_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_balance_sheet_statement", fake_balance_sheet_statement)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics", fake_key_metrics)
    monkeypatch.setattr(step4_data.fmp_client, "get_key_metrics_ttm", fake_key_metrics_ttm)


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

    assert extended.score == 80
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

    # CCC exemption is separate, data-driven (zero-inventory detection) --
    # must be unaffected by the ROIC fix. This fixture's balance sheet has
    # non-zero inventory, so CCC should still be scored normally.
    assert result.ccc is not None
    assert result.ccc_exempt_reason is None
    assert result.components["ccc"] is not None


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


def test_hard_fail_from_persistently_poor_roe(monkeypatch):
    _fresh_engine(monkeypatch)
    poor_roe_metrics = [{**row, "returnOnEquity": 0.03, "returnOnInvestedCapital": 0.03} for row in KEY_METRICS_ANNUAL]
    _patch_fmp(monkeypatch, key_metrics_annual=poor_roe_metrics)

    async def fake_key_metrics_ttm(ticker):
        return [{"returnOnEquityTTM": 0.03, "returnOnInvestedCapitalTTM": 0.03}]

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
