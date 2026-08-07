from datetime import date, datetime
from typing import Literal

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
    # Latest-quarter figure from /stable/enterprise-values (not a live
    # recompute) -- fresher than the endpoint's latest-annual row, see
    # CLAUDE.md's Summary tab expansion notes.
    enterprise_value: float | None = None
    beta: float | None = None
    # Trailing PEG (priceToEarningsGrowthRatioTTM) and forward PEG
    # (forwardPriceToEarningsGrowthRatioTTM) from /stable/ratios-ttm -- shown
    # side by side, matching the precedent already set on the Ratios tab.
    peg_ratio: float | None = None
    forward_peg_ratio: float | None = None
    # dividendYieldTTM from the same /stable/ratios-ttm call as the PEG
    # fields above -- FMP returns it as a fraction (e.g. 0.0032), scaled by
    # *100 here to match every other percent field on this model (see
    # eps_growth_3_5y/perf_* -- the frontend's fmtPct just appends "%" with
    # no scaling of its own).
    dividend_yield: float | None = None
    # Derived via shares.py::compute_shares_outstanding -- the same figure
    # Step 3's valuation math uses, since /stable/profile has no
    # sharesOutstanding field on our FMP plan.
    shares_outstanding: float | None = None
    shares_outstanding_source: str | None = None
    # Recomputed from daily historical price/volume, NOT profile's
    # averageVolume -- confirmed empirically that field is closer to a
    # ~50-63 trading-day average than a 30-day one.
    avg_volume_30d: float | None = None
    avg_dollar_volume_20d: float | None = None
    perf_1m: float | None = None
    perf_6m: float | None = None
    perf_ytd: float | None = None
    perf_1y: float | None = None
    perf_5y: float | None = None
    perf_10y: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    eps_growth_3_5y: float | None = None
    # revenueGrowth/netIncomeGrowth from /stable/financial-growth (latest
    # annual FY, YoY) -- a data domain not otherwise used in this app.
    # Also fractions on the raw FMP payload, *100 scaled here for the same
    # reason as dividend_yield above.
    revenue_growth_yoy: float | None = None
    net_income_growth_yoy: float | None = None
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
    # "auto" / "custom" -- lifted straight from Step3Out.valuation_source
    # (see step3_data.py::get_active_valuation). None only alongside a None
    # fair_value_verdict (Step 3 selected PASS with no active custom
    # valuation to fall back to).
    valuation_source: str | None = None


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
    # None when required raw data is missing -- never a fabricated number
    # (same convention as Step2Out/Step4Out/Step5Out).
    score: int | None = None
    # "Fail" / "Pass" / "Strong Pass" for scored tickers; "insufficient_data"
    # when required figures are missing.
    verdict: str
    components: dict = {}
    # Weight each component contributed to `score` -- WEIGHTS_STANDARD or
    # WEIGHTS_CFO_EXEMPT from scoring/step1.py, keyed the same as `components`.
    weights: dict[str, float]


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
    # None when no usable growth projection exists in either basis -- never
    # a fabricated number (same convention as Step4Out/Step5Out).
    score: int | None = None
    # "Fail" / "Pass" / "Strong Pass" for scored tickers; "insufficient_data"
    # when neither EPS nor Revenue yields a usable CAGR.
    verdict: str
    components: dict = {}
    # Weight each component contributed to `score` -- MAGNITUDE_WEIGHT /
    # AGREEMENT_WEIGHT from scoring/step2.py, keyed the same as `components`.
    weights: dict[str, float]


class BreachContextSignal(BaseModel):
    """One secondary signal evaluated by Step 5's breach-context framework
    (see scoring/step5.py's evaluate_debt_to_ebitda_breach_context /
    evaluate_current_ratio_breach_context) -- surfaced individually so the
    UI can explain exactly why a Borderline breach was (or wasn't)
    downgraded to "marginal", not just the final outcome."""

    key: str
    status: str  # "favorable" | "unfavorable" | "not_computable"
    # Factual value string for favorable/unfavorable (e.g. "4.81x now vs
    # 7.02x 5yr ago"); the manual-check sentence itself, verbatim, when
    # status is "not_computable" -- the backend supplies the full sentence
    # so this never silently omits a signal the UI doesn't have a template
    # for.
    detail: str | None = None
    # False for informational-only signals (cause of debt, undrawn
    # revolving credit, net-vs-gross debt) -- shown to the user but never
    # counted toward the majority-vote gate.
    counts_toward_gate: bool = True


