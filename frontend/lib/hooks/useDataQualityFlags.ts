"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { DataQualityFlagOut, DataQualityFlagsOut, DataQualityScope } from "@/lib/api/types";

/** Settings > Data quality: the open flags of one scope. The list changes once a night (and on "Mark reviewed", which revalidates it). */
export function useDataQualityFlags(scope: DataQualityScope) {
  return useSWR<DataQualityFlagsOut>(`/data-quality/flags?scope=${scope}`, (path: string) => apiFetch<DataQualityFlagsOut>(path));
}

/** One ticker's open, un-reviewed flags for the Financials-tab note. A read of the stored table: no FMP call. */
export function useTickerDataQuality(ticker: string) {
  return useSWR<DataQualityFlagOut[]>(`/tickers/${ticker}/data-quality`, (path: string) => apiFetch<DataQualityFlagOut[]>(path));
}
