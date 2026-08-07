"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TickerCustomValuationOut } from "@/lib/api/types";

export function useTickerCustomValuation(ticker: string) {
  return useApiResource<TickerCustomValuationOut>(`/tickers/${ticker}/custom-valuation`);
}
