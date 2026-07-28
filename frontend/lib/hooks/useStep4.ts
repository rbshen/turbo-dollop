"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { Step4Out } from "@/lib/api/types";

export function useStep4(ticker: string) {
  return useApiResource<Step4Out>(`/tickers/${ticker}/step4`);
}
