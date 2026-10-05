import asyncio

import httpx
import pytest
from sqlmodel import SQLModel, create_engine

import data.step1_data as step1_data
from data.step1_data import get_step1_data

PROFILE = [{"sector": "Technology", "industry": "Consumer Electronics"}]

INCOME_ANNUAL = [
    {"fiscalYear": "2025", "revenue": 300, "netInterestIncome": 130, "grossProfit": 150, "operatingIncome": 100, "netIncome": 80},
    {"fiscalYear": "2024", "revenue": 250, "netInterestIncome": 110, "grossProfit": 120, "operatingIncome": 80, "netIncome": 60},
    {"fiscalYear": "2023", "revenue": 200, "netInterestIncome": 90, "grossProfit": 100, "operatingIncome": 60, "netIncome": 40},
]

INCOME_QUARTERLY = [
    {"date": "2026-03-31", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-12-31", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-09-30", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
    {"date": "2025-06-30", "revenue": 80, "netInterestIncome": 35, "grossProfit": 40, "operatingIncome": 27, "netIncome": 21},
]

CASH_FLOW_ANNUAL = [
    {"fiscalYear": "2025", "netCashProvidedByOperatingActivities": 90, "capitalExpenditure": -20},
    {"fiscalYear": "2024", "netCashProvidedByOperatingActivities": 70, "capitalExpenditure": -15},
    {"fiscalYear": "2023", "netCashProvidedByOperatingActivities": 50, "capitalExpenditure": -10},
]

CASH_FLOW_QUARTERLY = [{"netCashProvidedByOperatingActivities": 24, "capitalExpenditure": -5} for _ in range(4)]


def _patch_fmp(monkeypatch, call_count, sector="Technology", industry="Consumer Electronics"):
    async def fake_profile(ticker):
        call_count["profile"] += 1
        return [{"sector": sector, "industry": industry}]

    async def fake_income_statement(ticker, period, limit):
        call_count[f"income_{period}"] += 1
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        call_count[f"cash_flow_{period}"] += 1
        return CASH_FLOW_ANNUAL if period == "annual" else CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)


def _fresh_engine(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)
    return test_engine


