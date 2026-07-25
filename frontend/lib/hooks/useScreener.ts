"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { ScreenerMeta, ScreenerUniverse, TickerScoreOut } from "@/lib/api/types";

export function useScreener(universe: ScreenerUniverse) {
  return useSWR<TickerScoreOut[]>(`/screener?universe=${universe}`, (path: string) => apiFetch<TickerScoreOut[]>(path));
}

export function useScreenerMeta(universe: ScreenerUniverse) {
  return useSWR<ScreenerMeta>(`/screener/meta?universe=${universe}`, (path: string) => apiFetch<ScreenerMeta>(path));
}
