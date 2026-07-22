export interface SecCrossCheck {
  available: boolean;
  sec_value: number | null;
  tag_used: string | null;
  matches_fmp: boolean | null;
  note: string;
}

export interface OutlierWarning {
  // Matches a TickerSummaryOut/MetricDef key (e.g. "interest_expense_ttm")
  // or a Step5 debt metric name (e.g. "cfo_ttm") -- never changes the
  // value, score, or verdict it's attached to, purely informational.
  metric: string;
  date: string | null;
  value: number;
  trailing_median: number;
  // Only populated for Step 5's own two Debt Servicing Ratio inputs
  // (net_interest_expense_ttm, cfo_ttm) -- null everywhere else, including
  // the ticker header's copy of the same warning list.
  sec_cross_check: SecCrossCheck | null;
}

export interface RefreshResult {
  ticker: string;
  cleared_entries: number;
  statement_types: string[];
}

export interface TickerSummaryOut {
  company_name: string | null;
  ticker: string;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
  description: string | null;
  price: number | null;
  change: number | null;
  change_percent: number | null;
  market_cap: number | null;
  beta: number | null;
  perf_1m: number | null;
  perf_6m: number | null;
  eps_growth_3_5y: number | null;
  pe_ratio: number | null;
  next_earnings_date: string | null;
  // Same figures Step 5's debt ratios are built from (backend/debt_metrics.py)
  // -- latest-quarter snapshot for total_debt, TTM for the other two. Shown
  // for every company type, including Bank/REIT.
  total_debt: number | null;
  ebitda_ttm: number | null;
  // Gross figures, not netted against each other.
  interest_expense_ttm: number | null;
  interest_income_ttm: number | null;
  outlier_warnings: OutlierWarning[];
  fair_value_price: number | null;
  fair_value_verdict: "undervalued" | "overvalued" | "fair" | null;
  // e.g. "DCF" / "DFCF" / "DNI" / "DNI (Normalized)" / "P/B" / "PSG" -- null
  // when Step 3 selected PASS (no valuation method applies).
  fair_value_method: string | null;
}

export interface Step1TrendComponent {
  score: number;
  pattern: string;
}

export interface Step1NetIncomeComponent extends Step1TrendComponent {
  used_operating_income_backup: boolean;
}

export interface Step1Components {
  revenue: Step1TrendComponent;
  net_income: Step1NetIncomeComponent;
  cfo: Step1TrendComponent | null;
  margins: Step1TrendComponent;
  // null whenever cfo is null -- FCF is derived from CFO, exempt under the
  // exact same conditions.
  fcf: Step1TrendComponent | null;
}

export interface Step1Out {
  ticker: string;
  years: string[];
  revenue: (number | null)[];
  // "Revenue" for every company type except Bank, where it's "Net Interest
  // Income" -- always shown alongside this field, never silently swapped
  // under the old label.
  revenue_label: string;
  net_income: (number | null)[];
  operating_income: (number | null)[];
  cfo: (number | null)[] | null;
  // FCF = CFO - CapEx. null (the whole field) whenever cfo is null -- same
  // exemption as CFO, since FCF is derived from it. Table/score only, not
  // part of the Financials Trend chart.
  fcf: (number | null)[] | null;
  gross_margin: (number | null)[];
  net_margin: (number | null)[];
  cfo_exempt_reason: string | null;
  net_income_one_off: boolean;
  cfo_one_off: boolean;
  score: number;
  verdict: string;
  components: Step1Components;
}

export interface Step2EstimateRow {
  fiscal_year: string;
  growth_avg: number;
  growth_high: number;
  growth_low: number;
}

export interface Step2Components {
  magnitude: { score: number; growth_rate?: number };
  agreement: { score: number; spread?: number };
  insufficient_data?: boolean;
}

export interface Step2Out {
  ticker: string;
  // Which FMP metric the projection is based on -- revenue preferred, EPS
  // as a fallback (see CLAUDE.md's "Scoring rubric deviations").
  basis: "revenue" | "eps" | null;
  estimates: Step2EstimateRow[];
  base_fiscal_year: string | null;
  target_fiscal_year: string | null;
  growth_rate: number | null;
  // High/low spread as a % of the average estimate -- "analyst estimate
  // range", not cross-platform "source consensus".
  estimate_spread: number | null;
  // Informational only -- how many analysts the target year's spread is
  // built on; doesn't affect the score.
  target_analyst_count: number | null;
  growth_catalysts: string | null;
  score: number;
  verdict: string;
  components: Step2Components;
}

