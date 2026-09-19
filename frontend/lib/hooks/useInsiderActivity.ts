"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { InsiderActivityOut } from "@/lib/api/types";

export function useInsiderActivity(ticker: string) {
  return useApiResource<InsiderActivityOut>(`/tickers/${ticker}/insider-activity`);
}
