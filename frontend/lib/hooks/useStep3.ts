"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { Step3Out } from "@/lib/api/types";

export function useStep3(ticker: string) {
  return useApiResource<Step3Out>(`/tickers/${ticker}/step3`);
}
