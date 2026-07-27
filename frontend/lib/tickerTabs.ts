export type TickerTab = "summary" | "financials" | "ratios" | "analysis" | "analystRatings" | "valuation" | "moat";

export interface TickerTabDef {
  key: TickerTab;
  label: string;
}

// Order here is the display order in the tab bar. Economic Moat is
// positioned after Valuation per spec. Analyst Ratings (external sell-side
// consensus, unrelated to Fathom's own Steps 1/2/4/5 scoring) sits right
// after Analysis.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "analysis", label: "Analysis" },
  { key: "analystRatings", label: "Analyst Ratings" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
