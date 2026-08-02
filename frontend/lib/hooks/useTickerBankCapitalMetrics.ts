"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TickerBankCapitalMetricsOut } from "@/lib/api/types";

export function useTickerBankCapitalMetrics(ticker: string) {
  return useApiResource<TickerBankCapitalMetricsOut>(`/tickers/${ticker}/bank-capital-metrics`);
}
