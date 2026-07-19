"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { Step4Out } from "@/lib/api/types";

export function useStep4(ticker: string) {
  return useSWR<Step4Out>(`/tickers/${ticker}/step4`, (path: string) => apiFetch<Step4Out>(path));
}
