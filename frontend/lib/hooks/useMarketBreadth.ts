"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { MarketBreadthOut } from "@/lib/api/types";

/** `universe` defaults to "sp500" (the existing /breadth page's own call, `useMarketBreadth()`, is
 * unaffected); pass a "sector:<ETF>" value for a sector, or `null` to skip the fetch entirely (the
 * conditional-fetch convention useWatchlistRows already uses) -- e.g. for an unrecognized sector param. */
export function useMarketBreadth(universe: string | null = "sp500") {
  return useApiResource<MarketBreadthOut>(universe ? `/market-breadth?universe=${universe}` : null);
}
