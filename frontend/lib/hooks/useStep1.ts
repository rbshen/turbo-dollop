"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { Step1Out } from "@/lib/api/types";

export function useStep1(ticker: string) {
  return useSWR<Step1Out>(`/tickers/${ticker}/step1`, (path: string) => apiFetch<Step1Out>(path));
}
