from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


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


class TickerSearchResult(BaseModel):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    # True only for a ticker the app already KNOWS is an ETF/fund (cached profile or TickerScore):
    # FMP's search endpoints carry no security-type field and a per-result /profile call would
    # both cost FMP calls and add every searched ticker to the tracked universe. An ETF never
    # opened or watchlisted before is therefore unlabelled until its page is first viewed.
    is_etf: bool = False


class TickerSummaryOut(BaseModel):
    company_name: str | None = None
    ticker: str
    exchange: str | None = None
    # FMP profile's `isEtf`/`isFund` -- the same flag classify_company_type's
    # `is_fund` reads. Lifted here so compute_ticker_score can denormalize it
    # onto TickerScore.is_etf without a second profile read.
    is_etf: bool = False
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
    # CLAUDE.md's Summary tab expansion notes. Denominated in the REPORTING
    # currency (reported_currency below), not quote_currency like market_cap
    # above -- the frontend formats it accordingly (lib/metrics/config.ts).
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
    # ticker's own 5Y return minus SPY's -- None only for SPY's own page
    # (self-comparison isn't meaningful) or when this ticker's own "5Y"
    # figure couldn't be fetched at all (perf_5y_vs_spy_status == "no_data"
    # in that case). See ticker_summary.py::_resolve_perf_vs_spy.
    perf_5y_vs_spy_pct: float | None = None
    # "outperform" / "underperform" / "match" / "no_data" / None (SPY's own page).
    perf_5y_vs_spy_status: str | None = None
    # True when FMP's "5Y" figure is actually a shorter-than-5-year
    # return-since-listing silently clamped to the 5Y slot (confirmed live:
    # a recent IPO's 3Y/5Y/10Y/max all report the identical value) -- still
    # feeds a real perf_5y_vs_spy_pct/status above, just flagged so the UI
    # can attach a caveat rather than presenting it as a true 5yr comparison.
    perf_5y_insufficient_history: bool = False
    week52_high: float | None = None
    week52_low: float | None = None
    eps_growth_3_5y: float | None = None
    # revenueGrowth/netIncomeGrowth from /stable/financial-growth (latest
    # annual FY, YoY) -- a data domain not otherwise used in this app.
    # Also fractions on the raw FMP payload, *100 scaled here for the same
    # reason as dividend_yield above.
    revenue_growth_yoy: float | None = None
    net_income_growth_yoy: float | None = None
    # Trailing P/E: nightly last close (quote price if none) / FMP TTM EPS; FMP's own TTM P/E for an
    # ADR (reported != quote currency); None for non-positive/missing EPS (helpers/trailing_pe.py).
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
    # Lifted from Step3Out.inputs.reported_currency -- None when Step 3's
    # reported_currency == quote_currency (no conversion happened).
    # fair_value_price above is in quote_currency either way (see
    # step3_data.py's FX generalization) -- this is display-only, driving
    # the header pill's compact currency badge (see FairValuePill.tsx) so a
    # converted figure is never shown as if it were a native, un-converted
    # number with no indication otherwise.
    fair_value_reported_currency: str | None = None
    # The ticker's actual trading currency (FMP /profile's `currency`
    # field, e.g. "USD"), defaulting to "USD" when /profile has none.
    # price/market_cap/fair_value_price above, and every other quote-domain
    # figure on this model, are denominated in this currency -- drives the
    # header/Screener/Watchlist currency-aware formatters (see
    # frontend/lib/format.ts).
    quote_currency: str = "USD"
    # The ticker's financial-statement reporting currency (FMP
    # `reportedCurrency`, e.g. "CNY"), None when unavailable. Distinct from
    # fair_value_reported_currency above (which specifically reflects
    # whether Step 3's Fair Value figure needed conversion) -- this field
    # describes revenue/net income/total_debt/ebitda_ttm/etc. on THIS
    # model, which stay raw/un-converted (same convention as
    # FinancialsOut.reported_currency).
    reported_currency: str | None = None
    # Which of the three tracked named indices ("sp500"/"nasdaq"/"dow") this
    # ticker is currently a constituent of, in that fixed display order --
    # see data/ticker_summary.py::INDEX_MEMBERSHIP_ORDER. Empty for a ticker
    # in none of them (drives the ticker-header pill, hidden when empty).
    index_memberships: list[str] = []


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
    # Real values always populate here, even for a CFO-exempt ticker (bank /
    # property developer / commodity company) -- display is decoupled from
    # scoring (2026-09-11). The score itself still excludes cfo entirely for
    # an exempt ticker (see scoring/step1.py::score_step1's own `cfo_exempt`
    # param) regardless of what's returned in this field; check
    # `cfo_exempt_reason` (below), not `cfo is None`, to tell whether CFO
    # was actually scored.
    cfo: list[float | None] | None = None
    # FCF = CFO - CapEx -- same display/scoring decoupling as CFO above:
    # real values always populate here, even when exempt from scoring.
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
    # Same convention as Step5Out/TickerSummaryOut below -- informational
    # only, never changes revenue/net_income/cfo/fcf or the score/verdict
    # above (see ttm.py::sum_last_four_quarters). Previously computed but
    # silently discarded here (2026-08-16 fix) -- Step 1 is exactly where a
    # flagged TTM figure feeds a real score, so it belongs in the UI, not
    # just Step 5's.
    outlier_warnings: list[OutlierWarning] = []


class Step2EstimateRow(BaseModel):
    fiscal_year: str
    growth_avg: float
    growth_high: float
    growth_low: float


