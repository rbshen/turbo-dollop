"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { ScreenerMeta, ScreenerUniverse, TickerScoreOut } from "@/lib/api/types";

export function useScreener(universe: ScreenerUniverse) {
  return useApiResource<TickerScoreOut[]>(`/screener?universe=${universe}`);
}

export function useScreenerMeta(universe: ScreenerUniverse) {
  return useApiResource<ScreenerMeta>(`/screener/meta?universe=${universe}`);
}
