"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TrendAnalysisOut } from "@/lib/api/types";

// Per-ticker Weinstein stage analysis (see GET /api/tickers/{ticker}/trend-
// analysis). The "trend" name is historical: the swing/BOS trend-structure
// fields this endpoint once carried were removed, Weinstein is all that's left.
export function useTrendAnalysis(ticker: string) {
  return useApiResource<TrendAnalysisOut | null>(`/tickers/${ticker}/trend-analysis`);
}
