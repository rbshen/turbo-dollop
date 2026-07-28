"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { Step2Out } from "@/lib/api/types";

export function useStep2(ticker: string) {
  return useApiResource<Step2Out>(`/tickers/${ticker}/step2`);
}
