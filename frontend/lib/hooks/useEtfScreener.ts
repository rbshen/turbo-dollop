"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { EtfScreenerMeta, EtfScreenerRowOut } from "@/lib/api/types";

// SWR keys (= the request path) deliberately do NOT start with "/screener": the Moat / Valuation / Bank-capital
// `mutate("/screener")` calls and the Stocks Recompute button's `startsWith("/screener")` sweep must never refresh
// ETF data. The ETFs page's saved-views key lives in useSavedEtfFilters.ts, for the same reason.
export const ETF_SCREENER_KEY = "/etf-screener";
export const ETF_SCREENER_META_KEY = "/etf-screener/meta";

export function useEtfScreener() {
  return useApiResource<EtfScreenerRowOut[]>(ETF_SCREENER_KEY);
}

export function useEtfScreenerMeta() {
  return useApiResource<EtfScreenerMeta>(ETF_SCREENER_META_KEY);
}
