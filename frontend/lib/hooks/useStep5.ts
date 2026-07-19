"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { Step5Out } from "@/lib/api/types";

export function useStep5(ticker: string) {
  return useSWR<Step5Out>(`/tickers/${ticker}/step5`, (path: string) => apiFetch<Step5Out>(path));
}
