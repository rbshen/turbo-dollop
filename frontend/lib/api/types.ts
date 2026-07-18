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
