"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { RatiosOut } from "@/lib/api/types";

export function useRatios(ticker: string) {
  return useApiResource<RatiosOut>(`/tickers/${ticker}/ratios`);
}
