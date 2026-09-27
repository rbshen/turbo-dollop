export type TickerTab =
  | "summary"
  | "financials"
  | "ratios"
  | "analysis"
  | "analystRatings"
  | "institutionalOwnership"
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
// independent, read-only lens layered on top of the core Steps 1-5/Overall
// Assessment scoring, rather than part of that blend. Chart sits right
// after it (per its own design spec: "next to Technical") -- a separate,
// also-independent OHLC/indicator view, not part of that blend either.
//
// Institutional Ownership sits right after Analyst Ratings -- the slot the
// original ask described as "after Analyst Ratings, before Economic Moat"
// no longer exists as written (Economic Moat already sits BEFORE Analyst
// Ratings in this list, not after), so this follows the unambiguous half
// of that instruction rather than guessing further.
export const TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
  { key: "analystRatings", label: "Analyst Ratings" },
  { key: "institutionalOwnership", label: "Institutional Ownership" },
  { key: "technical", label: "Technical" },
  { key: "chart", label: "Chart" },
];

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