class Step2Out(BaseModel):
    ticker: str
    # Which FMP metric the projection is based on -- EPS is preferred, Revenue
    # is a fallback when EPS estimates don't yield a usable CAGR (see
    # CLAUDE.md's "Scoring rubric deviations"). REITs are the one exception:
    # they're routed straight to Revenue, skipping the EPS attempt entirely
    # (see growth_basis_note below).
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
    # REIT-only: explains why Revenue (rental income) is used as the basis
    # instead of DPU/dividend growth -- FMP has no forward-looking DPU
    # estimate field at all (see CLAUDE.md). Informational only, never
    # affects score/verdict. None for every other company type.
    growth_basis_note: str | None = None
    # REIT-only: historical (trailing) DPU/share trend, reusing
    # scoring/step3.py's dpu_growth_note verbatim -- purely informational,
    # never scored (a trailing figure has no forward-looking analyst
    # agreement spread the way the scored basis does). None for every other
    # company type.
    dpu_growth_note: str | None = None
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
    # True only when this ticker actually reached score_step5_standard (the
    # Current Ratio / Debt-to-EBITDA / Debt Servicing Ratio path) and scored
    # -- i.e. Standard or Utility company_type with none of the 3 ratios'
    # required inputs missing. False for every other path: Bank (CET1/NPL
    # blend, not these ratios, whether or not CET1 has been entered),
    # Insurance (not_supported, no ratios at all), REIT/Property Developer
    # (Gearing ratio, a different metric entirely), and Standard/Utility's
    # own "insufficient_data" early return. Lets other consumers (e.g. the
    # Financials tab's Historical Trends debt chart) gate on "was debt
    # actually evaluated via the 3 ratios" without re-deriving Step 5's own
    # classification/data-availability branching.
    debt_ratios_evaluated: bool = False
    # 10yr annual + TTM (matching Step1Out/Step4Out's own years+TTM
    # convention), gross Debt/EBITDA -- (shortTermDebt + longTermDebt) /
    # EBITDA, the exact figure score_step5_standard scores, not FMP's own
    # `netDebtToEBITDA` (RatiosOut's "Net Debt/EBITDA" field). Those two
    # are NOT the same ratio: FMP's field nets against cash *and* uses
    # FMP's own broader `totalDebt` (which folds in capital lease
    # obligations Step 5 deliberately excludes -- see helpers/debt_metrics.py)
    # as its debt base. Confirmed via real cached data (2026-08-13
    # investigation) that this compounds into a material, not just
    # cosmetic, difference -- SBUX reads 2.26x gross (comfortably under the
    # 3.0x hard-fail line) vs 3.23x under FMP's net figure (inside the
    # Borderline zone) -- so this series is deliberately its own field
    # rather than reusing RatiosOut's. Only populated when
    # `debt_ratios_evaluated` is True (Standard path); `None`/empty
    # otherwise, same gating as the Total Debt chart card.
    debt_to_ebitda_years: list[str] = []
    debt_to_ebitda_series: list[float | None] = []


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
    # Additive display-only fields for the Financials tab's Historical
    # Trends debt bar chart -- not consumed by Step 4's own scoring (which
    # has no debt concept) or by Step 5/Valuation's separate `total_debt`
    # input (backend/helpers/debt_metrics.py), which stays untouched.
    long_term_debt: list[float | None] = []
    short_term_debt: list[float | None] = []
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
    # Weight each component contributed to `score` -- BASE_WEIGHTS from
    # scoring/step4.py, proportionally renormalized across whichever metrics
    # are applicable for this company type, keyed the same as `components`
    # (note: scoring/step4.py's own internal dict uses "ar", not
    # "revenue_vs_ar", for this key -- step4_data.py remaps it before
    # constructing this field, so API/UI consumers never see the mismatch).
    # {} when score is None (insufficient_data) -- never a fabricated weight
    # for a component that was never actually scored.
    weights: dict[str, float] = {}
    # Informational only -- never changes score/verdict (see CLAUDE.md's
    # Step 4 deviations). None unless ROE is "excellent"/"good" while ROIC
    # is "marginal" (a "fail" ROIC already hard-fails on its own).
    roe_roic_divergence_note: str | None = None
    # Same convention as Step5Out/TickerSummaryOut/Step1Out -- informational
    # only, never changes revenue/net_income/ocf or the score/verdict above
    # (see ttm.py::sum_last_four_quarters). Previously computed but silently
    # discarded here (2026-08-16 fix).
    outlier_warnings: list[OutlierWarning] = []


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
    """Every candidate figure a `current_value`-based method could use, not
    just the one matching the auto-selected method -- Manual Calculation
    needs the rest so switching its method dropdown to something other than
    what Auto picked still pre-fills a sensible starting value.

    cfo_smoothed/fcf_smoothed exist for CF_NORMALIZED/FCF_NORMALIZED, which
    are Manual Calculation/Custom Valuation-only method choices -- Auto
    Calculation's own select_method tree never picks either (see CLAUDE.md's
    Item 3 note), so these two fields are always pre-fill-only, never the
    source of selected_method/current_value on an "auto" Step3Out."""

    cfo_ttm: float | None = None
    fcf_ttm: float | None = None
    fcf_normalized: float | None = None
    net_income_ttm: float | None = None
    net_income_smoothed: float | None = None
    cfo_smoothed: float | None = None
    fcf_smoothed: float | None = None


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
    # quote_currency: the ticker's FMP `/profile` `currency` field (e.g.
    # "USD") -- the currency last_close/intrinsic_value_per_share are
    # actually denominated in. Defaults to "USD" when /profile has no
    # currency field, matching every ticker's behavior before this field
    # existed. This is the conversion TARGET fx_rate below converts
    # reported_currency into -- not always USD (see reported_currency's own
    # comment). Display-only, same as reported_currency.
    quote_currency: str = "USD"
    # reported_currency: the ticker's FMP `reportedCurrency` (e.g. "TWD"),
    # None for a reporter whose statements are already in quote_currency --
    # display-only, so the Valuation tab can caption "Converted from TWD @
    # ...". Every monetary field elsewhere in this schema (current_value,
    # total_debt, cash_and_st_investments, book_value_per_share,
    # sales_per_share, and current_value_candidates' own fields) is ALREADY
    # converted to quote_currency by the time it lands here -- step3_data.py
    # converts each raw figure once, upfront, right after it's pulled from
    # FMP, rather than deferring conversion to a later multiply -- so Manual
    # Calculation's pre-fill and a saved Custom Valuation's parameters are
    # always plain quote_currency, never a local-currency figure the user
    # would have to know to convert themselves. fx_rate below is therefore
    # pure display metadata past this point, not something downstream math
    # still needs to apply. last_close needs no conversion at all -- FMP's
    # /quote price is already in quote_currency by construction.
    reported_currency: str | None = None
    # The resolved reported_currency -> quote_currency spot rate actually
    # used for the conversion above (e.g. 0.0311 for TWD -> USD, or a cross
    # rate between two non-USD currencies),
    # None when no real conversion was needed (reported_currency ==
    # quote_currency) or when a non-matching conversion couldn't be resolved
    # at all (Valuation reads as insufficient_data instead -- see
    # step3_data.py's fx-resolution short-circuit). 1.0 when no conversion
    # was needed.
    fx_rate: float | None = 1.0
    # fetched_at of the cached forex_rate row(s) this fx_rate came from --
    # None when reported_currency == quote_currency (no forex fetch ever
    # attempted).
    fx_rate_as_of: datetime | None = None
    last_close: float | None = None

    # --- Price-to-Book inputs (tangible/"custom" basis -- manual-only as of
    # 2026-09-14, see book_value_per_share_standard below for the
    # auto-selected default) ---
    book_value_per_share: float | None = None
    historical_pb_ratios: list[float] | None = None
    pb_lookback: str | None = None
    # Computed from historical_pb_ratios/pb_lookback whenever both are
    # available, regardless of the auto-selected method -- lets Manual
    # Calculation pre-fill a real mean/SD P/B pair even when Auto picked a
    # different method for this ticker.
    pb_mean_ratio: float | None = None
    pb_sd_ratio: float | None = None

    # --- Price-to-Book inputs (standard basis: totalAssets -
    # totalLiabilities, no intangibles/goodwill subtraction) -- the
    # 2026-09-14 auto-selected default for Bank/REIT/Property Developer.
    # Exactly parallel to the 5 tangible fields above; computed
    # unconditionally, same reasoning. ---
    book_value_per_share_standard: float | None = None
    historical_pb_ratios_standard: list[float] | None = None
    pb_lookback_standard: str | None = None
    pb_mean_ratio_standard: float | None = None
    pb_sd_ratio_standard: float | None = None

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
    # DCF | DFCF | DNI | DNI_NORMALIZED | PRICE_TO_BOOK_STANDARD | PSG |
    # PASS -- plus CF_NORMALIZED | FCF_NORMALIZED | PRICE_TO_BOOK, but only
    # when valuation_source == "custom": select_method's own tree never
    # produces any of these three (Manual Calculation/Custom Valuation-only
    # method choices; PRICE_TO_BOOK was demoted from auto-selected to
    # manual-only 2026-09-14 when PRICE_TO_BOOK_STANDARD became the new
    # Bank/REIT/Property Developer default -- see CLAUDE.md's
    # Item 3 note), so an "auto" Step3Out can never show one here.
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
    # Standard-company-only: a purely informational liquidation-value
    # reference (spec's Method B) shown only when selected_method == "PASS"
    # and TTM Net Income is genuinely negative -- see
    # scoring.step3.loss_making_pb_reference_note. Never a scored method;
    # select_method's own decision_trail/pass_reason above are unaffected.
    loss_making_pb_note: str | None = None
    # Same convention as Step5Out/TickerSummaryOut/Step1Out/Step4Out --
    # informational only, never changes revenue_ttm/net_income_ttm/cfo_ttm/
    # fcf_ttm or intrinsic_value_per_share/verdict above (see
    # ttm.py::sum_last_four_quarters). Previously computed but silently
    # discarded here (2026-08-16 fix) -- Valuation is exactly where a
    # flagged TTM figure feeds a real fair-value number, so it belongs in
    # the UI, not just Step 5's.
    outlier_warnings: list[OutlierWarning] = []