class Step5RatioResult(BaseModel):
    # None only for interest_coverage_ratio when interest expense is
    # missing/non-positive -- never a fabricated number.
    value: float | None
    # Current Ratio only: the deferred-revenue-adjusted value used for
    # tiering once the raw ratio itself isn't already comfortable. Equals
    # `value` (or omitted) whenever deferred revenue didn't change anything.
    adjusted_value: float | None = None
    # Populated only for current_ratio/debt_to_ebitda when that ratio
    # actually reached the Borderline zone and the breach-context framework
    # evaluated it (None for Comfortable/Severe ratios, DSR, and ICR).
    breach_context: list[BreachContextSignal] | None = None
    label: str
    points: int
    # True when a Borderline breach was excused by its tiebreaker (deferred
    # revenue for Current Ratio, Interest Coverage for the other two).
    saved_by_tiebreaker: bool = False
    # Full sentence explaining an unusual result -- populated only for
    # Debt/EBITDA's negative-EBITDA Fail so far (see
    # scoring/step5.py::score_step5_standard). None otherwise.
    note: str | None = None


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
    # Bank only (non-excluded tickers) -- manually entered, no FMP source
    # exists (see CLAUDE.md's Step 5 CET1 deviation note). None when not yet
    # entered.
    cet1_ratio_pct: float | None = None
    cet1_as_of: str | None = None
    # "manual" when a TickerBankCapitalMetrics.npl_ratio_pct override is
    # set, "auto" when Step 5 fell back to the live compute_npl_ratio()
    # result, None when neither is available. Bank only.
    npl_source: str | None = None
    # True only for non-excluded Bank tickers (not IBKR/HOOD, which have no
    # customer deposit-taking business -- see step5_data.py's
    # BANK_CET1_NPL_EXCLUDED_TICKERS) -- tells the frontend whether to
    # render the CET1/NPL input form at all vs. IBKR/HOOD's unchanged
    # static blurb.
    bank_capital_metrics_editable: bool = False
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
    # Weight each ratio contributed to `score` -- WEIGHTS_STANDARD /
    # WEIGHTS_REIT from scoring/step5.py, keyed the same as `ratios`. Empty
    # for Bank (no composite score exists to weight).
    weights: dict[str, float] = {}
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
    # Set only for REIT/Property Developer -- Revenue-vs-AR has no
    # comparable concept for a rental-income business model, so it's
    # excluded from scoring the same way ccc_exempt_reason excludes CCC.
    revenue_vs_ar_exempt_reason: str | None = None
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
    # table range (see valuation.md §5).
    # CAPM is still applied directly, not floored; this is informational.
    beta_outside_reference_range: bool


class Step3CurrentValueCandidates(BaseModel):
    """All four candidate figures the method-selection tree can pick from as
    `current_value`, not just the one matching the auto-selected method --
    Manual Calculation needs the rest so switching its method dropdown to
    something other than what Auto picked still pre-fills a sensible
    starting value."""

    cfo_ttm: float | None = None
    fcf_ttm: float | None = None
    fcf_normalized: float | None = None
    net_income_ttm: float | None = None
    net_income_smoothed: float | None = None


