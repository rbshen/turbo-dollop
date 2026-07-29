"use client";

import { mutate } from "swr";

import { apiDelete, apiPost, apiPut } from "@/lib/api/client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { WatchlistOut, WatchlistSortField } from "@/lib/api/types";
import type { SortDirection } from "@/lib/screenerFilters";

const KEY = "/watchlists";

export interface UpdateWatchlistBody {
  name?: string;
  sort_field?: WatchlistSortField;
  sort_direction?: SortDirection;
}

export function useWatchlists() {
  return useApiResource<WatchlistOut[]>(KEY);
}

export async function createWatchlist(name: string): Promise<WatchlistOut> {
  const result = await apiPost<WatchlistOut>(KEY, { name });
  await mutate(KEY);
  return result;
}

export async function updateWatchlist(id: number, body: UpdateWatchlistBody): Promise<WatchlistOut> {
  const result = await apiPut<WatchlistOut>(`${KEY}/${id}`, body);
  await mutate(KEY);
  return result;
}

export async function deleteWatchlist(id: number): Promise<void> {
  await apiDelete<void>(`${KEY}/${id}`);
  await mutate(KEY);
}

export async function addTickerToWatchlist(id: number, ticker: string): Promise<void> {
  await apiPost(`${KEY}/${id}/tickers`, { ticker });
  await mutate(KEY);
}

export async function removeTickerFromWatchlist(id: number, ticker: string): Promise<void> {
  await apiDelete(`${KEY}/${id}/tickers/${encodeURIComponent(ticker)}`);
  await mutate(KEY);
}
