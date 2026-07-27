"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { AnalystRatingsOut } from "@/lib/api/types";

export function useAnalystRatings(ticker: string) {
  return useSWR<AnalystRatingsOut>(`/tickers/${ticker}/analyst-ratings`, (path: string) => apiFetch<AnalystRatingsOut>(path));
}