class Step3Inputs(BaseModel):
    # --- 20yr engine inputs (DCF / DFCF / DNI) ---
    current_value: float | None = None
    current_value_label: str | None = None
    current_value_candidates: Step3CurrentValueCandidates = Step3CurrentValueCandidates()
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
    # Computed from historical_pb_ratios/pb_lookback whenever both are
    # available, regardless of the auto-selected method -- lets Manual
    # Calculation pre-fill a real mean/SD P/B pair even when Auto picked a
    # different method for this ticker.
    pb_mean_ratio: float | None = None
    pb_sd_ratio: float | None = None

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
    # Only meaningful when selected_method == "PASS". True when at least one
    # check in method_reasoning has passed=None (couldn't run at all due to
    # missing/too-thin data -- a fetch failure or a genuinely too-thin
    # history) rather than every check genuinely computing a
    # disqualification -- lets the frontend distinguish "insufficient data"
    # from "no method applies" even though both currently share
    # selected_method == "PASS".
    insufficient_data: bool = False
    inputs: Step3Inputs
    # Below: None until the calculation engine runs (Phase 2).
    intrinsic_value_per_share: float | None = None
    pb_bands: Step3PBBands | None = None
    discount_premium_pct: float | None = None
    # "undervalued" / "fair" / "overvalued" -- None until Phase 2.
    verdict: str | None = None
    # "auto" (default) or "custom" -- "custom" only when this ticker has an
    # active TickerCustomValuation row, in which case selected_method/
    # intrinsic_value_per_share/pb_bands/discount_premium_pct/verdict above
    # reflect the saved custom valuation instead of Auto Calculation's own
    # pick (see step3_data.py::get_active_valuation). company_type/
    # method_reasoning/pass_reason/inputs below are ALWAYS Auto's own --
    # never overridden -- since they describe what Auto's method-selection
    # tree did, which stays meaningful context regardless of what's active.
    valuation_source: str = "auto"

    # --- Additive, informational-only fields (never change verdict above) --
    # The framework's own P/B buy signal for Bank/REIT ("price at/below -1SD
    # of historical average P/B") -- set whenever pb_bands/pb_result exist,
    # not gated to company_type, mirroring pb_mean_ratio/pb_sd_ratio's own
    # unconditional computation.
    historical_pb_buy_signal: bool | None = None
    # Fixed sanity-range benchmarks from the framework (Bank 1.2-1.4, REIT
    # <=1.2/up to 1.5 with high DPU growth) -- context only, never used to
    # gate or adjust intrinsic_value_per_share/verdict above. None for
    # company types the framework gives no benchmark for.
    benchmark_pb_low: float | None = None
    benchmark_pb_high: float | None = None
    benchmark_pb_note: str | None = None
    # REIT-only: Dividend/DPU Yield check (>=4%) and a simple growing/
    # declining read on dividendPerShare, both sourced from the same
    # ratios_annual data already fetched for the P/B lookback -- no new FMP
    # call. None for every other company type.
    dividend_yield_pct: float | None = None
    dividend_yield_meets_reit_threshold: bool | None = None
    dpu_growth_note: str | None = None


class Step3ManualParams(BaseModel):
    """The 13 method-specific input fields run_manual_calculation takes,
    factored out of Step3ManualRequest so TickerCustomValuationIn/Out (the
    persistent custom valuation's save/load schema) can reuse the exact
    same shape rather than redeclaring these fields a second time. Every
    field is optional since only the fields relevant to a given `method`
    need be populated; scoring.step3's run_manual_calculation reports which
    ones are missing for the chosen method rather than this schema
    enforcing it up front."""

    # 20yr engine inputs.
    current_value: float | None = None
    growth_yr_1_5: float | None = None
    growth_yr_6_10: float | None = None
    growth_yr_11_20: float | None = None
    discount_rate: float | None = None
    shares_outstanding: float | None = None
    total_debt: float | None = None
    cash_and_st_investments: float | None = None
    # Price-to-Book inputs.
    book_value_per_share: float | None = None
    pb_mean_ratio: float | None = None
    pb_sd_ratio: float | None = None
    # PSG inputs.
    sales_per_share: float | None = None
    projected_growth_rate: float | None = None
    fair_psg_ratio: float | None = None


class Step3ManualRequest(Step3ManualParams):
    """Manual Calculation's what-if request -- see Step3ManualParams for
    the shared parameter fields."""

    method: str  # DCF | DFCF | DNI | DNI_NORMALIZED | PRICE_TO_BOOK | PSG
    # Supplied by the caller (already available from the live Auto
    # Calculation fetch) rather than re-fetched server-side.
    last_close: float | None = None


class Step3ManualOut(BaseModel):
    intrinsic_value_per_share: float | None = None
    pb_bands: Step3PBBands | None = None
    discount_premium_pct: float | None = None
    verdict: str | None = None
    # Set when the chosen method is missing a required input -- e.g.
    # "Missing required inputs for DCF".
    error: str | None = None


class TickerCustomValuationIn(Step3ManualParams):
    """Save/update request for a ticker's persistent custom valuation --
    same parameter shape as Step3ManualRequest, minus `last_close` (always
    live, never saved) plus `method`. See models.py::TickerCustomValuation
    and data/custom_valuation_data.py."""

    method: str  # DCF | DFCF | DNI | DNI_NORMALIZED | PRICE_TO_BOOK | PSG


