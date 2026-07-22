from datetime import date, datetime

from pydantic import BaseModel


class SecCrossCheck(BaseModel):
    """Result of cross-checking an outlier-flagged Net Interest Expense or
    CFO quarter against SEC EDGAR's own XBRL filing data (see sec_edgar.py).
    `available=False` whenever the lookup itself couldn't complete (no CIK,
    no matching tag/period, network error) -- the original outlier warning
    is always still shown regardless, this is additive-only."""

    available: bool
    sec_value: float | None = None
    tag_used: str | None = None
    matches_fmp: bool | None = None
    note: str


class OutlierWarning(BaseModel):
    """A TTM-summed flow metric where one of the 4 summed quarters looked
    anomalous against its trailing history -- informational only, never
    changes the number it's attached to, a score, or a verdict (see
    ttm.py::sum_last_four_quarters)."""

    metric: str
    date: str | None = None
    value: float
    trailing_median: float
    # Only populated for the Debt Servicing Ratio's own two inputs
    # (net_interest_expense_ttm, cfo_ttm) -- see step5_data.py.
    sec_cross_check: SecCrossCheck | None = None


class RefreshResult(BaseModel):
    ticker: str
    cleared_entries: int
    statement_types: list[str]


class TickerSummaryOut(BaseModel):
    company_name: str | None = None
    ticker: str
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    # FMP's own company-profile prose blurb -- shown as-is on the ticker
    # page's Summary tab, not generated/edited by this app.
    description: str | None = None
    price: float | None = None
    change: float | None = None
    change_percent: float | None = None
    market_cap: float | None = None
    beta: float | None = None
    perf_1m: float | None = None
    perf_6m: float | None = None
    eps_growth_3_5y: float | None = None
    pe_ratio: float | None = None
    next_earnings_date: date | None = None
    # Same figures Step 5's debt ratios are built from (backend/debt_metrics.py)
    # -- latest-quarter snapshot for total_debt, TTM for the other two.
    # Shown for every company type, including Bank/REIT: these are raw
    # figures, not Step 5's classified ratios, so there's no exemption here.
    total_debt: float | None = None
    ebitda_ttm: float | None = None
    # Gross figures, not netted against each other.
    interest_expense_ttm: float | None = None
    interest_income_ttm: float | None = None
    outlier_warnings: list[OutlierWarning] = []
    # Sourced from Step 3's valuation result (see step3_data.py::get_step3_data)
    # -- None when Step 3 selected PASS (no valuation method applies) or
    # couldn't compute a value from available data.
    fair_value_price: float | None = None
    fair_value_verdict: str | None = None
    # e.g. "DCF" / "DFCF" / "DNI" / "DNI (Normalized)" / "P/B" / "PSG" --
    # None when Step 3 selected PASS. Shown on the header pill alongside the
    # verdict so it's never presented as a bare "Undervalued" with no method.
    fair_value_method: str | None = None


class Step1Out(BaseModel):
    ticker: str
    years: list[str]
    revenue: list[float | None]
    # "Revenue" for every company type except Bank, where it's "Net Interest
    # Income" (revenue's own field mixes interest and non-interest income in
    # a way that obscures the core lending-spread trend for banks). Never
    # silently substituted under the old label -- always shown alongside
    # this field.
    revenue_label: str = "Revenue"
    net_income: list[float | None]
    operating_income: list[float | None]
    # None (the whole field) when the ticker is CFO-exempt (bank / property
    # developer / commodity company) — not a list of nulls.
    cfo: list[float | None] | None = None
    # FCF = CFO - CapEx -- exempt under the exact same conditions as CFO
    # (derived from it, so the same "not a reliable trend signal for these
    # business models" reasoning applies). None (the whole field) whenever
    # cfo is None, never scored independently of CFO's exemption.
    fcf: list[float | None] | None = None
    gross_margin: list[float | None]
    net_margin: list[float | None]
    cfo_exempt_reason: str | None = None
    # Manually-flagged only for now; automated one-off detection is out of
    # scope for this phase (per spec).
    net_income_one_off: bool = False
    cfo_one_off: bool = False
    score: int
    verdict: str
    components: dict


