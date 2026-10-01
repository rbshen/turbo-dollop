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
// independent, read-only lens layered on top of the core Steps 1-5/Overall
// Assessment scoring, rather than part of that blend. Chart sits right
// after it (per its own design spec: "next to Technical") -- a separate,
// also-independent OHLC/indicator view, not part of that blend either.
//
// Institutional Ownership is shelved (2026-09-27, same reasoning as Insider
// Activity -- 13F's quarterly cadence and 45+ day reporting lag doesn't
// inform short-premium/short-term trading decisions) -- deliberately absent
// here and from TickerTabsContainer, with the backend gated off by the
// `institutional_ownership` FMP Data Group (default disabled). Its
// components (components/ticker/InstitutionalOwnershipTab.tsx, lib/hooks/
// useInstitutionalOwnership.ts) and all backend data/schema/route code are
// left in place, disconnected. To revive it: turn the `institutional_
// ownership` Data Group on in Settings > Status, re-add "institutionalOwnership"
// to the TickerTab union and an entry here (between Analyst Ratings and
// Technical), and the InstitutionalOwnershipTab branch in
// TickerTabsContainer.
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
