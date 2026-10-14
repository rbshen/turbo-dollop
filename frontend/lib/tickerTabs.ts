export type TickerTab =
  | "overview"
  | "summary"
  | "financials"
  | "ratios"
  | "analysis"
  | "analystRatings"
  | "valuation"
  | "moat"
  | "technical"
  | "chart";

export interface TickerTabDef {
  key: TickerTab;
  label: string;
}

// Order here is the display order in the tab bar, per user direction:
// Summary, Financials, Ratios, Analysis, Valuation, Economic Moat,
// Analyst Ratings, Technical, Chart. Technical is second-to-last -- an
// independent, read-only lens layered on top of the core Fundamentals 1-5/Overall
// Assessment scoring, rather than part of that blend. Chart sits right
// after it (per its own design spec: "next to Technical") -- a separate,
// also-independent OHLC/indicator view, not part of that blend either.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
  { key: "analystRatings", label: "Analyst Ratings" },
  { key: "technical", label: "Technical" },
  { key: "chart", label: "Chart" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";

// The ETF variant of the ticker page (docs/specs/etf-page.md): no Financials, Ratios, Analysis,
// Valuation, Moat or Analyst Ratings tab -- an ETF has none of that data.
export const ETF_TICKER_TABS: TickerTabDef[] = [
  { key: "overview", label: "Overview" },
  { key: "technical", label: "Technical" },
  { key: "chart", label: "Chart" },
];

export const DEFAULT_ETF_TICKER_TAB: TickerTab = "overview";
