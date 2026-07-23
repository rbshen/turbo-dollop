export type TickerTab = "summary" | "financials" | "companyMetrics" | "analysis" | "valuation" | "moat";

export interface TickerTabDef {
  key: TickerTab;
  label: string;
}

// Order here is the display order in the tab bar. Economic Moat is
// positioned after Valuation per spec.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "companyMetrics", label: "Company Metrics" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
