"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { StuckCheckOut } from "@/lib/api/types";

/** The "Why might it be stuck?" card. Cache only on the server: no FMP call, so no polling or revalidate options. */
export function useStuckCheck(ticker: string) {
  return useApiResource<StuckCheckOut>(`/tickers/${ticker}/stuck-check`);
}