class Step3ManualParams(BaseModel):
    """The 16 method-specific input fields run_manual_calculation takes,
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
    # Price-to-Book inputs (tangible/"custom" basis).
    book_value_per_share: float | None = None
    pb_mean_ratio: float | None = None
    pb_sd_ratio: float | None = None
    # Price-to-Book inputs (standard basis, 2026-09-14).
    book_value_per_share_standard: float | None = None
    pb_mean_ratio_standard: float | None = None
    pb_sd_ratio_standard: float | None = None
    # PSG inputs.
    sales_per_share: float | None = None
    projected_growth_rate: float | None = None
    fair_psg_ratio: float | None = None


class Step3ManualRequest(Step3ManualParams):
    """Manual Calculation's what-if request -- see Step3ManualParams for
    the shared parameter fields."""

    method: str  # DCF | DFCF | DNI | DNI_NORMALIZED | CF_NORMALIZED | FCF_NORMALIZED | PRICE_TO_BOOK | PRICE_TO_BOOK_STANDARD | PSG
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

    method: str  # DCF | DFCF | DNI | DNI_NORMALIZED | CF_NORMALIZED | FCF_NORMALIZED | PRICE_TO_BOOK | PRICE_TO_BOOK_STANDARD | PSG


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


class DataGroupVariantOut(BaseModel):
    """A request variant FMP refused with a canary-confirmed 402 (core/data_groups.py "Request variants"): the
    group stays live and only this way of asking is unavailable."""

    key: str  # `/income-statement?limit=12&period=quarter`
    label: str  # "Quarterly income statement (limit 12)"
    restricted_since: datetime
    last_error: str | None = None
    last_probe_at: datetime | None = None


class DataGroupOut(BaseModel):
    key: str
    label: str
    # False for a group seeded for a later phase, before anything reads it
    # yet -- still shown in Settings regardless. No group is currently in
    # that state (extended_hours, the last one, was removed 2026-09-27 --
    # it never got an endpoint, client method, or call site).
    wired: bool
    enabled: bool  # the user's own toggle
    # Chip: live | cached_only (master off or user off) | not_on_plan |
    # restricted (FMP 402, canary-confirmed) | failing (still live, calls erroring)
    state: Literal["live", "cached_only", "not_on_plan", "restricted", "failing"]
    reason: Literal["live", "master_off", "user_off", "above_plan", "restricted"]
    required_tier: str
    restricted_since: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    feeds: list[str]
    # False when the toggle can't take effect right now (master off / not on plan)
    can_toggle: bool
    # Request variants the plan refuses while the group itself stays live.
    unavailable_variants: list[DataGroupVariantOut] = []


class DataGroupsOut(BaseModel):
    master_on: bool
    fmp_plan: str
    tiers: list[str]
    # Global key problem (HTTP 401/403): no group is blamed.
    key_problem_at: datetime | None = None
    key_problem_detail: str | None = None
    groups: list[DataGroupOut]


class DataGroupUpdateIn(BaseModel):
    enabled: bool | None = None
    required_tier: str | None = None


class DataGroupMasterIn(BaseModel):
    master_on: bool


class DataGroupPlanIn(BaseModel):
    fmp_plan: str


class CronRunOut(BaseModel):
    """Mirrors CronRunLog. `status` here is the raw per-run value
    ("running"/"success"/"failure"/"skipped") -- see CronJobHealthOut.health_status
    for the computed ok/overdue/failed/unknown/skipped state a job as a whole is in."""

    job_name: str
    started_at: datetime
    finished_at: datetime | None = None
    status: str
    error_summary: str | None = None


class CronJobHealthOut(BaseModel):
    # Named health_status, not status, to avoid colliding with
    # CronRunOut.status's different vocabulary (running/success/failure vs.
    # this field's ok/overdue/failed/unknown/skipped).
    job_name: str
    health_status: Literal["ok", "overdue", "failed", "unknown", "skipped"]
    message: str | None = None
    last_run: CronRunOut | None = None
    last_success_at: datetime | None = None
    # Set only when health_status == "skipped": when the current streak of
    # skipped runs began (a long-off group must stay visible).
    skipped_since: datetime | None = None
    # Static display metadata from core/cron_health.py::JOB_METADATA --
    # sourced from crontab.txt, not derived from any live state. Added for
    # the Settings "Status" section's Scheduled Jobs table (job/
    # description/frequency+time columns), which has nothing else to read
    # this from -- crontab.txt itself isn't queryable at runtime.
    description: str
    cadence_group: Literal["daily", "weekly", "monthly"]
    time_label: str
    sort_minutes: int


class CronHealthOut(BaseModel):
    # Unlike the data-group config, jobs changes live every night with no backend
    # restart -- the frontend hook (useCronHealth) polls it for that reason.
    # `enabled` mirrors the cron_health_enabled setting -- False (with jobs always [])
    # when Settings.cron_health_enabled is False, a distinct, explicit
    # "not checking" state that must never be conflated with "checked and
    # everything's ok" (enabled=True, every job's health_status == "ok").
    enabled: bool
    jobs: list[CronJobHealthOut]


class DataSourceStatusOut(BaseModel):
    """One data source's health, for the Settings "Status" section's Data
    Sources cards -- computed purely from an enabled/kill-switch flag (FMP's
    master switch) plus
    DataSourceHealth.last_success_at, NEVER a live reachability ping (see
    core/data_source_status.py)."""

    source: Literal["fmp"]
    enabled: bool
    status: Literal["healthy", "disabled_or_failing", "stale"]
    last_success_at: datetime | None = None


class DataSourceHealthOut(BaseModel):
    sources: list[DataSourceStatusOut]


class DiscountRateConfigOut(BaseModel):
    region: str
    risk_free_rate: float
    market_risk_premium: float
    updated_at: datetime


class DiscountRateConfigIn(BaseModel):
    # Required (no default) -- every PUT must say which region's row it's
    # updating now that this isn't US-only. The single-region GET/PUT below
    # still default region to US_REGION at the query-param level for the
    # common case; this body field is what the update itself actually acts on.
    region: str
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


class SpeculativeGrowthOut(BaseModel):
    """New, independent, read-only classification layered on top of the
    existing 5-step framework -- never derived from or feeding back into
    Step1-5/Overall Assessment. See CLAUDE.md's Speculative Growth
    investigation/design notes and scoring/speculative_growth.py. Live
    per-request read (like Step2Out/TickerMoatOut), not a stored/cached row
    -- no computed_at field."""

    ticker: str
    # True only when company_type == "Standard" AND moat is Narrow/Wide AND
    # Step2's forward growth rate clears the gate -- see
    # scoring/speculative_growth.py::evaluate_speculative_growth. Everything
    # below this is informational context, never a gate.
    qualifies: bool
    company_type: str
    # Set only when the ticker is structurally out of scope (non-Standard
    # company type) -- None for an in-scope ticker that simply didn't clear
    # the moat/growth gate on the merits.
    not_applicable_reason: str | None = None
    moat: str | None = None
    # Step2's forward EPS/Revenue CAGR -- the growth *gate* input. basis
    # mirrors Step2Out.basis ("eps"/"revenue").
    growth_rate_pct: float | None = None
    growth_basis: str | None = None
    # TTM-vs-last-full-FY revenue growth -- informational secondary growth
    # signal, never a gate. See TRAILING_GROWTH_INFORMATIONAL_PCT.
    trailing_revenue_growth_pct: float | None = None
    gross_margin_ttm_pct: float | None = None
    net_income_ttm: float | None = None
    cfo_ttm: float | None = None
    # "turning_positive" / "improving" / "worsening" / "mixed" / None -- see
    # scoring/speculative_growth.py::cfo_recent_direction.
    cfo_recent_direction: str | None = None
    cash_and_st_investments: float | None = None
    # Years of cash at the current TTM CFO burn rate -- display only, no
    # cutoff. None whenever the company isn't burning cash (cfo_ttm >= 0).
    cash_runway_years: float | None = None
    price_to_sales_ttm: float | None = None
    # Price/Sales ÷ trailing_revenue_growth_pct -- informational, PSG_REASONABLE_MAX
    # (<=1) is a reference line shown in the UI, not a gate.
    psg_ratio: float | None = None
    # True when current revenue is well below the ticker's own recent peak
    # AND it clears the growth gate mainly via forward CAGR rather than real
    # trailing momentum -- informational only, never a gate. See
    # scoring/speculative_growth.py::is_potential_fake_growth. Defaults False
    # for the non-Standard/CFO-exempt early-return branches, same convention
    # as every other informational field defaulting to its "nothing to flag"
    # value there.
    potential_fake_growth: bool = False


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


class ReitDividendYieldConfigOut(BaseModel):
    threshold_pct: float
    updated_at: datetime


class ReitDividendYieldConfigIn(BaseModel):
    threshold_pct: float


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
    # See models.py::TickerScore.is_etf.
    is_etf: bool | None = None
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
    # See models.py::TickerScore.last_price -- same rollout-gap convention,
    # None for a row computed before this field existed.
    last_price: float | None = None
    # See models.py::TickerScore.quote_currency -- None (treat as "USD")
    # for a row computed before this field existed.
    quote_currency: str | None = None
    # See models.py::TickerScore.reported_currency.
    reported_currency: str | None = None
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
    # See models.py::TickerScore.perf_5y_vs_spy_pct/_status.
    perf_5y_vs_spy_pct: float | None = None
    perf_5y_vs_spy_status: str | None = None
    # See models.py::TickerScore.speculative_growth_qualifies.
    speculative_growth_qualifies: bool | None = None
    # See models.py::TickerScore.weinstein_stage/_since_date/_since_is_lower_bound/_ma_slope_pct/_vs_ma_pct.
    weinstein_stage: str | None = None
    weinstein_stage_since_date: date | None = None
    weinstein_stage_since_is_lower_bound: bool | None = None
    weinstein_ma_slope_pct: float | None = None
    weinstein_vs_ma_pct: float | None = None
    # See models.py::TickerScore.weinstein_pending_direction.
    weinstein_pending_direction: str | None = None
    # See models.py::TickerScore.bb_rsi_entry_signal. None for the
    # overwhelming majority of tickers -- this signal only ever exists for
    # members of a watchlist named E<number> or ETF.
    bb_rsi_entry_signal: bool | None = None
    # See models.py::TickerScore.warren_active_signal_kind/_last_buy_fired_at.
    # Same monitored-watchlist-only scoping as bb_rsi_entry_signal.
    warren_active_signal_kind: str | None = None
    warren_last_buy_fired_at: datetime | None = None


class RecomputeSummary(BaseModel):
    processed: int
    failed: int
    duration_seconds: float
    failures: list[tuple[str, str]] = []


SavedFilterKind = Literal["stock", "etf"]


class SavedScreenerFilterIn(BaseModel):
    universe: str
    sort_field: str
    sort_direction: str
    filters: dict
    # Which watchlist (if any) was selected as the Screener's base universe
    # when this view was saved -- see SavedScreenerFilter.watchlist_id.
    watchlist_id: int | None = None


class SavedScreenerFilterOut(BaseModel):
    id: int
    name: str
    kind: SavedFilterKind = "stock"
    universe: str
    sort_field: str
    sort_direction: str
    filters: dict
    watchlist_id: int | None = None
    created_at: datetime
    updated_at: datetime


Universe = Literal["sp500", "dow", "nasdaq", "all"]

MomentumPeriod = Literal["current", "previous"]


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
    # data.watchlists.is_monitored_watchlist_name(name) -- the nightly technical jobs read this list.
    # Computed here so the frontend never has to re-implement the naming rule.
    monitored: bool = False


# Shared by create and rename -- strips surrounding whitespace before
# length-checking, so a whitespace-only name (e.g. "   ") is rejected by
# min_length=1 the same as a literal empty string, not silently accepted.
WatchlistName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class WatchlistIn(BaseModel):
    name: WatchlistName


class WatchlistUpdateIn(BaseModel):
    # All optional -- PUT /api/watchlists/{id} is a partial update (rename
    # and/or sort preference), not a full-replace.
    name: WatchlistName | None = None
    sort_field: str | None = None
    sort_direction: str | None = None


class WeinsteinParamsOut(BaseModel):
    ma_length: int
    ma_type: Literal["SMA", "EMA"]
    within_range_pct: float
    slope_lookback: int
    breakout_volume_mult: float
    volume_avg_length: int
    rs_benchmark: str
    rs_smoothing_length: int


class WeinsteinPendingEtaScenarioOut(BaseModel):
    """One projected-confirmation scenario (flat / trend_5 / trend_13) --
    see analysis/trend_structure/weinstein_pending.py::
    WeinsteinPendingEtaScenario for the full mechanism.

    horizon_exceeded=True means this scenario's assumption never lets the
    slope and band conditions coincide within the 2-year projection
    window (weeks_away/projected_date are then null). This is NOT specific
    to the flat scenario -- ANY scenario with a nonzero-but-constant
    growth rate can hit this once real history has fully rolled out of
    the 30-week lookback (see docs/
    weinstein_pending_confirmation_investigation_2026-09-22.md's round-2
    validation, which found this on trend_5/trend_13 scenarios too, not
    just flat)."""

    weeks_away: int | None = None
    projected_date: date | None = None
    band_lapsed_before_confirmation: bool = False
    growth_rate_pct: float
    horizon_exceeded: bool


class WeinsteinPendingOut(BaseModel):
    """Weinstein Stage Analysis: "pending confirmation" + ETA -- present
    only when the ticker currently has one of the two conditions (slope,
    band) for a Stage 2/Stage 4 transition met and the other still open.
    See analysis/trend_structure/weinstein_pending.py's own module
    docstring for the full design. Nested under TrendAnalysisOut.pending
    (null when not currently pending) rather than flattened onto
    TrendAnalysisOut directly, so a non-pending ticker's payload is
    unchanged."""

    direction: Literal["advance", "decline"]
    since_date: date | None = None
    since_is_lower_bound: bool = False
    band_cushion_pct: float | None = None
    typical_weekly_move_pct: float | None = None
    # Keyed by scenario name ("flat", "trend_5", "trend_13").
    eta: dict[str, WeinsteinPendingEtaScenarioOut]


class TrendAnalysisOut(BaseModel):
    """Latest Weinstein stage analysis for one ticker -- see
    models.py::TrendAnalysis for the persisted shape this mirrors. The
    "trend" name is historical: the swing/BOS trend-structure fields this
    once carried were removed, Weinstein is all that remains. None (the
    whole object, via the endpoint returning `| None`) for a ticker with no
    computed row yet, rather than a fabricated all-null result --
    distinguishes "not computed yet" from "computed as neutral." """

    ticker: str
    computed_at: datetime
    # Weinstein Stage Analysis, computed on weekly bars, see
    # models.py::TrendAnalysis's own comment for field
    # semantics (weinstein_stage_changed vs. weinstein_breakout_confirmed
    # in particular -- different comparisons, computed at different layers).
    weinstein_stage: Literal["base", "advance", "top", "decline"] | None = None
    weinstein_stage_since_date: date | None = None
    weinstein_stage_since_is_lower_bound: bool | None = None
    # NULL alongside a NULL weinstein_stage means "never computed under
    # this feature yet" (a legacy/never-reprocessed row); a real (always
    # sub-40) int alongside a NULL weinstein_stage means a compute genuinely
    # ran and found too little history -- see models.py::TrendAnalysis's
    # own comment for the full story.
    weinstein_weeks_available: int | None = None
    weinstein_stage_changed: bool | None = None
    weinstein_ma_slope_pct: float | None = None
    weinstein_vs_ma_pct: float | None = None
    weinstein_volume_ratio: float | None = None
    weinstein_mansfield_rs: float | None = None
    weinstein_breakout_confirmed: bool | None = None
    # The engine parameters this row's Weinstein fields were computed with
    # (null on a row computed before the configurable engine existed) -- the
    # UI labels ("30-wk EMA", band %) read this, not the live Settings, so
    # they always describe the row they sit next to.
    weinstein_params: WeinsteinParamsOut | None = None
    # "Pending confirmation" + ETA -- see WeinsteinPendingOut's own
    # docstring. Null whenever the ticker isn't currently pending a Stage
    # 2/Stage 4 transition (the common case).
    pending: WeinsteinPendingOut | None = None


class TechnicalEntrySignalOut(BaseModel):
    """Latest technical entry-signal read for one (ticker, signal_type,
    timeframe) -- see models.py::TechnicalEntrySignal for the persisted
    shape this mirrors. None (the whole object, via the endpoint returning
    `| None`) when this ticker has no computed row yet -- either it isn't a
    member of a watchlist named E<number> or ETF the nightly job
    reads (see pipeline/nightly_entry_signal_calculation.py), or it hasn't
    been processed yet, same "not computed yet, not a fabricated neutral
    result" convention as TrendAnalysisOut above.

    `active` is derived, never the raw stored value -- there is no longer a
    raw stored flag at all (a `fired` column used to play that role; see
    models.py::TechnicalEntrySignal's own comment on why it was replaced by
    fired_at instead). For signal_type="bb_rsi", derived as fired_at within
    the last data/entry_signal_data.py::ACTIVE_WINDOW_DAYS; for
    signal_type="warren", derived instead from signal_kind membership (see
    data/warren_signal_data.py::is_warren_signal_active) -- no time window
    at all, since Warren's own state machine (not a flat timer) is what
    determines whether a signal is still "in trade."

    signal_kind/gray_suppressed/stop_count are only ever populated for
    signal_type="warren" (always None for "bb_rsi") -- see
    models.py::TechnicalEntrySignal's own comment on these three columns."""

    ticker: str
    signal_type: str  # "bb_rsi" | "warren"
    timeframe: str  # "2h"
    active: bool
    fired_at: datetime | None = None
    pct_b: float | None = None
    rsi: float | None = None
    close: float | None = None
    stop_price: float | None = None
    signal_kind: str | None = None  # "warren" only -- one of analysis.warren_signal.types.SIGNAL_KINDS
    gray_suppressed: bool | None = None  # "warren" only
    stop_count: int | None = None  # "warren" only
    source: str  # "fmp" (legacy rows may read "yahoo")
    as_of: datetime
    computed_at: datetime


