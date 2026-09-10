"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { ChartOut, ChartRange } from "@/lib/api/types";

// Per-ticker OHLC + indicators for the Chart tab (see GET
// /api/tickers/{ticker}/chart). Fully on-demand -- unlike useTrendAnalysis/
// useEntrySignal/useLiquidityZones, there's no "never computed yet" null
// state here: every ticker gets a real (possibly chart_available: false)
// response, since this endpoint fetches fresh on every call rather than
// reading a nightly-precomputed row.
export function useTickerChart(ticker: string, range: ChartRange) {
  return useApiResource<ChartOut>(`/tickers/${ticker}/chart?range=${range}`);
}
