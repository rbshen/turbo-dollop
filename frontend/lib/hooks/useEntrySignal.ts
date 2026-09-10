"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TechnicalEntrySignalOut } from "@/lib/api/types";

// Per-ticker BB+RSI (2h) technical entry signal (see GET
// /api/tickers/{ticker}/entry-signal). Mirrors useTrendAnalysis's shape --
// a standalone endpoint/hook, not prop-drilled off TrendAnalysisOut, since
// this is a fully independent signal living in its own table. Resolves to
// null for any ticker on none of the W1-W5 named
// watchlists, or one not yet processed by the nightly job.
export function useEntrySignal(ticker: string) {
  return useApiResource<TechnicalEntrySignalOut | null>(`/tickers/${ticker}/entry-signal`);
}
