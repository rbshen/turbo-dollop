"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { TickerMoatOut } from "@/lib/api/types";

export function useTickerMoat(ticker: string) {
  return useSWR<TickerMoatOut>(`/tickers/${ticker}/moat`, (path: string) => apiFetch<TickerMoatOut>(path));
}
