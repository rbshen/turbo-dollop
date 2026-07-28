"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TickerSummaryOut } from "@/lib/api/types";

export function useTickerSummary(ticker: string) {
  return useApiResource<TickerSummaryOut>(`/tickers/${ticker}/summary`);
}
