"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { FinancialsOut } from "@/lib/api/types";

export function useFinancials(ticker: string) {
  return useSWR<FinancialsOut>(`/tickers/${ticker}/financials`, (path: string) => apiFetch<FinancialsOut>(path));
}
