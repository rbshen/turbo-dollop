"use client";

import { mutate } from "swr";

import { apiDelete } from "@/lib/api/client";
import type { WarrenWatchOut } from "@/lib/api/types";
import { useApiResource } from "@/lib/hooks/useApiResource";

const KEY = "/technical-ideas/warren";

// The Warren watch table behind the Technical Ideas page: stored rows only, refreshed by the nightly job (no polling).
export function useWarrenWatch() {
  return useApiResource<WarrenWatchOut>(KEY);
}

// Admin only (the Remove control sits behind <AdminOnly>). A soft remove: the row stays in the table, hidden, until a newer arrow wakes it.
export async function removeWarrenWatchRow(ticker: string): Promise<void> {
  await apiDelete<unknown>(`${KEY}/${encodeURIComponent(ticker)}`);
  await mutate(KEY);
}
