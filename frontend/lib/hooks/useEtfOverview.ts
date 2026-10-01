"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { EtfOverviewOut } from "@/lib/api/types";

// FMP /etf/info for the ETF page (see GET /api/tickers/{ticker}/etf-overview). Shared by the Overview tab
// and the header (asset class) -- one SWR key, one request. Never errors for an FMP problem: an off group
// or a failed fetch arrives as status "unavailable".
export function useEtfOverview(ticker: string) {
  return useApiResource<EtfOverviewOut>(`/tickers/${ticker}/etf-overview`);
}