def test_get_step1_data_builds_series_and_ttm_and_caches(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
    _patch_fmp(monkeypatch, call_count)

    result = asyncio.run(get_step1_data("aapl"))

    assert result.ticker == "AAPL"
    assert result.years == ["2023", "2024", "2025", "TTM"]
    assert result.revenue == [200, 250, 300, 320]
    assert result.revenue_label == "Revenue"
    assert result.net_income == [40, 60, 80, 84]
    assert result.cfo == [50, 70, 90, 96]
    # capitalExpenditure is already negative (FMP convention) -- FCF = CFO +
    # capitalExpenditure: 50-10=40, 70-15=55, 90-20=70, TTM 96-20=76.
    assert result.fcf == [40, 55, 70, 76]
    assert result.gross_margin[0] == 50.0
    assert result.cfo_exempt_reason is None
    assert result.components["cfo"] is not None
    assert result.components["fcf"]["pattern"] == "consistently_positive"
    assert result.components["fcf"]["score"] == 100
    assert 0 <= result.score <= 100
    assert result.verdict in {"Strong Pass", "Pass", "Fail"}
    assert call_count == {
        "profile": 1,
        "income_annual": 1,
        "income_quarter": 1,
        "cash_flow_annual": 1,
        "cash_flow_quarter": 1,
    }

    # Second call within the staleness window should hit the cache, not FMP again.
    asyncio.run(get_step1_data("aapl"))
    assert call_count == {
        "profile": 1,
        "income_annual": 1,
        "income_quarter": 1,
        "cash_flow_annual": 1,
        "cash_flow_quarter": 1,
    }


# TEAM's actual FY2026/Q4 FY2026 shape (2026-08-16 investigation): the Q4
# quarterly row is byte-identical to the annual row for revenue/netIncome/
# CFO (but not for other fields like ebitda -- not modeled here, out of
# scope for Step 1). Real values.
TEAM_INCOME_ANNUAL = [{"fiscalYear": "2026", "revenue": 6_572_308_000, "netInterestIncome": 0, "grossProfit": 5_575_478_000, "operatingIncome": 11_366_000, "netIncome": -53_828_000}]

TEAM_INCOME_QUARTERLY = [
    {"date": "2026-06-30", "period": "Q4", "fiscalYear": "2026", "revenue": 6_572_308_000, "netInterestIncome": 20_260_000, "grossProfit": 5_575_478_000, "operatingIncome": 10_355_000, "netIncome": -53_828_000},
    {"date": "2026-03-31", "period": "Q3", "fiscalYear": "2026", "revenue": 1_786_971_000, "netInterestIncome": 20_260_000, "grossProfit": 1_500_000_000, "operatingIncome": 2_000_000, "netIncome": -98_389_000},
    {"date": "2025-12-31", "period": "Q2", "fiscalYear": "2026", "revenue": 1_586_315_000, "netInterestIncome": 20_260_000, "grossProfit": 1_300_000_000, "operatingIncome": 1_000_000, "netIncome": -42_645_000},
    {"date": "2025-09-30", "period": "Q1", "fiscalYear": "2026", "revenue": 1_432_553_000, "netInterestIncome": 20_260_000, "grossProfit": 1_200_000_000, "operatingIncome": 500_000, "netIncome": -51_870_000},
]

TEAM_CASH_FLOW_ANNUAL = [{"fiscalYear": "2026", "netCashProvidedByOperatingActivities": 1_353_135_000, "capitalExpenditure": -34_060_000}]

TEAM_CASH_FLOW_QUARTERLY = [
    {"period": "Q4", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 1_353_135_000, "capitalExpenditure": -34_060_000},
    {"period": "Q3", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 567_475_000, "capitalExpenditure": -6_211_000},
    {"period": "Q2", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 177_805_000, "capitalExpenditure": -9_289_000},
    {"period": "Q1", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 128_715_000, "capitalExpenditure": -14_112_000},
]


def test_get_step1_data_corrects_team_shaped_duplicate_annual_quarter(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    async def fake_profile(ticker):
        return PROFILE

    async def fake_income_statement(ticker, period, limit):
        return TEAM_INCOME_ANNUAL if period == "annual" else TEAM_INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return TEAM_CASH_FLOW_ANNUAL if period == "annual" else TEAM_CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("team"))

    # TTM revenue/cfo resolve to the annual figure itself (the true isolated
    # Q4 + the other 3 known-good quarters always sum back to it by
    # construction) -- not the raw, ~1.7x-inflated double-count a pre-fix
    # Fathom would have shown (revenue TTM would have read ~$11.38B against
    # real cached TEAM data with this same shape).
    assert result.revenue[-1] == 6_572_308_000
    assert result.cfo[-1] == 1_353_135_000
    # net_income is the one exception since the Defect-B plausibility check
    # (2026-10-05): TEAM's true isolated Q4 net income is +139.1M against
    # three loss quarters (-98.4M/-42.6M/-51.9M), a genuine sign flip, which
    # the check cannot tell apart from a stub annual row (FERG/AZO) and so
    # skips -- the quarters stay as reported and TTM is the raw sum, not the
    # annual -53.8M. Known cost of the rule, reported to the owner.
    assert result.net_income[-1] == -53_828_000 - 98_389_000 - 42_645_000 - 51_870_000
    # No revenue/net_income/cfo outlier warning -- revenue/cfo correctly
    # resolved by the duplicate-annual correction; net_income has no
    # 4-quarter baseline to flag against.
    flagged_metrics = {w.metric for w in result.outlier_warnings}
    assert "revenue" not in flagged_metrics
    assert "net_income" not in flagged_metrics
    assert "cfo" not in flagged_metrics


def test_bank_is_cfo_exempt(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
    _patch_fmp(monkeypatch, call_count, sector="Financial Services", industry="Banks - Diversified")

    result = asyncio.run(get_step1_data("jpm"))

    assert result.cfo_exempt_reason == "Bank"
    # Display is decoupled from scoring (2026-09-11): real CFO/FCF values
    # still populate here for the UI even though the ticker is CFO-exempt --
    # only components["cfo"]/["fcf"] (what actually feeds the score) reads
    # None. Same fixture data as the base (non-exempt) test above, since
    # exemption never touches the raw cash-flow-statement parsing.
    assert result.cfo == [50, 70, 90, 96]
    assert result.components["cfo"] is None

    # FCF mirrors CFO's exemption exactly -- derived from CFO, so it's not a
    # reliable signal for Banks either. Still displayed, not scored.
    assert result.fcf == [40, 55, 70, 76]
    assert result.components["fcf"] is None

    # Change 1: Banks show Net Interest Income in place of Revenue, clearly
    # labeled -- not silently substituted under the old "Revenue" label.
    assert result.revenue_label == "Net Interest Income"
    assert result.revenue == [90, 110, 130, 140]

    # Margins must stay tied to real Revenue, not NII -- gross margin here
    # should read against the 200/250/300/320 revenue series, not NII.
    assert result.gross_margin[0] == 50.0  # grossProfit 100 / revenue 200 * 100

    # Margins (2026-09-10): excluded from SCORING for Banks specifically --
    # same mechanism as CFO/FCF above -- but the raw gross_margin/net_margin
    # series above are still populated for display (a scoping decision, not
    # an oversight: only the score, not the raw chart data, is suppressed).
    assert result.components["margins"] is None
    # Weight redistributes proportionally across Revenue/Net Income only
    # (28/47, 19/47 -- see WEIGHTS_CFO_MARGINS_EXEMPT's own comment).
    assert result.weights["margins"] == 0.0
    assert result.weights["revenue"] == pytest.approx(28 / 47, abs=1e-5)
    assert result.weights["net_income"] == pytest.approx(19 / 47, abs=1e-5)


def test_insurance_is_cfo_exempt_but_keeps_revenue_label(monkeypatch):
    # MET/PGR-shaped: sector "Financial Services", industry "Insurance -
    # Life" -- Insurance now gets the same CFO/FCF de-emphasis Bank already
    # had (claim timing/reserve movements/investment portfolio fluctuations
    # make OCF noisy for insurers too), but must NOT get Bank's Net Interest
    # Income revenue-label swap -- that's Bank-only.
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
    _patch_fmp(monkeypatch, call_count, sector="Financial Services", industry="Insurance - Life")

    result = asyncio.run(get_step1_data("met"))

    assert result.cfo_exempt_reason == "Insurance"
    # Display decoupled from scoring, same as Bank above -- real values
    # still populate, only the score-facing components read None.
    assert result.cfo == [50, 70, 90, 96]
    assert result.components["cfo"] is None
    assert result.fcf == [40, 55, 70, 76]
    assert result.components["fcf"] is None

    # Unlike Bank, Insurance keeps the plain Revenue label/series -- no NII
    # swap.
    assert result.revenue_label == "Revenue"
    assert result.revenue == [200, 250, 300, 320]

    # Unlike Bank (2026-09-10), Insurance is NOT in MARGINS_EXEMPT_TYPES --
    # margins stays scored normally, still on WEIGHTS_CFO_EXEMPT's 3-way
    # (Revenue/Net Income/Margins) split, not the 2-way Bank-only one.
    assert result.components["margins"] is not None
    assert result.weights["margins"] == pytest.approx(13 / 60, abs=1e-5)


def test_property_developer_and_commodity_company_also_keep_margins_scored(monkeypatch):
    # Rounds out the MARGINS_EXEMPT_TYPES={"Bank"} confirmation -- Property
    # Developer/REIT and Commodity Company are CFO-exempt but, like
    # Insurance above, are deliberately NOT margins-exempt (see
    # MARGINS_EXEMPT_TYPES's own comment in step1_data.py: their margins
    # noise, where it exists at all, has a different root cause than
    # Banks' universal one and wasn't in scope for this fix).
    for sector, industry, expected_reason in [
        ("Real Estate", "REIT - Residential", "Property Developer"),
        ("Basic Materials", "Chemicals - Specialty", "Commodity Company"),
    ]:
        test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(test_engine)
        monkeypatch.setattr(step1_data, "engine", test_engine)

        call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
        _patch_fmp(monkeypatch, call_count, sector=sector, industry=industry)

        result = asyncio.run(get_step1_data("test"))

        assert result.cfo_exempt_reason == expected_reason
        # Display decoupled from scoring (2026-09-11) -- real CFO/FCF still
        # populate for these two exempt types too, not just Bank/Insurance
        # above (this is the LIN/APD/ECL-shaped bug fix: Commodity Company's
        # own real cash-flow numbers should render on the Financials tab
        # even though CFO/FCF are excluded from the Step 1 score).
        assert result.cfo == [50, 70, 90, 96]
        assert result.fcf == [40, 55, 70, 76]
        assert result.components["cfo"] is None
        assert result.components["margins"] is not None
        assert result.weights["margins"] == pytest.approx(13 / 60, abs=1e-5)


def test_margins_severity_carveout_wiring_by_company_type(monkeypatch):
    # Orchestration-level wiring check (the graduated-formula math itself
    # is covered exhaustively in scoring/test_step1.py) -- confirms
    # step1_data.py computes `margins_severity_carveout` correctly per
    # company type and threads it through to score_step1, by intercepting
    # the actual kwarg score_step1 is called with rather than re-deriving
    # the score. Insurance/REIT-Property-Developer/Utility -> True; Bank
    # never even reaches this decision in practice (margins_exempt short-
    # circuits it first) but is included as a defensive check that the
    # carveout set and the exempt set don't silently overlap in a way that
    # would matter; Commodity Company and a plain Standard company -> False.
    captured: dict = {}
    real_score_step1 = step1_data.score_step1

    def capturing_score_step1(*args, **kwargs):
        captured["margins_severity_carveout"] = kwargs.get("margins_severity_carveout")
        captured["margins_exempt"] = kwargs.get("margins_exempt")
        return real_score_step1(*args, **kwargs)

    monkeypatch.setattr(step1_data, "score_step1", capturing_score_step1)

    cases = [
        ("Financial Services", "Banks - Diversified", False, True),  # Bank: exempt short-circuits carveout
        ("Financial Services", "Insurance - Life", True, False),
        ("Real Estate", "REIT - Residential", True, False),
        ("Utilities", "Utilities - Regulated Electric", True, False),
        ("Basic Materials", "Chemicals - Specialty", False, False),
        ("Technology", "Consumer Electronics", False, False),
    ]
    for sector, industry, expected_carveout, expected_margins_exempt in cases:
        test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(test_engine)
        monkeypatch.setattr(step1_data, "engine", test_engine)
        call_count = {"profile": 0, "income_annual": 0, "income_quarter": 0, "cash_flow_annual": 0, "cash_flow_quarter": 0}
        _patch_fmp(monkeypatch, call_count, sector=sector, industry=industry)

        asyncio.run(get_step1_data("test"))

        assert captured["margins_severity_carveout"] is expected_carveout, (sector, industry)
        assert captured["margins_exempt"] is expected_margins_exempt, (sector, industry)


def test_insufficient_data_when_cash_flow_fetch_fails(monkeypatch):
    # Mirrors the confirmed Step 1 repro: a genuine FMP fetch failure on ONE
    # of Step 1's 5 independently-isolated safe_fetch calls (cash flow) must
    # not fabricate a scored Fail out of an otherwise-strong ticker -- Revenue/
    # Net Income/Margins here are all real and strong (grows_every_year /
    # stable_or_expanding); only CFO/FCF read as insufficient_data. Same
    # insufficient_data convention as Step 2's fix (see CLAUDE.md).
    _fresh_engine(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("TEST"))

    assert result.score is None
    assert result.verdict == "insufficient_data"
    assert result.components == {}


def test_insufficient_data_when_total_fetch_failure(monkeypatch):
    # Every underlying fetch failing (profile + income statement + cash
    # flow) must collapse to the same insufficient_data state as the
    # single-endpoint failure above, not a maximally-negative fabricated
    # Fail.
    _fresh_engine(monkeypatch)

    async def raise_error(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", raise_error)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", raise_error)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", raise_error)

    result = asyncio.run(get_step1_data("TEST"))

    assert result.score is None
    assert result.verdict == "insufficient_data"
    assert result.components == {}


def test_insufficient_data_when_genuinely_thin_cash_flow_history(monkeypatch):
    # Not a fetch failure -- FMP responds successfully but with zero annual
    # cash-flow filings (a real data gap for this ticker, e.g. a data
    # provider coverage gap). Must land on the same insufficient_data state
    # as an actual fetch failure above, not a scored Fail -- the two are
    # deliberately indistinguishable downstream (see CLAUDE.md's Step 1/
    # Step 2 deviations).
    _fresh_engine(monkeypatch)

    async def fake_profile(ticker):
        return [{"sector": "Technology", "industry": "Consumer Electronics"}]

    async def fake_income_statement(ticker, period, limit):
        return INCOME_ANNUAL if period == "annual" else INCOME_QUARTERLY

    async def fake_cash_flow_statement(ticker, period, limit):
        return [] if period == "annual" else CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("TEST"))

    assert result.score is None
    assert result.verdict == "insufficient_data"


# --- Operating Income backup gates wired to the real TTM slots (K2) ---------

_BACKUP_ANNUAL = [
    {"fiscalYear": str(2021 + i), "revenue": rev, "netInterestIncome": 0, "grossProfit": rev // 2, "operatingIncome": oi, "netIncome": ni}
    for i, (rev, oi, ni) in enumerate(zip([600, 700, 800, 900, 1000], [200, 220, 240, 260, 280], [100, 60, 90, 55, 95]))
][::-1]


def _backup_quarters(oi_per_quarter, revenue_per_quarter=250):
    return [
        {"date": f"2026-0{q}-28", "revenue": revenue_per_quarter, "netInterestIncome": 0, "grossProfit": 100, "operatingIncome": oi, "netIncome": 24}
        for q, oi in zip((4, 3, 2, 1), oi_per_quarter)
    ]


def _run_backup_case(monkeypatch, quarters):
    _fresh_engine(monkeypatch)

    async def fake_profile(ticker):
        return PROFILE

    async def fake_income(ticker, period, limit):
        return _BACKUP_ANNUAL if period == "annual" else quarters

    async def fake_cash_flow(ticker, period, limit):
        return CASH_FLOW_ANNUAL if period == "annual" else CASH_FLOW_QUARTERLY

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow)
    return asyncio.run(get_step1_data("bkup")).components["net_income"]


def test_backup_gates_read_the_real_ttm_slots(monkeypatch):
    # TTM OI 280 on TTM revenue 1000 = 28%, 5 of 5 positive: lifted.
    assert _run_backup_case(monkeypatch, _backup_quarters([70, 70, 70, 70]))["used_operating_income_backup"] is True
    # TTM OI 48 on 1000 = 4.8%: margin gate blocks.
    assert _run_backup_case(monkeypatch, _backup_quarters([12, 12, 12, 12]))["used_operating_income_backup"] is False
    # One quarter's OI missing -> TTM OI is None -> gate fails (even though
    # the cleaned annual series alone would pass every gate).
    assert _run_backup_case(monkeypatch, _backup_quarters([70, 70, 70, None]))["used_operating_income_backup"] is False


# AZO-shaped: the newest quarter's cash-flow row (and the FY annual row) is an
# all-zero placeholder beside a real income statement.
def _azo_income_quarter(date, period, net_income=100):
    return {"date": date, "period": period, "fiscalYear": "2026", "revenue": 1000, "netInterestIncome": 0,
            "grossProfit": 500, "operatingIncome": 200, "netIncome": net_income}


def _azo_cash_flow_quarter(date, period, cfo=200, capex=-50):
    return {"date": date, "period": period, "fiscalYear": "2026", "netCashProvidedByOperatingActivities": cfo,
            "capitalExpenditure": capex, "freeCashFlow": cfo + capex, "netCashProvidedByInvestingActivities": capex,
            "netCashProvidedByFinancingActivities": -10}


def test_get_step1_data_treats_placeholder_cash_flow_rows_as_missing(monkeypatch):
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(test_engine)
    monkeypatch.setattr(step1_data, "engine", test_engine)

    quarters = [("2026-08-29", "Q4"), ("2026-05-09", "Q3"), ("2026-02-14", "Q2"), ("2025-11-22", "Q1"), ("2025-08-30", "Q4")]
    income_quarterly = [_azo_income_quarter(d, p) for d, p in quarters]
    cash_flow_quarterly = [
        {**_azo_cash_flow_quarter(*quarters[0], cfo=0, capex=0), "freeCashFlow": 0, "netCashProvidedByInvestingActivities": 0,
         "netCashProvidedByFinancingActivities": 0},
        *[_azo_cash_flow_quarter(d, p) for d, p in quarters[1:]],
    ]
    income_annual = [
        {"date": "2026-08-29", "period": "FY", "fiscalYear": "2026", "revenue": 4000, "netInterestIncome": 0, "grossProfit": 2000,
         "operatingIncome": 800, "netIncome": 400},
        {"date": "2025-08-30", "period": "FY", "fiscalYear": "2025", "revenue": 3800, "netInterestIncome": 0, "grossProfit": 1900,
         "operatingIncome": 760, "netIncome": 380},
    ]
    cash_flow_annual = [
        {"date": "2026-08-29", "period": "FY", "fiscalYear": "2026", "netCashProvidedByOperatingActivities": 0,
         "capitalExpenditure": 0, "freeCashFlow": 0, "netCashProvidedByInvestingActivities": 0,
         "netCashProvidedByFinancingActivities": 0},
        {"date": "2025-08-30", "period": "FY", "fiscalYear": "2025", "netCashProvidedByOperatingActivities": 780,
         "capitalExpenditure": -190, "freeCashFlow": 590, "netCashProvidedByInvestingActivities": -190,
         "netCashProvidedByFinancingActivities": -40},
    ]

    async def fake_profile(ticker):
        return PROFILE

    async def fake_income_statement(ticker, period, limit):
        return income_annual if period == "annual" else income_quarterly

    async def fake_cash_flow_statement(ticker, period, limit):
        return cash_flow_annual if period == "annual" else cash_flow_quarterly

    monkeypatch.setattr(step1_data.fmp_client, "get_profile", fake_profile)
    monkeypatch.setattr(step1_data.fmp_client, "get_income_statement", fake_income_statement)
    monkeypatch.setattr(step1_data.fmp_client, "get_cash_flow_statement", fake_cash_flow_statement)

    result = asyncio.run(get_step1_data("azo"))

    # TTM CFO is the last four VALID quarters (Q3, Q2, Q1 FY26 and Q4 FY25 = 4 x 200),
    # not 0 and not a 3-quarter 600. Revenue TTM keeps the real newest quarter.
    assert result.cfo[-1] == 800
    assert result.revenue[-1] == 4000
    # The placeholder FY2026 annual CFO reads as missing, not as a reported 0, and
    # FY2025 stays aligned to its own year.
    assert result.cfo[result.years.index("2026")] is None
    assert result.cfo[result.years.index("2025")] == 780
