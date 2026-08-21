"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TrendAnalysisOut } from "@/lib/api/types";

// Per-ticker trend-structure analysis (see GET /api/tickers/{ticker}/trend-
// analysis). Mirrors useSpeculativeGrowth's shape -- for a future ticker-page
// "Technical" tab (not built this round), not the Watchlist table, which
// reads bar_level/blended_score/trend_state from the bulk
// /watchlists/{id}/rows response instead (see WatchlistTable.tsx) to avoid
// firing one extra request per row per column.
export function useTrendAnalysis(ticker: string) {
  return useApiResource<TrendAnalysisOut | null>(`/tickers/${ticker}/trend-analysis`);
}
