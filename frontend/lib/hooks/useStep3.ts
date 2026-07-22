"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { Step3Out } from "@/lib/api/types";

export interface Step3GrowthOverrides {
  growth_yr_1_5?: number;
  growth_yr_6_10?: number;
  growth_yr_11_20?: number;
}

function buildPath(ticker: string, overrides?: Step3GrowthOverrides): string {
  const params = new URLSearchParams();
  if (overrides?.growth_yr_1_5 != null) params.set("growth_yr_1_5", String(overrides.growth_yr_1_5));
  if (overrides?.growth_yr_6_10 != null) params.set("growth_yr_6_10", String(overrides.growth_yr_6_10));
  if (overrides?.growth_yr_11_20 != null) params.set("growth_yr_11_20", String(overrides.growth_yr_11_20));
  const qs = params.toString();
  return `/tickers/${ticker}/step3${qs ? `?${qs}` : ""}`;
}

// Re-fetches (recomputes, no new FMP calls) whenever `overrides` changes --
// the backend applies them to the already-cached inputs and reruns the calc
// engine, so the math stays in one place instead of being duplicated here.
export function useStep3(ticker: string, overrides?: Step3GrowthOverrides) {
  const path = buildPath(ticker, overrides);
  return useSWR<Step3Out>(path, (p: string) => apiFetch<Step3Out>(p));
}
