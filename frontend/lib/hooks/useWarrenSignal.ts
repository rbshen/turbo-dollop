"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { TechnicalEntrySignalOut } from "@/lib/api/types";

// Warren RSI/ADX/WVF (2h) technical entry signal -- the same endpoint
// useEntrySignal calls, with signal_type=warren so it reads the "warren"
// row instead of the default "bb_rsi" one (see GET
// /api/tickers/{ticker}/entry-signal). Resolves to null for any ticker on
// none of the W1-W5 named watchlists, or one not yet processed by
// pipeline.nightly_warren_signal_calculation.
export function useWarrenSignal(ticker: string) {
  return useApiResource<TechnicalEntrySignalOut | null>(`/tickers/${ticker}/entry-signal?signal_type=warren`);
}
