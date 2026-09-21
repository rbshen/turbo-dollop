"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { MarketBreadthOut } from "@/lib/api/types";

export function useMarketBreadth() {
  return useApiResource<MarketBreadthOut>("/market-breadth");
}
