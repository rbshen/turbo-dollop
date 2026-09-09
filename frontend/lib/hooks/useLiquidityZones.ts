"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { LiquidityZonesOut } from "@/lib/api/types";

// Per-ticker Liquidity Zone (LP) detection, both timeframes bundled (see
// GET /api/tickers/{ticker}/liquidity-zones). Mirrors useEntrySignal's
// shape -- a standalone endpoint/hook, not prop-drilled off
// TrendAnalysisOut, since this is a fully independent lens living in its
// own table. Resolves to null for any ticker on neither the "Main" nor
// "Secondary" named watchlists, or one not yet processed by the nightly
// job.
export function useLiquidityZones(ticker: string) {
  return useApiResource<LiquidityZonesOut | null>(`/tickers/${ticker}/liquidity-zones`);
}
