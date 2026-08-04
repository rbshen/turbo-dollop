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

// News & Sentiment is fully built (backend, caching, frontend -- see
// news_sentiment_data.py / NewsSentimentCache) but not being shipped yet;
// focus shifted to valuation/analysis work. Flip back to true to re-surface
// it in the tab bar -- nothing else needs to change. NewsSentimentTab.tsx
// and its "newsSentiment" case in TickerTabsContainer.tsx are left as-is
// either way, since TickerTab (the type) still includes "newsSentiment".
const NEWS_SENTIMENT_TAB_ENABLED = false;

// Order here is the display order in the tab bar, per user direction:
// Summary, Financials, Ratios, Analysis, Valuation, Economic Moat, Analyst
// Ratings, News & Sentiment.
const ALL_TICKER_TABS: TickerTabDef[] = [
  { key: "summary", label: "Summary" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "analysis", label: "Analysis" },
  { key: "valuation", label: "Valuation" },
  { key: "moat", label: "Economic Moat" },
  { key: "analystRatings", label: "Analyst Ratings" },
  { key: "newsSentiment", label: "News & Sentiment" },
];

export const TICKER_TABS: TickerTabDef[] = ALL_TICKER_TABS.filter(
  (t) => NEWS_SENTIMENT_TAB_ENABLED || t.key !== "newsSentiment"
);

export const DEFAULT_TICKER_TAB: TickerTab = "summary";
