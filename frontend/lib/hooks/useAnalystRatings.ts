"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { AnalystRatingsOut } from "@/lib/api/types";

export function useAnalystRatings(ticker: string) {
  return useApiResource<AnalystRatingsOut>(`/tickers/${ticker}/analyst-ratings`);
}