class ZoneOut(BaseModel):
    """One clustered Liquidity Zone (LP) level -- see
    analysis/liquidity_zones/types.py::Zone for the pure-engine shape this
    mirrors. `distance_pct` is derived at read time from the price and the
    timeframe's own last_price (never stored), same convention as
    TechnicalEntrySignalOut.active."""

    price: float
    distance_pct: float  # (price - last_price) / last_price * 100
    cluster_size: int
    formed_at: date


class BrokenZoneOut(BaseModel):
    """The single most-recently-breached support or resistance level that
    still qualifies for display -- see
    analysis/liquidity_zones/types.py::BrokenZone for the pure-engine
    shape this mirrors. `distance_pct` is derived the same way ZoneOut's
    own is. `breached_at` is the later, confirming swing's own date (the
    "breach bar"), distinct from `formed_at` (the original swing's own
    date)."""

    price: float
    distance_pct: float  # (price - last_price) / last_price * 100
    formed_at: date
    breached_at: date


class LiquidityZoneOut(BaseModel):
    """One timeframe's (Daily or Weekly) complete Liquidity Zone (LP) read
    -- see models.py::LiquidityZoneAnalysis for the persisted shape this
    mirrors. support_zones/resistance_zones are already the nearest-N,
    correct-side-of-price, clustered zones (see analysis/liquidity_zones/
    engine.py) -- an empty list means genuinely zero currently-valid zones
    on that side (sparse history, or price has never pulled back far
    enough to form one yet), not a data gap. broken_support/
    broken_resistance are None whenever no breach currently qualifies for
    display (see BrokenZoneOut's own docstring)."""

    timeframe: str  # "daily" | "weekly"
    last_price: float
    as_of: date
    computed_at: datetime
    source: str  # "fmp"
    support_zones: list[ZoneOut]
    resistance_zones: list[ZoneOut]
    broken_support: BrokenZoneOut | None = None
    broken_resistance: BrokenZoneOut | None = None


