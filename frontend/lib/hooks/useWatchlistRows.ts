import { useApiResource } from "@/lib/hooks/useApiResource";
import type { WatchlistRowOut } from "@/lib/api/types";

export function useWatchlistRows(id: number | null) {
  return useApiResource<WatchlistRowOut[]>(id != null ? `/watchlists/${id}/rows` : null);
}