class Step2EstimateRow(BaseModel):
    fiscal_year: str
    growth_avg: float
    growth_high: float
    growth_low: float


class Step2Out(BaseModel):
    ticker: str
    # Which FMP metric the projection is based on -- revenue is preferred,
    # EPS is a fallback when revenue estimates are unavailable (see
    # CLAUDE.md's "Scoring rubric deviations").
    basis: str | None = None
    estimates: list[Step2EstimateRow] = []
    base_fiscal_year: str | None = None
    target_fiscal_year: str | None = None
    growth_rate: float | None = None
    # High/low spread as a % of the average estimate for the target year --
    # labeled "analyst estimate range" in the UI, NOT "source consensus":
    # this is multiple analysts on one platform, not multiple platforms.
    estimate_spread: float | None = None
    # Informational only -- how many analysts the target year's spread is
    # built on; doesn't affect the score.
    target_analyst_count: int | None = None
    # Manually-curated free text; not factored into the score (see
    # CLAUDE.md). Null when nothing has been recorded yet.
    growth_catalysts: str | None = None
    score: int
    verdict: str
    components: dict


class Step5RatioResult(BaseModel):
    # None only for interest_coverage_ratio when interest expense is
    # missing/non-positive -- never a fabricated number.
    value: float | None
    # Current Ratio only: the deferred-revenue-adjusted value used for
    # tiering once the raw ratio itself isn't already comfortable. Equals
    # `value` (or omitted) whenever deferred revenue didn't change anything.
    adjusted_value: float | None = None
    label: str
    points: int
    # True when a Borderline breach was excused by its tiebreaker (deferred
    # revenue for Current Ratio, Interest Coverage for the other two).
    saved_by_tiebreaker: bool = False


class Step5Out(BaseModel):
    ticker: str
    # "Standard" / "Bank" / "REIT/Property Developer" -- best-effort
    # sector/industry text match, not a certified determination (see
    # CLAUDE.md's "Scoring rubric deviations").
    company_type: str
    classification_note: str = "Best-effort classification from sector/industry text — not a certified determination."
    ratios: dict[str, Step5RatioResult] = {}
    # Set only when ratios["npl_ratio"] is present -- labels which filing the
    # NPL figure is actually as-of (e.g. "FY2025 annual filing" vs. "Q2
    # 2026"). A fallback to the annual filing (see npl.py) must never be
    # presented as equally current as a ticker where the quarterly figure
    # was available.
    npl_as_of: str | None = None
    # Deferred revenue is now wired into the Current Ratio verdict itself
    # (see ratios["current_ratio"].adjusted_value) -- this raw figure is
    # kept for display/context, not just as an unused note.
    deferred_revenue_current: float | None = None
    # None for Bank (not yet supported) or when required raw data is
    # missing -- never a fabricated number.
    score: int | None = None
    # "Fail" / "Pass" / "Strong Pass" for scored tickers; "Pass with
    # caution" when a Borderline breach was excused by its tiebreaker;
    # "not_supported" for Bank; "insufficient_data" when required figures
    # are missing.
    verdict: str
    hard_fail: bool = False
    # True whenever verdict == "Pass with caution" -- convenience flag so
    # the frontend doesn't need to string-match the verdict.
    pass_with_caution: bool = False
    outlier_warnings: list[OutlierWarning] = []