class LiquidityZonesOut(BaseModel):
    """Both timeframes bundled into one response -- the ticker-page card
    always shows Daily and Weekly together, so this avoids two round
    trips (a deliberate deviation from TechnicalEntrySignalOut's
    one-timeframe-per-call shape). None (the whole object, via the
    endpoint returning `| None`) only when NEITHER timeframe has ever been
    computed for this ticker -- either it isn't a member of a watchlist
    named E<number> or ETF the nightly job reads, or it hasn't been
    processed yet. If only one timeframe has been computed (e.g. a
    brand-new deploy), the other side is None rather than the whole
    object being None."""

    daily: LiquidityZoneOut | None = None
    weekly: LiquidityZoneOut | None = None


class ChartBarOut(BaseModel):
    time: str  # "YYYY-MM-DD"; on the 2H_90D range the naive-ET candle START "YYYY-MM-DDTHH:MM:SS" (09:30/11:30/13:30/15:30)
    open: float
    high: float
    low: float
    close: float


class ChartStagePointOut(BaseModel):
    """One weekly bar's Weinstein stage AT THAT WEEK (replayed through the
    sticky state machine, not the ticker's current stage) -- W_4Y only."""

    time: str  # "YYYY-MM-DD"
    stage: Literal["base", "advance", "top", "decline"]


class ChartLinePointOut(BaseModel):
    """One point in a simple line series -- reused for ema21/sma50/sma200/rsi,
    same shared-shape convention Options Tracker's own chart schema uses for
    its equivalent EMA/SMA/RSI series."""

    time: str
    value: float


class ChartBollingerPointOut(BaseModel):
    time: str
    upper: float
    middle: float
    lower: float


class ChartStochasticPointOut(BaseModel):
    time: str
    k: float
    d: float


class ChartMarkerOut(BaseModel):
    """One historical entry-signal marker -- either BB+RSI (sourced from
    TechnicalEntrySignalEvent) or Warren (sourced from WarrenSignalEvent),
    see data/chart_data.py's grouping logic for both. ChartOut.
    entry_signal_markers / warren_signal_markers below each carry a list of
    these, one per exchange-calendar day (daily views) or Monday-anchored
    week (weekly view) within the visible window -- for Warren, grouped by
    (bucket, kind) rather than bucket alone, so two different arrows firing
    in the same visible bar (e.g. Blue Up and Yellow Up) both render as
    distinct markers. `time` is always a plain "YYYY-MM-DD" date string,
    deliberately never a raw timestamp -- fired_at is stored naive-Eastern,
    and emitting only the already-bucketed date avoids a client re-deriving
    "which day" from a timestamp under a different, incorrect timezone
    assumption.

    `kind` drives frontend marker styling (color/shape/position) --
    `"bb_rsi"` for every BB+RSI marker, or one of
    analysis.warren_signal.types.SIGNAL_KINDS for a Warren marker. `label`
    stays human-readable text ("BB+RSI", "Blue Up", "Yellow Down", ...)."""

    time: str  # "YYYY-MM-DD"; "YYYY-MM-DDTHH:MM:SS" (the candle start) on the 2H_90D range
    label: str  # "BB+RSI" | "Blue Up" | "Yellow Up" | "Gray Up" | "Blue Down" | "Yellow Down" | "Gray Down"
    kind: str  # "bb_rsi" | one of analysis.warren_signal.types.SIGNAL_KINDS


class ChartZoneOut(BaseModel):
    """One Liquidity Zone (LP) level to overlay on the Chart tab's main
    pane -- see data/liquidity_zone_data.py::ZoneOut for the richer
    (distance_pct-carrying) shape this is sourced from; only what the
    chart needs to draw a price line is kept here. `formed_at` is the
    establishing swing's own date (same field LiquidityZoneAnalysis calls
    formed_at), already filtered server-side to fall within this
    response's own visible window -- see get_chart_data's range-filtering
    comment. `broken=True` marks the (at most one per side) most-recently-
    breached zone -- see BrokenZoneOut -- so the frontend can render it in
    a distinct color while reusing the exact same LineSeries mechanism as
    an active zone."""

    side: str  # "support" | "resistance"
    price: float
    formed_at: str  # "YYYY-MM-DD"; the swing candle's "YYYY-MM-DDTHH:MM:SS" start on the 2H_90D range
    broken: bool = False


class ChartEarningsMarkerOut(BaseModel):
    """One earnings-report marker on the Chart tab's price pane -- see
    data/chart_data.py::_earnings_markers. `time` is the chart bar the marker
    attaches to (the report's own trading day for daily views, its
    Monday-anchored week for the weekly view); `event_date` is the actual
    report date, which differs from `time` in the weekly view and is what a
    tooltip should show. EPS is per-share, split-adjusted, and either side can
    be None (no analyst estimate on file)."""

    time: str  # "YYYY-MM-DD"
    event_date: str  # "YYYY-MM-DD"
    eps_actual: float | None = None
    eps_estimated: float | None = None


class ChartDividendMarkerOut(BaseModel):
    """One dividend ex-date marker -- same time/event_date split as
    ChartEarningsMarkerOut. `amount` is per-share and split-adjusted; when two
    ex-dates land in one bar (a regular plus a special dividend in the same
    week) it is their sum and `event_date` is the earlier of the two."""

    time: str  # "YYYY-MM-DD"
    event_date: str  # "YYYY-MM-DD"
    amount: float


class ChartWarrenLevelsOut(BaseModel):
    """Warren's own reference levels, read from the engine constants (analysis.warren_signal.state_machine.
    warren_reference_levels) so the panes can never drift from the thresholds the arrows use. RSI: 12 (Blue
    trigger -- omitted for tickers with their own Blue profile), 30, 70, 80.81 (bear1), 84.75 (Yellow-sell);
    ADX: 40; WVF: 0.40."""

    rsi: list[float]
    adx: list[float]
    wvf: list[float]


class ChartOut(BaseModel):
    """OHLC + indicators for one ticker-page Chart tab view -- see
    data/chart_data.py for the fetch/compute mechanism. Computed fully
    on-demand (no persisted table, no nightly job -- confirmed fast enough
    for a page load in the Chart tab latency investigation), so this always
    reflects a live read (2026-09-18 -- FMP is no longer a data source here
    at all), never a stale precomputed row.

    `zones`/`zones_available` overlay the separately-computed, nightly-cron
    -backed Liquidity Zone (LP) feature (data/liquidity_zone_data.py) --
    unlike every other field on this schema, these are a cache-only read,
    not computed from the bars fetched for this same request."""

    range: str  # "2H_90D" | "D_6M" | "D_1Y" | "D_2Y" | "W_4Y"
    timeframe: str  # "2h" | "daily" | "weekly"
    bars: list[ChartBarOut]
    ema21: list[ChartLinePointOut]
    sma50: list[ChartLinePointOut]
    sma200: list[ChartLinePointOut]
    bollinger: list[ChartBollingerPointOut]
    stochastic: list[ChartStochasticPointOut]
    rsi: list[ChartLinePointOut]
    # Every historical fire within this response's visible window, one per
    # exchange-calendar day (daily views) / Monday-anchored week (weekly
    # view) -- see data/chart_data.py's grouping logic. Deliberately NOT
    # gated on TechnicalEntrySignal's own 7-day "active" window (that gate
    # only makes sense for "is there a live, tradeable signal right now,"
    # not for a historical chart marker) -- an old, long-inactive fire
    # still gets a marker if it falls in the visible range. Empty (not
    # None) when the ticker is tracked but had no fires in this window --
    # entry_signal_available, not this field, distinguishes "not tracked
    # at all" from "tracked, nothing fired here."
    entry_signal_markers: list[ChartMarkerOut] = []
    entry_signal_available: bool
    # W_4Y only (empty/None on the daily ranges): the live-configured Weinstein MA
    # (WeinsteinSettings type+length, e.g. "EMA30") and the per-week stage of every
    # visible bar, from the same engine functions the nightly job uses. A week
    # before the state machine is seeded has no entry (uncolored on the chart).
    weinstein_ma: list[ChartLinePointOut] = []
    weinstein_ma_label: str | None = None
    weinstein_stages: list[ChartStagePointOut] = []
    # Warren's own marker pair, parallel to entry_signal_markers/
    # entry_signal_available above rather than merged into it -- keeps
    # BB+RSI's own wire shape/semantics untouched (same "add a new pair
    # alongside the old one" convention zones/zones_available below already
    # established for Liquidity Zones). warren_signal_available=False means
    # "not tracked" (not on a monitored watchlist, or not yet processed), same
    # as entry_signal_available's own convention -- an empty
    # warren_signal_markers with warren_signal_available=True means
    # "tracked, nothing fired in this window."
    warren_signal_markers: list[ChartMarkerOut] = []
    warren_signal_available: bool
    # zones_available mirrors entry_signal_available's convention: False
    # means the ticker isn't on a watchlist named E<number> or ETF (or the
    # nightly LP job hasn't reached it yet), not "genuinely zero zones" --
    # an empty `zones` list with zones_available=True means the latter.
    zones: list[ChartZoneOut] = []
    zones_available: bool
    # Earnings-report dates / dividend ex-dates within this response's visible
    # window (see data/chart_events_data.py + chart_data.py), read from the nightly
    # CorporateEvent cache. `events_source` is "fmp", or
    # None when the ticker isn't cached -- the only way to tell "couldn't fetch"
    # from a genuinely empty list (a non-dividend payer). The UI omits both
    # marker types silently in either case.
    earnings_markers: list[ChartEarningsMarkerOut] = []
    dividend_markers: list[ChartDividendMarkerOut] = []
    events_source: str | None = None
    # 2H_90D only (empty/None on every other range): the Warren engine's OWN indicator series -- the same
    # objects its state machine read, not a second calculation -- for the three sub-panes, plus its
    # reference levels. Deliberately not the `rsi` field above (that is the EWM-seeded RSI(14) the daily
    # ranges plot). ADX/+DI/-DI/WVF are percentages-scale values (WVF is wvfBuy). Times are naive-ET
    # "YYYY-MM-DDTHH:MM:SS" candle-start stamps, like every other time on a 2H_90D response.
    warren_rsi: list[ChartLinePointOut] = []
    warren_adx: list[ChartLinePointOut] = []
    warren_plus_di: list[ChartLinePointOut] = []
    warren_minus_di: list[ChartLinePointOut] = []
    warren_wvf: list[ChartLinePointOut] = []
    warren_levels: ChartWarrenLevelsOut | None = None
    # Always "fmp" (Yahoo removed in Phase 6b); an empty chart is chart_available=False.
    source: str
    chart_available: bool  # False only for a genuinely bad/delisted ticker with no bars at all