class TickerCustomValuationOut(Step3ManualParams):
    """Full state of a ticker's custom valuation slot -- whether one is
    saved, its method/parameters (all None when saved=False), whether it's
    currently active, and active_verdict (whichever source -- Auto or this
    custom valuation -- currently applies, via
    step3_data.py::get_active_valuation), so the Custom Valuation panel can
    render its entire state from one GET."""

    ticker: str
    saved: bool = False
    method: str | None = None
    is_active: bool = False
    saved_at: datetime | None = None
    active_verdict: Step3ManualOut


class DiscountRateConfigOut(BaseModel):
    region: str
    risk_free_rate: float
    market_risk_premium: float
    updated_at: datetime


class DiscountRateConfigIn(BaseModel):
    risk_free_rate: float
    market_risk_premium: float


class TickerMoatOut(BaseModel):
    ticker: str
    # None means "not set" -- the default for every ticker until a user
    # explicitly sets one via the Economic Moat tab.
    moat: str | None = None
    updated_at: datetime | None = None


class TickerMoatIn(BaseModel):
    moat: Literal["no_moat", "narrow_moat", "wide_moat"]


class TickerBankCapitalMetricsOut(BaseModel):
    ticker: str
    # None means "not set" -- CET1 has no FMP source at all, so this is the
    # default for every Bank ticker until a user explicitly enters one via
    # the Debt (Step 5) card.
    cet1_ratio_pct: float | None = None
    cet1_as_of: str | None = None
    # None means "no manual override" -- Step 5 defers to the live
    # compute_npl_ratio() result in that case (see step5_data.py).
    npl_ratio_pct: float | None = None
    npl_as_of: str | None = None
    updated_at: datetime | None = None


class TickerBankCapitalMetricsIn(BaseModel):
    # Full-replace PUT, same semantics as TickerMoatIn -- every field is
    # optional (unlike TickerMoatIn's required `moat`) since a user may set
    # only CET1 and leave NPL on auto, or only override NPL.
    cet1_ratio_pct: float | None = None
    cet1_as_of: str | None = None
    npl_ratio_pct: float | None = None
    npl_as_of: str | None = None


class MoatScoreConfigOut(BaseModel):
    wide_moat_score: float
    narrow_moat_score: float
    no_moat_score: float
    updated_at: datetime


class MoatScoreConfigIn(BaseModel):
    wide_moat_score: float
    narrow_moat_score: float
    no_moat_score: float


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
    # None when no moat is set for this ticker.
    moat: str | None = None
    moat_score: float | None = None
    overall_score: int | None = None
    overall_verdict: str | None = None
    market_cap: float | None = None
    pe_ratio: float | None = None
    beta: float | None = None
    # "undervalued" / "fair" / "overvalued" -- same Step 3 verdict as the
    # ticker header's FairValuePill (see models.py::TickerScore).
    valuation_verdict: str | None = None
    # "auto" / "custom" -- see models.py::TickerScore.valuation_source.
    valuation_source: str | None = None
    # Step 2's analyst-estimate CAGR % (see models.py::TickerScore).
    growth_rate: float | None = None
    computed_at: datetime


class RecomputeSummary(BaseModel):
    processed: int
    failed: int
    duration_seconds: float
    failures: list[tuple[str, str]] = []


class SavedScreenerFilterIn(BaseModel):
    universe: str
    sort_field: str
    sort_direction: str
    filters: dict


class SavedScreenerFilterOut(BaseModel):
    id: int
    name: str
    universe: str
    sort_field: str
    sort_direction: str
    filters: dict
    created_at: datetime
    updated_at: datetime


Universe = Literal["sp500", "dow", "all"]


class WatchlistTickerOut(BaseModel):
    ticker: str
    added_at: datetime


class WatchlistOut(BaseModel):
    id: int
    name: str
    sort_field: str
    sort_direction: str
    created_at: datetime
    updated_at: datetime
    tickers: list[WatchlistTickerOut]


class WatchlistIn(BaseModel):
    name: str


class WatchlistUpdateIn(BaseModel):
    # All optional -- PUT /api/watchlists/{id} is a partial update (rename
    # and/or sort preference), not a full-replace.
    name: str | None = None
    sort_field: str | None = None
    sort_direction: str | None = None


class WatchlistTickerIn(BaseModel):
    ticker: str


class WatchlistBulkAddIn(BaseModel):
    tickers: list[str]


class WatchlistBulkAddOut(BaseModel):
    added: int
    already_present: int