class Step4Out(BaseModel):
    # years/roe/roic/revenue/accounts_receivable/ccc AND
    # score/verdict/hard_fail/components all now share the same 10yr+TTM
    # window (step4_data.py's ANNUAL_WINDOW), matching Step 1 -- a
    # deliberate deviation beyond the source doc's explicit "5 years" (see
    # CLAUDE.md's Step 4 deviations). There used to be a narrower 5yr+TTM
    # SCORING window decoupled from a wider DISPLAY window; that decoupling
    # has been removed.
    ticker: str
    years: list[str]
    # "Standard" / "Bank" / "Insurance" / "Utility" / "REIT/Property
    # Developer" -- best-effort sector/industry text match, shared with
    # Step 5 (see CLAUDE.md's "Scoring rubric deviations").
    company_type: str
    classification_note: str = "Best-effort classification from sector/industry text — not a certified determination."
    roe: list[float | None]
    # None (the whole field) when ROIC is exempt for this company type
    # (Bank / Insurance / Utility) -- not a list of nulls.
    roic: list[float | None] | None = None
    roic_exempt_reason: str | None = None
    revenue: list[float | None]
    accounts_receivable: list[float | None]
    # None (the whole field) when no physical inventory was detected across
    # the reporting window.
    ccc: list[float | None] | None = None
    ccc_exempt_reason: str | None = None
    # None when required raw data is missing -- never a fabricated number.
    score: int | None = None
    # "Fail" / "Pass" / "Strong Pass" for scored tickers; "insufficient_data"
    # when required figures are missing.
    verdict: str
    hard_fail: bool = False
    components: dict = {}
    # Informational only -- never changes score/verdict (see CLAUDE.md's
    # Step 4 deviations). None unless ROE is "excellent"/"good" while ROIC
    # is "marginal" (a "fail" ROIC already hard-fails on its own).
    roe_roic_divergence_note: str | None = None


class Step3MethodStep(BaseModel):
    """One node of the method-selection decision trail (see scoring/step3.py
    ::select_method) -- surfaced in full so the UI can show *why* a method
    was picked, not just the answer."""

    step: str
    check: str
    # None when the check couldn't run at all (missing data), not the same
    # as a real False.
    passed: bool | None
    detail: str


class Step3CapmComponents(BaseModel):
    risk_free_rate: float
    market_risk_premium: float
    beta: float
    # True when beta < 0.8 -- outside the workbook's own manual reference
    # table range (see step6_intrinsic_value_calculation_prompt.md §5).
    # CAPM is still applied directly, not floored; this is informational.
    beta_outside_reference_range: bool


class Step3Inputs(BaseModel):
    # --- 20yr engine inputs (DCF / DFCF / DNI) ---
    current_value: float | None = None
    current_value_label: str | None = None
    total_debt: float | None = None
    cash_and_st_investments: float | None = None
    # False when only cashAndCashEquivalents was available (no separate
    # short-term-investments figure to add in). True does NOT mean equity
    # securities are excluded -- FMP's standardized schema has no
    # equity-vs-debt split within short-term investments (confirmed against
    # JPM/AAPL/GOOGL/MSFT), so the spec's "include equity holdings?" toggle
    # is approximated as "cash only" vs "cash + all short-term investments"
    # (undifferentiated) rather than a true equity-securities exclusion.
    cash_and_st_investments_includes_short_term_investments: bool = False
    growth_yr_1_5: float | None = None
    growth_yr_6_10: float | None = None
    growth_yr_11_20: float
    # e.g. "Step 2 analyst-estimate CAGR (revenue basis)" -- None means no
    # Step 2 growth rate was available for this ticker.
    growth_yr_1_5_source: str | None = None
    shares_outstanding: float | None = None
    shares_outstanding_source: str | None = None
    discount_rate: float | None = None
    capm: Step3CapmComponents | None = None
    current_fiscal_year: str | None = None
    # Hardcoded 1.0 for now -- this app's screener is S&P 500 (US-listed,
    # USD-denominated) only, so the spec's HK/China cross-currency branch
    # isn't built. Revisit if non-US tickers are ever added.
    fx_rate: float = 1.0
    last_close: float | None = None

    # --- Price-to-Book inputs ---
    book_value_per_share: float | None = None
    historical_pb_ratios: list[float] | None = None
    pb_lookback: str | None = None

    # --- PSG inputs ---
    sales_per_share: float | None = None
    projected_growth_rate: float | None = None
    fair_psg_ratio: float | None = None


