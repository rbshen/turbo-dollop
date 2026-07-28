"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TickerMoatOut } from "@/lib/api/types";

export function useTickerMoat(ticker: string) {
  return useApiResource<TickerMoatOut>(`/tickers/${ticker}/moat`);
}