class WatchlistRowOut(BaseModel):
    """One Watchlist row: compute_ticker_score's cache-only fields (same set
    as TickerScoreOut, minus company/sector/industry/growth_rate/computed_at
    which the Watchlist table doesn't show) plus Step 1's raw Revenue/Net
    Income/CFO series and the Analyst Ratings consensus banner (also
    cache-only) -- see watchlist_data.py::_compose_row. Every score field is
    None for a ticker that's never been visited/cached (compute_ticker_score
    returns None), rather than erroring the whole row."""

    ticker: str
    company_name: str | None = None
    sector: str | None = None
    # FMP's exchangeShortName (e.g. "NASDAQ", "NYSE") -- used to build the
    # EXCHANGE:SYMBOL pairs the per-watchlist Export button writes out for
    # TradingView's "Upload list" import. None whenever the profile cache
    # entry isn't populated yet (never-visited ticker).
    exchange: str | None = None
    # Latest watchlist_data.LATEST_YEARS_SHOWN (5) periods of Step 1's
    # years/revenue/net_income/cfo, for the table's per-row mini trend bar
    # charts -- same series Step1Out itself exposes, just windowed down.
    # cfo is None (the whole field, not a list of nulls) for a CFO-exempt
    # ticker (Bank/Property Developer/Commodity), same convention as
    # Step1Out.cfo.
    years: list[str] = []
    revenue: list[float | None] = []
    net_income: list[float | None] = []
    cfo: list[float | None] | None = None
    moat: str | None = None
    valuation_verdict: str | None = None
    # "auto" / "custom" -- see models.py::TickerScore.valuation_source.
    valuation_source: str | None = None
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
    # FMP's live consensus label (ConsensusBanner.rating), "N/A" when there's
    # no cached analyst-ratings data for this ticker yet -- never null.
    consensus_rating: str
    added_at: datetime


class ScreenerMeta(BaseModel):
    universe: Universe
    # Total stored constituents for `universe` -- NOT the same as
    # len(GET /api/screener)'s response for that same universe, since a
    # ticker with no cached profile at all gets no TickerScore row. The gap
    # between the two is what the Screener page's "X of Y" transparency
    # note is built from.
    total_constituents: int


class FinancialsLineItem(BaseModel):
    label: str
    values: list[float | None]
    # Tells the frontend which formatter to use, since a bare number reads
    # wrong under the wrong unit (e.g. an EPS row divided by 1e6 like every
    # other "money" row would read as ~0.00). Accepted values: "money"
    # (default, /1e6-scaled), "per_share" (unscaled $, 2dp -- also used by
    # Ratios' Graham Number/Net-Net, which are $-per-share intrinsic-value
    # estimates, not company totals), "shares" (unscaled count, /1e6-scaled
    # like money but the label spells out "(millions)" itself since it isn't
    # USD), and, added for the Ratios tab: "ratio" (plain multiple, e.g.
    # "12.3x"), "percent" (e.g. "24.7%"), "days" (e.g. "63.4 days").
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


class RatiosOut(BaseModel):
    """Raw-metrics display only (no scoring/verdicts) for the Ratios tab --
    unlike FinancialsOut there's no annual/quarterly split, since FMP's
    stable /key-metrics and /ratios endpoints 402 on period=quarter under
    our current plan; this is Annual (10yr) + TTM only, a single flat table
    closer in shape to FinancialsPeriodOut alone than to FinancialsOut."""

    ticker: str
    periods: list[str]
    groups: list[FinancialsGroup]


class SegmentationOut(BaseModel):
    """Revenue-by-business-segment and revenue-by-geography breakdowns for
    the Summary tab's two new charts (see segmentation_data.py). Annual-only
    on our FMP plan -- /revenue-product-segmentation and
    /revenue-geographic-segmentation both 402 on period=quarter, confirmed
    empirically, so there's no TTM column here unlike Ratios/Financials.
    `*_segments`/`*_values` are None/empty when the ticker doesn't disclose
    that breakdown (a clean empty FMP payload, not an error) -- the frontend
    shows a "not disclosed" note rather than a broken chart in that case."""

    ticker: str
    product_years: list[str]
    product_segments: list[str] | None = None
    product_values: dict[str, list[float | None]] = {}
    geographic_years: list[str]
    geographic_segments: list[str] | None = None
    geographic_values: dict[str, list[float | None]] = {}


class RatingBucketCounts(BaseModel):
    """FMP's native 5-bucket analyst rating counts (grades-consensus /
    grades-historical) -- reused as-is by both the current consensus banner
    and each historical Recommendation Details column, rather than
    collapsing to 3 buckets everywhere (the banner's segmented bar collapses
    separately, see ConsensusBanner)."""

    strong_buy: int
    buy: int
    hold: int
    sell: int
    strong_sell: int


