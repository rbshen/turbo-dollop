"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { SegmentationOut } from "@/lib/api/types";

export function useSegmentation(ticker: string) {
  return useApiResource<SegmentationOut>(`/tickers/${ticker}/segmentation`);
}
