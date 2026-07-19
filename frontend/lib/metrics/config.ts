import type { TickerSummaryOut } from "@/lib/api/types";

export type MetricFormat = "compactMoney" | "number" | "percent";

export interface MetricDef {
  key: keyof TickerSummaryOut;
  label: string;
  format: MetricFormat;
}

/** Ticker header metrics grid — a configurable list rather than a hardcoded
 * set of tiles, so more metrics can be added later without touching the
 * grid component itself. */
export const DEFAULT_METRICS: MetricDef[] = [
  { key: "total_debt", label: "Debt (ST + LT)", format: "compactMoney" },
  { key: "ebitda_ttm", label: "EBITDA (TTM)", format: "compactMoney" },
  { key: "net_interest_expense_ttm", label: "Net Interest Expense (TTM)", format: "compactMoney" },
  { key: "market_cap", label: "Market Cap", format: "compactMoney" },
  { key: "beta", label: "Beta", format: "number" },
  { key: "perf_1m", label: "1M Performance", format: "percent" },
  { key: "perf_6m", label: "6M Performance", format: "percent" },
  { key: "eps_growth_3_5y", label: "EPS Growth (3-5Y)", format: "percent" },
  { key: "pe_ratio", label: "P/E Ratio", format: "number" },
];
