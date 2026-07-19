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
  growth_catalysts: string | null;
  score: number;
  verdict: string;
  components: Step2Components;
}