export interface Step5RatioResult {
  // null only for interest_coverage_ratio when interest expense is
  // missing/non-positive.
  value: number | null;
  // Current Ratio only: the deferred-revenue-adjusted value, once the raw
  // ratio itself isn't already comfortable.
  adjusted_value: number | null;
  label: string;
  points: number;
  // True when a Borderline breach was excused by its tiebreaker.
  saved_by_tiebreaker: boolean;
}

export interface Step5Out {
  ticker: string;
  // "Standard" / "Bank" / "REIT/Property Developer" -- best-effort
  // sector/industry text match, not a certified determination.
  company_type: string;
  classification_note: string;
  ratios: Record<string, Step5RatioResult>;
  // Now wired into the Current Ratio verdict itself (see
  // ratios.current_ratio.adjusted_value) -- kept for display/context.
  deferred_revenue_current: number | null;
  // null for Bank (not yet supported) or when required data is missing.
  score: number | null;
  // "Fail" / "Pass" / "Strong Pass" / "Pass with caution" for scored
  // tickers; "not_supported" for Bank; "insufficient_data" when required
  // figures are missing.
  verdict: string;
  hard_fail: boolean;
  // True whenever verdict === "Pass with caution".
  pass_with_caution: boolean;
  outlier_warnings: OutlierWarning[];
}

export interface Step4RatioComponent {
  label: string;
  points: number;
}

export interface Step4CccComponent {
  pattern: string;
  points: number;
}

export interface Step4Components {
  roe: Step4RatioComponent;
  roic: Step4RatioComponent | null;
  revenue_vs_ar: Step4RatioComponent;
  ccc: Step4CccComponent | null;
}

export interface Step4Out {
  // years/roe/roic/revenue/accounts_receivable/ccc AND
  // score/verdict/hard_fail/components all share the same 10yr+TTM window,
  // matching Step 1 -- a deliberate deviation beyond the source doc's
  // explicit "5 years" (see CLAUDE.md's Step 4 deviations). There used to
  // be a narrower 5yr+TTM scoring window decoupled from a wider display
  // window; that decoupling has been removed.
  ticker: string;
  years: string[];
  // "Standard" / "Bank" / "Insurance" / "Utility" / "REIT/Property
  // Developer" -- shared classifier with Step 5.
  company_type: string;
  classification_note: string;
  roe: (number | null)[];
  // null (the whole field) when ROIC is exempt (Bank / Insurance / Utility).
  roic: (number | null)[] | null;
  roic_exempt_reason: string | null;
  revenue: (number | null)[];
  accounts_receivable: (number | null)[];
  // null (the whole field) when no physical inventory was detected.
  ccc: (number | null)[] | null;
  ccc_exempt_reason: string | null;
  // null when required raw data is missing.
  score: number | null;
  // "Fail" / "Pass" / "Strong Pass" for scored tickers; "insufficient_data"
  // when required figures are missing.
  verdict: string;
  hard_fail: boolean;
  components: Step4Components;
  // Informational only -- never changes score/verdict. Present when ROE is
  // "excellent"/"good" while ROIC is "marginal".
  roe_roic_divergence_note: string | null;
}

export interface TickerScoreOut {
  ticker: string;
  company_name: string | null;
  sector: string | null;
  industry: string | null;
  company_type: string | null;
  step1_score: number | null;
  step1_verdict: string | null;
  step2_score: number | null;
  step2_verdict: string | null;
  step4_score: number | null;
  step4_verdict: string | null;
  step5_score: number | null;
  step5_verdict: string | null;
  // null (along with overall_verdict) when any non-exempt step is missing --
  // a ticker can have a row here without a full Overall Assessment.
  overall_score: number | null;
  overall_verdict: string | null;
  market_cap: number | null;
  pe_ratio: number | null;
  beta: number | null;
  computed_at: string;
}

