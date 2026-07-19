export interface TickerSummaryOut {
  company_name: string | null;
  ticker: string;
  exchange: string | null;
  sector: string | null;
  industry: string | null;
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
  net_interest_expense_ttm: number | null;
  fair_value_price: number | null;
  fair_value_verdict: "undervalued" | "overvalued" | "fair" | null;
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
}

export interface Step1Out {
  ticker: string;
  years: string[];
  revenue: (number | null)[];
  net_income: (number | null)[];
  operating_income: (number | null)[];
  cfo: (number | null)[] | null;
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
  value: number;
  label: string;
  points: number;
}

export interface Step5Out {
  ticker: string;
  // "Standard" / "Bank" / "REIT/Property Developer" -- best-effort
  // sector/industry text match, not a certified determination.
  company_type: string;
  classification_note: string;
  ratios: Record<string, Step5RatioResult>;
  // Informational only (deferred-revenue exception) -- not auto-applied.
  deferred_revenue_current: number | null;
  // null for Bank (not yet supported) or when required data is missing.
  score: number | null;
  // "Fail" / "Pass" / "Strong Pass" for scored tickers; "not_supported" for
  // Bank; "insufficient_data" when required figures are missing.
  verdict: string;
  hard_fail: boolean;
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
}
