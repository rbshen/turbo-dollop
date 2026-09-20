export type TickerTab =
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
// independent, read-only lens layered on top of the core Steps 1-5/Overall
// Assessment scoring, rather than part of that blend. Chart sits right
// after it (per its own design spec: "next to Technical") -- a separate,
// also-independent OHLC/indicator view, not part of that blend either.
//
// Insider Activity is shelved (2026-09-20) -- deliberately absent here and
// from TickerTabsContainer, with the backend gated off by
// INSIDER_ACTIVITY_ENABLED. Its components (components/ticker/
// InsiderActivityTab.tsx, components/insiderActivity/, lib/insiderActivity.ts,
// lib/hooks/useInsiderActivity.ts) are left in place, disconnected. To revive
// it: re-add "insiderActivity" to the TickerTab union and an entry here
// (between Analyst Ratings and Technical), and the InsiderActivityTab branch
// in TickerTabsContainer.
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
