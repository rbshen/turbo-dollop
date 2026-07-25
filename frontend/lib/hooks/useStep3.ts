"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { Step3Out } from "@/lib/api/types";

export function useStep3(ticker: string) {
  return useSWR<Step3Out>(`/tickers/${ticker}/step3`, (p: string) => apiFetch<Step3Out>(p));
}
