"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { TickerSummaryOut } from "@/lib/api/types";

export function useTickerSummary(ticker: string) {
  return useSWR<TickerSummaryOut>(`/tickers/${ticker}/summary`, (path: string) =>
    apiFetch<TickerSummaryOut>(path)
  );
}
