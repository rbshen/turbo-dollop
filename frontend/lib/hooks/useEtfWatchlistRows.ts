import { useApiResource } from "@/lib/hooks/useApiResource";
import type { EtfWatchlistRow } from "@/lib/api/types";

/** The ETF table's rows (GET /api/watchlists/{id}/etf-rows, only the list named "ETF"). `null` skips the fetch, so the
 * page asks for it only while that list is active. Key `/watchlists/{id}/etf-rows`: refreshed by every watchlist
 * mutation in useWatchlists.ts (see mutateWatchlistRows) and by any `/watchlists` prefix sweep. */
export function useEtfWatchlistRows(id: number | null) {
  return useApiResource<EtfWatchlistRow[]>(id != null ? `/watchlists/${id}/etf-rows` : null);
}
