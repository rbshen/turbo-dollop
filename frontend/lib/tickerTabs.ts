export type TickerTab =
  | "summary"
  | "financials"
  | "ratios"
  | "analysis"
  | "analystRatings"
  | "valuation"
  | "moat"
  | "technical";

export interface TickerTabDef {
  key: TickerTab;
  label: string;
}

// Order here is the display order in the tab bar, per user direction:
// Summary, Financials, Ratios, Analysis, Valuation, Economic Moat,
// Analyst Ratings, Technical. Technical is last -- an independent,
// read-only lens layered on top of the core Steps 1-5/Overall Assessment
// scoring, rather than part of that blend.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
  { key: "analystRatings", label: "Analyst Ratings" },
  { key: "technical", label: "Technical" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
