"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TickerScoreOut } from "@/lib/api/types";

export function useTickerScore(ticker: string) {
  return useApiResource<TickerScoreOut | null>(`/tickers/${ticker}/score`);
}