class LiquidityZoneConfigOut(BaseModel):
    key: str
    swing_bars_each_side: int
    cluster_pct: float
    max_lps_per_side: int
    over_cap_priority: Literal["nearest_price", "most_recent"]
    keep_last_breached_support: bool
    keep_last_breached_resistance: bool
    only_keep_if_breached_recently: bool
    breach_recency_bars: int
    updated_at: datetime


class LiquidityZoneConfigIn(BaseModel):
    swing_bars_each_side: int = Field(ge=1, le=3)
    cluster_pct: float = Field(ge=0, le=3)
    max_lps_per_side: int = Field(ge=1, le=10)
    over_cap_priority: Literal["nearest_price", "most_recent"]
    keep_last_breached_support: bool
    keep_last_breached_resistance: bool
    only_keep_if_breached_recently: bool
    breach_recency_bars: int = Field(ge=1, le=52)


class WeinsteinConfigOut(WeinsteinParamsOut):
    key: str
    updated_at: datetime


class WeinsteinConfigIn(BaseModel):
    ma_length: int = Field(ge=2, le=200)
    ma_type: Literal["SMA", "EMA"]
    within_range_pct: float = Field(ge=0, le=50)
    slope_lookback: int = Field(ge=1, le=52)
    breakout_volume_mult: float = Field(gt=0, le=20)
    volume_avg_length: int = Field(ge=2, le=200)
    rs_benchmark: str = Field(min_length=1, max_length=20)
    rs_smoothing_length: int = Field(ge=2, le=200)


class MomentumSnapshotRowOut(BaseModel):
    """One ticker's row in a Momentum snapshot -- see models.py::
    MomentumSnapshot. `company_name`/`overall_score` are joined live from
    TickerScore at request time (data/momentum_data.py), not stored in the
    snapshot itself, so `overall_score` always reflects today's Fathom
    score -- shown for context only, never used in the ranking. `moat` IS
    a stored snapshot (what the rating was at compute time), unlike those
    two -- see MomentumSnapshot's own docstring for why."""

    ticker: str
    company_name: str | None = None
    moat: Literal["wide_moat", "narrow_moat", "no_moat"]
    return_3mo: float
    return_6mo: float
    return_12mo: float
    composite_score: float
    rank: int
    overall_score: int | None = None
    # Informational only -- not part of the composite/rank. None for snapshots that predate them.
    return_1w: float | None = None
    return_1mo: float | None = None
    # The nightly official close (models.py::TickerLastClose), read from the DB -- no FMP call. None for a
    # ticker the nightly last-close job has not written yet. `quote_currency` joined live from TickerScore.
    last_price: float | None = None
    quote_currency: str | None = None


class MomentumOut(BaseModel):
    """A full ranked Momentum snapshot for one month. as_of_date/computed_at
    are both None (with rows == []) when no snapshot exists yet at all --
    the pre-first-cron-run empty state, and also what a `period="previous"`
    request returns when only one month's snapshot has ever been computed
    -- never a 404/error either way (see data/momentum_data.py::
    get_momentum_snapshot)."""

    as_of_date: date | None
    computed_at: datetime | None
    rows: list[MomentumSnapshotRowOut]


class EtfMomentumRowOut(BaseModel):
    """One ETF's row in the ETF Momentum top 5 -- see models.py::EtfMomentumSnapshot. Same return columns as
    MomentumSnapshotRowOut but no `moat`, `overall_score` or `quote_currency` (an ETF has none of them).
    `company_name` is EtfScreenerRow.name and `last_price` the nightly TickerLastClose, both joined at request time."""

    ticker: str
    company_name: str | None = None
    return_3mo: float
    return_6mo: float
    return_12mo: float
    composite_score: float
    rank: int
    return_1w: float | None = None
    return_1mo: float | None = None
    last_price: float | None = None


class EtfMomentumOut(BaseModel):
    """The top ETF_MOMENTUM_TOP_N rows of one month's stored ETF ranking. `total_ranked` is how many ETFs the
    snapshot scored (the full ranking stays stored). as_of_date/computed_at are None, rows [] and total_ranked 0
    when no matching snapshot exists (none yet, or no earlier month for `previous`) -- never a 404."""

    as_of_date: date | None
    computed_at: datetime | None
    total_ranked: int
    rows: list[EtfMomentumRowOut]


class SectorHeatmapCellOut(BaseModel):
    """One (ETF, window) cell. `return_pct` is a trailing TOTAL return in
    percentage points (4.25 == +4.25%); None (with `base_date` None) when
    the fund has no history that far back, or no row exists for the
    current as_of_date -- never imputed. `base_date` is the trading day
    whose close the return is measured from."""

    return_pct: float | None = None
    base_date: date | None = None


class SectorHeatmapRowOut(BaseModel):
    ticker: str
    name: str
    cells: dict[str, SectorHeatmapCellOut]  # keyed by window, every entry of SectorHeatmapOut.windows present


class SectorHeatmapOut(BaseModel):
    """The latest Sector Heatmap -- see models.py::SectorEtfReturn.
    `as_of_date`/`computed_at` are both None (with rows == []) before the
    nightly job has ever run, never a 404. Once data exists, every sector
    is always listed: an ETF with no row at the latest as_of_date (its
    fetch failed that night) has all-None cells rather than an older
    night's numbers shown under a newer date. `windows` fixes the column
    order (scoring/etf_returns.py::WINDOWS); `rows` follow the fixed
    universe order, leaving any sorting to the client."""

    as_of_date: date | None
    computed_at: datetime | None
    windows: list[str]
    rows: list[SectorHeatmapRowOut]


class MarketBreadthPointOut(BaseModel):
    """One session of market breadth -- see models.py::MarketBreadthSnapshot.
    Percentages are in percentage POINTS (27.8 == 27.8%) and None when that
    metric's eligible count is 0. `stale_excluded` constituents had no bar
    that session and are in no count; the *_eligible fields are the
    denominators. `is_backfilled` rows apply today's constituents to a past
    date (survivorship-biased); live nightly rows are point-in-time."""

    as_of_date: date
    # None for a row that predates the 20-day metric and hasn't been backfilled yet (a NULL column),
    # as well as for a session with no eligible tickers -- the UI renders both as "no reading".
    pct_above_sma20: float | None
    pct_above_sma50: float | None
    pct_above_sma200: float | None
    sma20_above: int | None
    sma50_above: int
    sma200_above: int
    new_highs: int
    new_lows: int
    net_new_highs: int  # new_highs - new_lows
    constituents: int
    stale_excluded: int
    sma20_eligible: int | None
    sma50_eligible: int
    sma200_eligible: int
    hl_eligible: int
    is_backfilled: bool


