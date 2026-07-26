"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { SegmentationOut } from "@/lib/api/types";

export function useSegmentation(ticker: string) {
  return useSWR<SegmentationOut>(`/tickers/${ticker}/segmentation`, (path: string) =>
    apiFetch<SegmentationOut>(path)
  );
}
