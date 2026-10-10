"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { DashboardOut } from "@/lib/api/types";

/** The Dashboard tab's step blocks, fair value and stage series. Cache only on the server (no FMP call). The key starts with
 * `/tickers/{ticker}`, so Refresh and the Moat save revalidate it with the rest of the page. */
export function useDashboard(ticker: string) {
  return useApiResource<DashboardOut>(`/tickers/${ticker}/dashboard`);
}