class MarketBreadthOut(BaseModel):
    """The S&P 500 market-breadth history. `series` is every stored session,
    oldest first (the table is never pruned and a row is ~100 bytes);
    `latest` is its last element. All of `as_of_date`/`computed_at`/`latest`
    are None (with series == []) before any row exists, never a 404."""

    universe: str
    as_of_date: date | None
    computed_at: datetime | None
    latest: MarketBreadthPointOut | None
    series: list[MarketBreadthPointOut]


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
    # Real values populate here even for a CFO-exempt ticker (Bank/Property
    # Developer/Commodity) -- same display/scoring decoupling as
    # Step1Out.cfo (2026-09-11); this row carries no `cfo_exempt_reason` of
    # its own, so it can't distinguish "exempt" from "not exempt" anyway,
    # only the Financials tab's Step1Out does.
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
    # See models.py::TickerScore.quote_currency -- None (treat as "USD")
    # for a row computed before this field existed.
    quote_currency: str | None = None
    # The nightly official close (models.py::TickerLastClose), cache-only like every other field here.
    # None for a ticker the nightly last-close job has not written yet; denominated in quote_currency.
    last_price: float | None = None
    # See models.py::TickerScore.reported_currency -- what the Revenue/Net
    # Income/CFO mini trend chart below (years/revenue/net_income/cfo) is
    # denominated in. Must always match the Financials tab's own
    # reported_currency for the same ticker (same underlying annual data).
    reported_currency: str | None = None
    pe_ratio: float | None = None
    beta: float | None = None
    # See models.py::TickerScore.perf_5y_vs_spy_pct/_status.
    perf_5y_vs_spy_pct: float | None = None
    perf_5y_vs_spy_status: str | None = None
    # See models.py::TickerScore.speculative_growth_qualifies.
    speculative_growth_qualifies: bool | None = None
    # FMP's live consensus label (ConsensusBanner.rating), "N/A" when there's
    # no cached analyst-ratings data for this ticker yet -- never null.
    consensus_rating: str
    added_at: datetime
    # TickerScore.is_etf of the cache-only score row; the table shows an "ETF" marker in place of
    # the (always blank) score cells. False for a never-viewed ticker with no score row.
    is_etf: bool = False


class EtfWatchlistRowOut(BaseModel):
    """One row of GET /api/watchlists/{id}/etf-rows (the table of the list named "ETF"): the ETF screener row's
    stored figures (models.py::EtfScreenerRow, through the same `_row_out`, so Beta is already null unless the asset
    class contains "equity") plus the cached profile's exchange (for the TradingView export). Every figure is None for a
    ticker with no EtfScreenerRow yet. Percent fields are percent numbers (0.09 = 0.09%)."""

    ticker: str
    name: str | None = None
    # Cached profile exchange (EXCHANGE:SYMBOL pairs for the export button); None when no profile is cached.
    exchange: str | None = None
    last_price: float | None = None
    pct_change_1d: float | None = None
    asset_class: str | None = None
    expense_ratio: float | None = None
    aum: float | None = None
    holdings_count: int | None = None
    avg_volume_30d: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    return_ytd: float | None = None
    return_1y: float | None = None


class EtfScreenerRowOut(BaseModel):
    """A row of GET /api/etf-screener (models.py::EtfScreenerRow). `beta` is already nulled unless the asset class contains
    "equity" (has_equity_beta). Percent fields are percent numbers (0.09 = 0.09%); see the model."""

    ticker: str
    name: str | None = None
    asset_class: str | None = None
    expense_ratio: float | None = None
    aum: float | None = None
    holdings_count: int | None = None
    last_price: float | None = None
    pct_change_1d: float | None = None
    avg_volume_30d: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    return_ytd: float | None = None
    return_1y: float | None = None
    vs_spy_1y: float | None = None
    weinstein_stage: str | None = None
    weinstein_stage_since_date: date | None = None
    weinstein_stage_since_is_lower_bound: bool | None = None
    weinstein_ma_slope_pct: float | None = None
    weinstein_vs_ma_pct: float | None = None
    weinstein_pending_direction: str | None = None
    bb_rsi_entry_signal: bool | None = None
    warren_active_signal_kind: str | None = None
    warren_last_buy_fired_at: datetime | None = None
    as_of_date: date | None = None
    info_updated_at: datetime | None = None
    updated_at: datetime | None = None


class EtfRangeOut(BaseModel):
    min: float | None = None
    max: float | None = None


class EtfScreenerMeta(BaseModel):
    # ETFs in the ETF universe (data/tracked_universe.py::load_etf_universe), with or without a row yet.
    total_etfs: int
    # How many of them have a row, i.e. len(GET /api/etf-screener). total_etfs - row_count is the "X of Y" gap.
    row_count: int
    # Distinct non-null asset classes among the returned rows, sorted.
    asset_classes: list[str] = []
    # Min/max over the returned rows for every numeric filter, always all keys (null/null when no value):
    # expense_ratio, aum, last_price, pct_change_1d, beta (after the equity-only rule), return_1y, vs_spy_1y.
    ranges: dict[str, EtfRangeOut] = {}


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
    # FMP's `reportedCurrency` (e.g. "TWD"), None for USD reporters --
    # cosmetic label only (only a US-listed ADR of a foreign reporter is ever
    # non-USD -- see docs/specs/valuation.md §2.1b). Every figure in this schema stays the company's
    # raw reported number, deliberately never converted -- this field exists
    # purely so the frontend can caption the table with which currency
    # that raw number actually is.
    reported_currency: str | None = None


class RatiosOut(BaseModel):
    """Raw-metrics display only (no scoring/verdicts) for the Ratios tab --
    unlike FinancialsOut there's no annual/quarterly split, since FMP's
    stable /key-metrics and /ratios endpoints 402 on period=quarter under
    our current plan; this is Annual (10yr) + TTM only, a single flat table
    closer in shape to FinancialsPeriodOut alone than to FinancialsOut."""

    ticker: str
    periods: list[str]
    groups: list[FinancialsGroup]
    # Same cosmetic-only label as FinancialsOut.reported_currency above --
    # per-share/money rows here stay raw/un-converted; ratio/percent rows
    # are dimensionless and the label doesn't apply to them at all.
    reported_currency: str | None = None


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
    # All 5 of FMP's own buckets (Strong Buy/Buy/Hold/Sell/Strong Sell,
    # relabeled Buy/Outperform/Hold/Underperform/Sell -- same 1:1 mapping
    # RecommendationDetailsColumn uses), not a 3-bucket collapse -- see
    # analyst_ratings_data.py's own comment on why history must stay
    # uncollapsed even though ConsensusBanner's ITS OWN 3-bucket summary
    # deliberately does collapse.
    buy_pct: float
    outperform_pct: float
    hold_pct: float
    underperform_pct: float
    sell_pct: float
    # Weighted score (5=Strong Buy ... 1=Strong Sell) averaged across all
    # analysts in that month's grades-historical snapshot -- see
    # analyst_ratings_data.py's _weighted_score.
    avg_rating: float
    # None until nightly_price_target_snapshot.py has captured a snapshot
    # for/near this month -- FMP has no historical price-target series of
    # its own, so this line starts empty and fills in going forward.
    avg_price_target: float | None = None
    # How avg_price_target was derived: "legacy_all_analysts" (historical
    # reconstruction, every analyst since 2021, no recency cutoff) or
    # "live_consensus" (FMP's ~180-day consensus, from the daily snapshot
    # job). None when there is no target or the row is untagged. The two are
    # not comparable, so the chart draws them as separate segments.
    methodology: str | None = None
    # FMP split-adjusted close (not dividend-adjusted) "on or before" this row's
    # own `date` (see analyst_ratings_data.py::_price_on_or_before) --
    # feeds the Price Target Trend chart's optional price overlay. Only
    # ever populated from the first row where avg_price_target itself is
    # non-null onward (never before -- the overlay isn't meant to show
    # price for a stretch the target line doesn't cover), and stays None
    # past that point too if the stored history doesn't reach back this
    # far -- the frontend reads a None run right after the target series'
    # own first real point as "price data starts later than this" and
    # marks it accordingly, rather than this being a distinct flag.
    price_on_date: float | None = None


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


class PriceTargetRecencyBucket(BaseModel):
    """One row of FMP's /price-target-summary -- a ready-made recency-
    bucketed average target, independent of PriceTargetSnapshot/history
    above (which is our own reconstructed monthly series). Purely
    informational, same as every other Analyst Ratings figure -- no scoring
    implications."""

    label: str  # "Last Month" | "Last Quarter" | "Last Year" | "All Time"
    avg_price_target: float | None = None
    analyst_count: int


class AnalystRatingsOut(BaseModel):
    ticker: str
    banner: ConsensusBanner
    price_target: PriceTargetSummary
    price_target_by_recency: list[PriceTargetRecencyBucket]
    history: list[RatingHistoryPoint]
    recommendation_details: list[RecommendationDetailsColumn]
    # fetched_at of the cached grades_consensus row banner/recommendation_
    # details[0] ("Current") are both built from -- FMP's own live, rolling
    # consensus, refreshed independently of grades_historical (the monthly
    # rating-action snapshots behind `history`/the Recommendation Trend
    # chart). Surfaced so the UI can caption Current Distribution rather
    # than let it look reconcilable against that chart's own totals.
    grades_consensus_as_of: datetime | None = None


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


class InstitutionalOwnershipQuarterOut(BaseModel):
    """One quarter's point on the ownership-%/holder-count trend chart --
    see data/institutional_ownership_data.py. Only quarters that were both
    filed (FMP returned a real row) and passed the plausibility guardrail
    appear here at all; a dropped quarter is invisible to this list, not
    represented with nulls -- InstitutionalOwnershipOut.trend_quarters_shown
    is how the frontend knows fewer than trend_quarters_total are present."""

    year: int
    quarter: int
    date: date
    ownership_percent: float | None = None
    ownership_percent_change: float | None = None
    investors_holding: int | None = None
    investors_holding_change: int | None = None


