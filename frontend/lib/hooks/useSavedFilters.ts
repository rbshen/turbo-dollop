"use client";

import { mutate } from "swr";

import { apiDelete, apiPut } from "@/lib/api/client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { SavedScreenerFilter, ScreenerUniverse } from "@/lib/api/types";
import type { ScreenerFilterState, SortDirection, SortField } from "@/lib/screenerFilters";

const KEY = "/screener/filters";

export interface SaveScreenerFilterBody {
  universe: ScreenerUniverse;
  sort_field: SortField;
  sort_direction: SortDirection;
  filters: ScreenerFilterState;
}

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
