"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { SpeculativeGrowthOut } from "@/lib/api/types";

export function useSpeculativeGrowth(ticker: string) {
  return useApiResource<SpeculativeGrowthOut>(`/tickers/${ticker}/speculative-growth`);
}