class Step3PBBands(BaseModel):
    minus_2sd: float
    minus_1sd: float
    mean: float
    plus_1sd: float
    plus_2sd: float


class Step3Out(BaseModel):
    ticker: str
    # "Standard" / "Bank" / "Insurance" / "Utility" / "REIT/Property
    # Developer" -- best-effort sector/industry text match, shared with
    # Step 4/Step 5 (see CLAUDE.md's "Scoring rubric deviations").
    company_type: str
    classification_note: str = "Best-effort classification from sector/industry text — not a certified determination."
    # DCF | DFCF | DNI | DNI_NORMALIZED | PRICE_TO_BOOK | PSG | PASS
    selected_method: str
    method_reasoning: list[Step3MethodStep] = []
    # Set only when selected_method == "PASS".
    pass_reason: str | None = None
    inputs: Step3Inputs
    # Below: None until the calculation engine runs (Phase 2).
    intrinsic_value_per_share: float | None = None
    pb_bands: Step3PBBands | None = None
    discount_premium_pct: float | None = None
    # "undervalued" / "fair" / "overvalued" -- None until Phase 2.
    verdict: str | None = None


class DiscountRateConfigOut(BaseModel):
    region: str
    risk_free_rate: float
    market_risk_premium: float
    updated_at: datetime


class DiscountRateConfigIn(BaseModel):
    risk_free_rate: float
    market_risk_premium: float


class TickerScoreOut(BaseModel):
    """A pre-computed row for the Screener page (see ticker_score.py) --
    denormalized from the same 5 functions Step 1/2/4/5 and the ticker
    header call, refreshed by the nightly fetch job and the standalone
    recompute_ticker_scores.py script. Every score/verdict is None when
    that step's data wasn't available for this ticker (mirrors each step's
    own None-for-insufficient-data convention)."""

    ticker: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    company_type: str | None = None
    step1_score: int | None = None
    step1_verdict: str | None = None
    step2_score: int | None = None
    step2_verdict: str | None = None
    step4_score: int | None = None
    step4_verdict: str | None = None
    step5_score: int | None = None
    step5_verdict: str | None = None
    overall_score: int | None = None
    overall_verdict: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    beta: float | None = None
    computed_at: datetime


class RecomputeSummary(BaseModel):
    processed: int
    failed: int
    duration_seconds: float
    failures: list[tuple[str, str]] = []


class ScreenerMeta(BaseModel):
    # Total stored S&P 500 constituents -- NOT the same as len(GET
    # /api/screener)'s response, since a ticker with no cached profile at
    # all gets no TickerScore row. The gap between the two is what the
    # Screener page's "X of Y" transparency note is built from.
    total_sp500_constituents: int


class FinancialsLineItem(BaseModel):
    label: str
    values: list[float | None]
    # "money" or "per_share" -- tells the frontend which formatter to use
    # (fmtTableMoney vs fmtNumber), since EPS rows would otherwise be
    # divided by 1e6 like every other row and read as ~0.00.
    unit: str = "money"
    # Bold/subtotal row (e.g. "Total Assets") -- a lightweight rendering
    # hint, not a computed value; the totals themselves come straight from
    # FMP's own reported total fields, never summed client- or server-side.
    emphasis: bool = False


class FinancialsGroup(BaseModel):
    # None renders with no group header -- used by Income Statement, which
    # has no natural sub-grouping the way Balance Sheet/Cash Flow do.
    label: str | None = None
    items: list[FinancialsLineItem]


class FinancialsPeriodOut(BaseModel):
    periods: list[str]
    groups: list[FinancialsGroup]


class FinancialsStatementOut(BaseModel):
    annual: FinancialsPeriodOut
    quarterly: FinancialsPeriodOut


class FinancialsOut(BaseModel):
    ticker: str
    income_statement: FinancialsStatementOut
    balance_sheet: FinancialsStatementOut
    cash_flow: FinancialsStatementOut
