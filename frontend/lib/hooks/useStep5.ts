"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { Step5Out } from "@/lib/api/types";

export function useStep5(ticker: string) {
  return useApiResource<Step5Out>(`/tickers/${ticker}/step5`);
}
