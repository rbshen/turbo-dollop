export type TickerTab = "summary" | "financials" | "companyMetrics" | "analysis" | "valuation";

export interface TickerTabDef {
  key: TickerTab;
  label: string;
}

// Order here is the display order in the tab bar.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "companyMetrics", label: "Company Metrics" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
