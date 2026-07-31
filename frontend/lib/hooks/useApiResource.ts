"use client";

import useSWR, { type SWRResponse } from "swr";

import { apiFetch } from "@/lib/api/client";

/** Shared pattern behind every read-only stepN/ticker-resource hook in this
 * directory -- a GET against `url` with no SWR options (no polling, no
 * conditional key), returned as-is. Hooks with real extra behavior (write +
 * cache-invalidation, e.g. useSavedFilters) keep their own module instead.
 * `url: null` skips the fetch entirely (SWR's own conditional-key
 * convention) -- for a resource keyed off data that hasn't loaded yet, e.g.
 * useWatchlistRows before the active watchlist's id is known. */
export function useApiResource<T>(url: string | null): SWRResponse<T, Error> {
  return useSWR<T>(url, (path: string) => apiFetch<T>(path));
}
