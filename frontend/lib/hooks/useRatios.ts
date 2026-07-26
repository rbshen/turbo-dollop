"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { RatiosOut } from "@/lib/api/types";

export function useRatios(ticker: string) {
  return useSWR<RatiosOut>(`/tickers/${ticker}/ratios`, (path: string) => apiFetch<RatiosOut>(path));
}
