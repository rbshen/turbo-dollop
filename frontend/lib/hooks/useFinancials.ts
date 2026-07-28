"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { FinancialsOut } from "@/lib/api/types";

export function useFinancials(ticker: string) {
  return useApiResource<FinancialsOut>(`/tickers/${ticker}/financials`);
}
