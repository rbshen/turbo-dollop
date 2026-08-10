import type { TickerSummaryOut } from "@/lib/api/types";

export type MetricFormat = "compactMoney" | "compactNumber" | "number" | "percent" | "ratio" | "text";

export interface MetricDef {
  key: keyof TickerSummaryOut;
  label: string;
  format: MetricFormat;
  /** Optional caveat icon+tooltip, shown only when `values[when]` is truthy
   * (see MetricsGrid.tsx). Distinct from the outlier-flag warning icon --
   * this is a methodology caveat, not a data-quality flag. */
  tooltip?: { when: keyof TickerSummaryOut; text: string };
}

export interface MetricGroup {
  title: string;
  /** Which of the Summary tab's two side-by-side tables this whole group
   * renders in -- groups are never split across both columns. */
  column: "left" | "right";
  metrics: MetricDef[];
}

/** Ticker header metrics grid, grouped by category -- each group is a
 * configurable list rather than a hardcoded set of tiles, so more metrics
 * can be added later without touching the grid component itself.
 *
 * Column assignment per user direction (overrides the design handoff's own
 * split): left = Classification, Size & Valuation, Growth; right =
 * Liquidity, Performance. */
export const METRIC_GROUPS: MetricGroup[] = [
  {
    title: "Classification",
    column: "left",
    metrics: [
      { key: "sector", label: "Sector", format: "text" },
      { key: "industry", label: "Industry", format: "text" },
    ],
  },
  {
    title: "Size & Valuation",
    column: "left",
    metrics: [
      { key: "market_cap", label: "Market Cap", format: "compactMoney" },
      { key: "enterprise_value", label: "Enterprise Value", format: "compactMoney" },
      { key: "pe_ratio", label: "P/E Ratio", format: "number" },
      { key: "peg_ratio", label: "PEG Ratio", format: "ratio" },
      { key: "forward_peg_ratio", label: "Forward PEG Ratio", format: "ratio" },
      { key: "dividend_yield", label: "Dividend Yield", format: "percent" },
    ],
  },
  {
    title: "Growth",
    column: "left",
    metrics: [
      { key: "eps_growth_3_5y", label: "EPS Growth (3-5Y)", format: "percent" },
      { key: "revenue_growth_yoy", label: "Revenue Growth (YoY)", format: "percent" },
      { key: "net_income_growth_yoy", label: "Net Income Growth (YoY)", format: "percent" },
    ],
  },
  {
    title: "Liquidity",
    column: "right",
    metrics: [
      { key: "beta", label: "Beta", format: "number" },
      { key: "shares_outstanding", label: "Shares Outstanding", format: "compactNumber" },
      { key: "avg_volume_30d", label: "30-Day Avg Volume", format: "compactNumber" },
      { key: "avg_dollar_volume_20d", label: "20-Day Avg $ Volume", format: "compactMoney" },
    ],
  },
  {
    title: "Performance",
    column: "right",
    metrics: [
      { key: "perf_1m", label: "1M Performance", format: "percent" },
      { key: "perf_6m", label: "6M Performance", format: "percent" },
      { key: "perf_ytd", label: "YTD Performance", format: "percent" },
      { key: "perf_1y", label: "1Y Performance", format: "percent" },
      { key: "perf_5y", label: "5Y Performance", format: "percent" },
      { key: "perf_10y", label: "10Y Performance", format: "percent" },
      {
        key: "perf_5y_vs_spy_pct",
        label: "5Y vs SPY",
        format: "percent",
        tooltip: {
          when: "perf_5y_insufficient_history",
          text: "Reflects return since listing, not a full 5-year window -- this ticker has under 5 years of trading history. The same limitation affects the 5Y/10Y Performance figures above.",
        },
      },
      { key: "week52_high", label: "52 Week High", format: "compactMoney" },
      { key: "week52_low", label: "52 Week Low", format: "compactMoney" },
    ],
  },
];

