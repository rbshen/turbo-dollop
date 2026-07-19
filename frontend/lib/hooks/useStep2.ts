"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { Step2Out } from "@/lib/api/types";

export function useStep2(ticker: string) {
  return useSWR<Step2Out>(`/tickers/${ticker}/step2`, (path: string) => apiFetch<Step2Out>(path));
}
