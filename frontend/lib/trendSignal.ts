// TREND column color mapping for the Watchlist's 5-bar SignalBars indicator
// (see components/watchlist/WatchlistTable.tsx). Unlike Moat/Value/vs-SPY
// (a 3-state enum mapped through its own *_SIGNAL_LEVEL table, see
// MoatPill.tsx/FairValuePill.tsx), bar_level here is already a 1-5 integer
// computed backend-only (analysis/trend_structure/conviction.py) -- so this
// is a direct level -> color lookup, no separate *_SIGNAL_LEVEL map needed.
// Red (1) -> muted/neutral (2-3) -> green (4) -> dark green (5), reusing the
// same 5 color tokens tierColor.ts already draws on.
export const TREND_SIGNAL_COLOR: Record<1 | 2 | 3 | 4 | 5, string> = {
  1: "bg-negative",
  2: "bg-caution",
  3: "bg-warn",
  4: "bg-positive",
  5: "bg-positive-strong",
};
