export type TickerTab =
  | "summary"
  | "financials"
  | "ratios"
  | "analysis"
  | "analystRatings"
  | "valuation"
  | "moat"
  | "newsSentiment";

export interface TickerTabDef {
  key: TickerTab;
  label: string;
}

// Order here is the display order in the tab bar, per user direction:
// Summary, Financials, Ratios, Analysis, Valuation, Economic Moat, Analyst
// Ratings, News & Sentiment.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
  { key: "analystRatings", label: "Analyst Ratings" },
  { key: "newsSentiment", label: "News & Sentiment" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
