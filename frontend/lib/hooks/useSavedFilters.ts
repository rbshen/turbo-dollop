"use client";

import { mutate } from "swr";

import { apiDelete, apiPut } from "@/lib/api/client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import type { ScreenerFilterState, SortDirection, SortField } from "@/lib/screenerFilters";

const KEY = "/screener/filters";

// The body of a saved-view PUT, for either page (the ETFs page uses useSavedEtfFilters.ts).
export interface SaveViewBody<TUniverse extends string, TSort extends string, TFilters> {
  universe: TUniverse;
  sort_field: TSort;
  sort_direction: SortDirection;
  filters: TFilters;
  watchlist_id: number | null;
}

export type SaveScreenerFilterBody = SaveViewBody<ScreenerUniverse, SortField, ScreenerFilterState>;

export function useSavedFilters() {
  return useApiResource<SavedScreenerFilter[]>(KEY);
}

export async function saveScreenerFilter(name: string, body: SaveScreenerFilterBody): Promise<SavedScreenerFilter> {
  const result = await apiPut<SavedScreenerFilter>(`${KEY}/${encodeURIComponent(name)}`, body);
  await mutate(KEY);
  return result;
}

export async function deleteScreenerFilter(name: string): Promise<void> {
  await apiDelete<void>(`${KEY}/${encodeURIComponent(name)}`);
  await mutate(KEY);
}
