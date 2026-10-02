"use client";

import useSWR, { mutate } from "swr";

import { apiDelete, apiFetch, apiPut } from "@/lib/api/client";
import type { SavedEtfFilter } from "@/lib/api/types";
import type { SaveViewBody } from "@/lib/hooks/useSavedFilters";
import type { EtfFilterState, EtfSortField } from "@/lib/etfScreenerFilters";

// The ETFs page's saved views are the same backend rows as the Stocks page's, told apart by `?kind=etf`. The SWR key is
// NOT the request path here (unlike the stock hook, whose key is "/screener/filters"): it must differ from the stock key
// and must not start with "/screener", which the stock mutations sweep. Names are unique per kind, so a stock view and
// an ETF view can share one.
export const SAVED_ETF_FILTERS_KEY = "/etf-screener/filters";
const PATH = "/screener/filters";
const KIND = "kind=etf";

// An ETF view has one universe, so the stock page's universe column is always "all".
export type SaveEtfFilterBody = SaveViewBody<"all", EtfSortField, EtfFilterState>;

export function useSavedEtfFilters() {
  return useSWR<SavedEtfFilter[]>(SAVED_ETF_FILTERS_KEY, () => apiFetch<SavedEtfFilter[]>(`${PATH}?${KIND}`));
}

export async function saveEtfFilter(name: string, body: SaveEtfFilterBody): Promise<SavedEtfFilter> {
  const result = await apiPut<SavedEtfFilter>(`${PATH}/${encodeURIComponent(name)}?${KIND}`, body);
  await mutate(SAVED_ETF_FILTERS_KEY);
  return result;
}

export async function deleteEtfFilter(name: string): Promise<void> {
  await apiDelete<void>(`${PATH}/${encodeURIComponent(name)}?${KIND}`);
  await mutate(SAVED_ETF_FILTERS_KEY);
}