export interface ScreenerMeta {
  // Total stored S&P 500 constituents -- not the same as the length of
  // GET /api/screener's response, since a ticker with no cached profile at
  // all (e.g. an FMP 402) gets no TickerScoreOut row at all.
  total_sp500_constituents: number;
}

export interface RecomputeSummary {
  processed: number;
  failed: number;
  duration_seconds: number;
  failures: [string, string][];
}

export interface FinancialsLineItem {
  label: string;
  values: (number | null)[];
  // "money" | "per_share" -- which formatter to use (fmtTableMoney vs fmtNumber).
  unit: string;
  // Bold/subtotal row (e.g. "Total Assets").
  emphasis: boolean;
}

export interface FinancialsGroup {
  // null renders with no group header (Income Statement's flat list).
  label: string | null;
  items: FinancialsLineItem[];
}

export interface FinancialsPeriodOut {
  periods: string[];
  groups: FinancialsGroup[];
}

export interface FinancialsStatementOut {
  annual: FinancialsPeriodOut;
  quarterly: FinancialsPeriodOut;
}

export interface FinancialsOut {
  ticker: string;
  income_statement: FinancialsStatementOut;
  balance_sheet: FinancialsStatementOut;
  cash_flow: FinancialsStatementOut;
}

export type Step3Method = "DCF" | "DFCF" | "DNI" | "DNI_NORMALIZED" | "PRICE_TO_BOOK" | "PSG" | "PASS";

export interface Step3MethodStep {
  step: string;
  check: string;
  // null when the check couldn't run at all (missing data), distinct from
  // a real false.
  passed: boolean | null;
  detail: string;
}

export interface Step3CapmComponents {
  risk_free_rate: number;
  market_risk_premium: number;
  beta: number;
  // True when beta < 0.8 -- outside the workbook's own manual reference
  // table range. CAPM is still applied directly, not floored.
  beta_outside_reference_range: boolean;
}

export interface Step3Inputs {
  current_value: number | null;
  current_value_label: string | null;
  total_debt: number | null;
  cash_and_st_investments: number | null;
  // False when only cashAndCashEquivalents was available. True does NOT
  // mean equity securities are excluded -- FMP has no equity-vs-debt split
  // within short-term investments, so this toggle is "cash only" vs "cash +
  // all short-term investments" (undifferentiated), not a true
  // equity-holdings exclusion.
  cash_and_st_investments_includes_short_term_investments: boolean;
  growth_yr_1_5: number | null;
  growth_yr_6_10: number | null;
  growth_yr_11_20: number;
  growth_yr_1_5_source: string | null;
  shares_outstanding: number | null;
  shares_outstanding_source: string | null;
  discount_rate: number | null;
  capm: Step3CapmComponents | null;
  current_fiscal_year: string | null;
  fx_rate: number;
  last_close: number | null;
  // Price-to-Book inputs.
  book_value_per_share: number | null;
  historical_pb_ratios: number[] | null;
  pb_lookback: string | null;
  // PSG inputs.
  sales_per_share: number | null;
  projected_growth_rate: number | null;
  fair_psg_ratio: number | null;
}

export interface Step3PBBands {
  minus_2sd: number;
  minus_1sd: number;
  mean: number;
  plus_1sd: number;
  plus_2sd: number;
}

export interface DiscountRateConfigOut {
  region: string;
  // Decimal fractions (e.g. 0.03608 for 3.608%), 5-year trailing averages
  // per step6_intrinsic_value_calculation_prompt.md §5 -- manually
  // maintained, not auto-fetched. See /settings.
  risk_free_rate: number;
  market_risk_premium: number;
  updated_at: string;
}

export interface Step3Out {
  ticker: string;
  company_type: string;
  classification_note: string;
  selected_method: Step3Method;
  method_reasoning: Step3MethodStep[];
  // Set only when selected_method === "PASS".
  pass_reason: string | null;
  inputs: Step3Inputs;
  intrinsic_value_per_share: number | null;
  pb_bands: Step3PBBands | null;
  discount_premium_pct: number | null;
  verdict: "undervalued" | "overvalued" | "fair" | null;
}