class ConsensusBanner(BaseModel):
    # FMP's own live consensus label (grades-consensus.consensus) --
    # verbatim, not derived from our own weighted-score banding (see
    # RecommendationDetailsColumn for why historical columns can't do the
    # same).
    rating: str
    analyst_count: int
    # 3-bucket collapse of RatingBucketCounts for the segmented bar:
    # buy = strong_buy + buy, sell = sell + strong_sell.
    buy_count: int
    hold_count: int
    sell_count: int


class PriceTargetSummary(BaseModel):
    current_price: float | None = None
    target_consensus: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    target_median: float | None = None
    # % upside/downside of target_consensus vs. current_price. None if
    # either input is missing.
    upside_pct: float | None = None


class RatingHistoryPoint(BaseModel):
    date: str
    buy_pct: float
    hold_pct: float
    sell_pct: float
    # Weighted score (5=Strong Buy ... 1=Strong Sell) averaged across all
    # analysts in that month's grades-historical snapshot -- see
    # analyst_ratings_data.py's _weighted_score.
    avg_rating: float
    # None until monthly_price_target_snapshot.py has captured a snapshot
    # for/near this month -- FMP has no historical price-target series of
    # its own, so this line starts empty and fills in going forward.
    avg_price_target: float | None = None


class RecommendationDetailsColumn(BaseModel):
    # "Current" / "2M Ago" / "6M Ago" / "1Y Ago".
    label: str
    buy: int
    outperform: int
    hold: int
    underperform: int
    sell: int
    # Weighted score, same formula as RatingHistoryPoint.avg_rating.
    mean: float | None = None
    # "Current" uses FMP's own live consensus text (see ConsensusBanner);
    # the three historical columns have no FMP-provided consensus label, so
    # this is our own weighted-score banding onto this table's own row
    # labels (Buy/Outperform/Hold/Underperform/Sell) -- see
    # analyst_ratings_data.py's _band_consensus. This is a deliberate
    # methodology difference between the Current column and the other
    # three, not an inconsistency to fix.
    consensus: str | None = None
    # None where no PriceTargetSnapshot row falls within tolerance of this
    # column's target date (see analyst_ratings_data.py's
    # _nearest_snapshot) -- most commonly all three historical columns,
    # until the monthly cron has enough history.
    target: float | None = None


class AnalystRatingsOut(BaseModel):
    ticker: str
    banner: ConsensusBanner
    price_target: PriceTargetSummary
    history: list[RatingHistoryPoint]
    recommendation_details: list[RecommendationDetailsColumn]


class NewsArticle(BaseModel):
    title: str
    publisher: str
    site: str
    snippet: str
    image: str | None = None
    url: str
    # FMP's raw "YYYY-MM-DD HH:MM:SS" string, passed through as-is -- no
    # timezone is documented, so no UTC/local conversion is attempted here.
    published_at: str


class NewsOut(BaseModel):
    ticker: str
    articles: list[NewsArticle]


class NewsSentimentArticle(BaseModel):
    title: str
    url: str
    source: str
    # ISO 8601, converted from Alpha Vantage's raw "YYYYMMDDTHHMMSS" string
    # -- unlike NewsArticle.published_at above, AV's format is fixed and
    # documented, so it's normalized here rather than passed through raw.
    published_at: str
    summary: str
    overall_sentiment_score: float
    overall_sentiment_label: str
    # The entry from this article's ticker_sentiment[] matching the
    # requested ticker specifically -- not the article's overall
    # sentiment, which may be dominated by a different company entirely.
    ticker_relevance_score: float
    ticker_sentiment_score: float
    ticker_sentiment_label: str  # "Bearish" | "Somewhat-Bearish" | "Neutral" | "Somewhat-Bullish" | "Bullish"


class SentimentDistribution(BaseModel):
    """Counts of ticker_sentiment_label across the returned article batch
    -- ticker-specific, not overall_sentiment_label, matching the same
    per-ticker framing as NewsSentimentArticle above."""

    bearish: int
    somewhat_bearish: int
    neutral: int
    somewhat_bullish: int
    bullish: int


class NewsSentimentOut(BaseModel):
    ticker: str
    articles: list[NewsSentimentArticle]
    distribution: SentimentDistribution
