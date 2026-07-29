import { useApiResource } from "@/lib/hooks/useApiResource";
import type { WatchlistRowOut } from "@/lib/api/types";

export function useWatchlistRows(id: number) {
  return useApiResource<WatchlistRowOut[]>(`/watchlists/${id}/rows`);
}
