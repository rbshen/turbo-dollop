"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { PeHistoryOut } from "@/lib/api/types";

export function usePeHistory(ticker: string) {
  return useApiResource<PeHistoryOut>(`/tickers/${ticker}/pe-history`);
}
