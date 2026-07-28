"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { Step1Out } from "@/lib/api/types";

export function useStep1(ticker: string) {
  return useApiResource<Step1Out>(`/tickers/${ticker}/step1`);
}