class InstitutionalOwnershipPositionsOut(BaseModel):
    """This quarter's opened/increased/reduced/closed 13F position counts.
    Computed independently of InstitutionalOwnershipOut.ownership_valid --
    a quarter whose ownership%/shares-outstanding relationship fails the
    plausibility guardrail can still have perfectly good position counts,
    so this renders even when the headline stat cards don't."""

    opened: int
    opened_change: int | None = None
    increased: int
    increased_change: int | None = None
    reduced: int
    reduced_change: int | None = None
    closed: int
    closed_change: int | None = None


class InstitutionalHolderOut(BaseModel):
    """One row of the top-holders table (extract-analytics/holder), already
    sorted descending by market_value by FMP itself -- no client-side
    re-sort needed."""

    investor_name: str
    market_value: float | None = None
    market_value_change_pct: float | None = None
    shares: float | None = None
    shares_change_pct: float | None = None


class InstitutionalOwnershipOut(BaseModel):
    """The Institutional Ownership ticker-page tab -- see
    data/institutional_ownership_data.py for the full four-state mechanism
    this represents (group disabled / no 13F coverage / a plausibility
    guardrail degrading just the headline stats / a normal complete read).
    Deliberately not a single top-level success/failure: `enabled`,
    `no_coverage`, and `ownership_valid` are independent flags a consumer
    must check separately, since `positions`/`top_holders` can be populated
    even when `ownership_valid` is false.

    `shares_outstanding` is always Fathom's own
    helpers.shares.compute_shares_outstanding figure, never FMP's own
    implied one (numberOf13Fshares / (ownershipPercent/100)) -- the
    feasibility investigation found the latter diverges materially on
    dual-class/GP-LP names (and reads >100% for at least one real ticker,
    ARES) and would be a second, silently-inconsistent shares-outstanding
    figure on the same page. `shares_held` is FMP's own numberOf13Fshares
    for the latest quarter (a real filed count, not derived)."""

    ticker: str
    enabled: bool
    no_coverage: bool
    as_of_quarter: str | None = None  # "2026Q2"
    as_of_date: date | None = None
    fetched_at: datetime | None = None
    # True only when the last successful fetch is older than ~4 months --
    # on top of, not instead of, the normal ~weekly cache refetch attempts
    # (13F filings trickle in well past the nominal 45-day deadline).
    data_stale_warning: bool = False
    ownership_valid: bool
    ownership_percent: float | None = None
    ownership_percent_change: float | None = None
    holder_count: int | None = None
    holder_count_change: int | None = None
    shares_held: float | None = None
    shares_outstanding: float | None = None
    shares_outstanding_source: str | None = None
    sentiment: str | None = None  # "Accumulating" | "Neutral" | "Distributing"
    sentiment_rising_count: int | None = None  # of the last 4 quarters
    positions: InstitutionalOwnershipPositionsOut | None = None
    trend: list[InstitutionalOwnershipQuarterOut] = []
    trend_quarters_shown: int = 0
    trend_quarters_total: int = 8
    top_holders: list[InstitutionalHolderOut] = []
    # Explains a degraded ownership_valid=False state -- None otherwise.
    note: str | None = None



class EtfSectorWeightOut(BaseModel):
    sector: str
    # Percent of the fund (0-100), as FMP reports it in /etf/info `sectorsList[].exposure`.
    weight: float


class EtfTradingDataOut(BaseModel):
    """The Overview's "Trading data" block (data/etf_data.py::_trading_data). Built only from rows the app
    already holds -- cached daily bars, the cached quote and profile, the cached /etf/info asset class --
    so it never costs an FMP call. A value that is None (unavailable) or zero is omitted by the UI, and
    the whole block is None on the Overview when every value is.

    perf_* are percent price returns from the cached daily bars (split-adjusted, NOT dividend-adjusted),
    measured to `perf_as_of`, the last completed session with a bar."""

    perf_1m: float | None = None
    perf_ytd: float | None = None
    perf_1y: float | None = None
    perf_as_of: date | None = None
    week52_low: float | None = None
    week52_high: float | None = None
    # Share volume over the trailing 30 calendar days / close x volume over the last 20 trading days.
    avg_volume_30d: float | None = None
    avg_dollar_volume_20d: float | None = None
    # FMP profile `lastDividend` is the TRAILING-12-MONTH distribution per share (not the last payment);
    # the yield is that over the current price, in percent. Not an SEC yield.
    distribution_ttm_per_share: float | None = None
    distribution_ttm_yield_pct: float | None = None
    # Only when the asset class (from /etf/info) contains "equity"; None for bond, commodity and other funds.
    beta: float | None = None


class EtfOverviewOut(BaseModel):
    """ETF page Overview tab, from FMP /etf/info only (see data/etf_data.py).

    status "ok": fund facts present; every fact FMP did not return is None (the UI omits it).
    "unavailable": nothing to show -- the etf_info data group is off (or not on the plan) with no
    cached row, or the fetch failed with no cached row; `reason` says which.
    "no_data": FMP answered but has no fund record for this ticker (`[]`)."""

    ticker: str
    status: Literal["ok", "unavailable", "no_data"]
    reason: Literal["group_off", "fetch_failed"] | None = None
    name: str | None = None
    issuer: str | None = None
    asset_class: str | None = None
    # Percent (0.09 means 0.09%), None when absent.
    expense_ratio: float | None = None
    assets_under_management: float | None = None
    holdings_count: int | None = None
    nav: float | None = None
    nav_currency: str | None = None
    avg_volume: float | None = None
    inception_date: str | None = None
    domicile: str | None = None
    description: str | None = None
    website: str | None = None
    # Largest first. EMPTY when the fund is not an equity fund, or when the only entry is
    # "Cash & Others 100%" -- the UI then shows its "not shown for funds that don't hold stocks" note.
    sector_weights: list[EtfSectorWeightOut] = []
    # None when status is not "ok", or when every Trading data value is unavailable.
    trading_data: EtfTradingDataOut | None = None
    # When FMP last updated the record (/etf/info `updatedAt`), and when this app last fetched it.
    updated_at: str | None = None
    fetched_at: datetime | None = None


class EtfWatchlistAddOut(BaseModel):
    watchlist_id: int
    watchlist_name: str
    # False when the ticker was already on the ETF watchlist (the call is idempotent).
    added: bool


# --- the opt-in universe API (docs/specs/tracked-universe.md, "API") --------------------------------------------------


class UniverseStatusOut(BaseModel):
    """GET /api/tickers/{t}/universe: the state of a ticker (protected / added / browsed) and whether it is in the
    universe. Since the classification flip (2026-10-03) `in_universe` and `classification` come from the same
    classification the universes use, so they cannot disagree. Cache-only: no FMP call, no write, no TickerView touch."""

    ticker: str
    # 'stock' | 'etf'; null when no profile (or score row) is cached yet for the ticker.
    kind: Literal["stock", "etf"] | None = None
    # Membership in the real universe (`load_tracked_universe` / `load_etf_universe`), from the SAME classification
    # (`classify_one`): protected-or-added AND not delisted AND known to the app. False for a delisted ticker even when
    # protected or added, and for a protected ticker the app holds no profile, score, index or watchlist row for.
    in_universe: bool
    # The classification reason: delisted | index | watchlist | system | manual | added | browsed | expired | untracked,
    # or null when the app does not know the ticker (nothing cached, never opened).
    classification: str | None = None
    # 'protected': at least one protection (reasons non-empty; added_at may also be set). 'added': explicitly added, no
    # protection. 'browsed': neither (the classification may call it browsed, expired or untracked).
    state: Literal["protected", "added", "browsed"]
    # Protections, e.g. "index:sp500", "watchlist:E3", "seed", "benchmark", "rs_benchmark", "manual:moat".
    reasons: list[str]
    # state == 'browsed', not delisted, and (profile not cached yet, or US-listed).
    can_add: bool
    # state == 'added' (so: added_at set and NO protection applies).
    can_remove: bool
    added_at: datetime | None = None
    added_source: Literal["user", "grandfathered"] | None = None
    delisted: bool


class UniverseAddOut(BaseModel):
    """POST /api/tickers/{t}/universe. `changed` is false for an idempotent repeat or a protected ticker (no write).
    The add itself is durable even when the immediate compute fails (`score_computed` / `row_written` false + `error`)."""

    status: UniverseStatusOut
    changed: bool
    # Stock only (null for an ETF or when nothing was added): did a live compute_ticker_score run and produce a row.
    score_computed: bool | None = None
    # ETF only (null for a stock or when nothing was added): was the EtfScreenerRow written now.
    row_written: bool | None = None
    # Why a compute/write did not happen, e.g. "fundamentals_group_off", "daily_prices_group_off", "no_data", "failed".
    reason: str | None = None
    error: str | None = None
    # Not available: FMPClient keeps no per-request call counter.
    fmp_calls: int | None = None
    message: str


class UniverseRemoveOut(BaseModel):
    """DELETE /api/tickers/{t}/universe. `changed` is false when the ticker was not added (no-op)."""

    status: UniverseStatusOut
    changed: bool
    message: str
