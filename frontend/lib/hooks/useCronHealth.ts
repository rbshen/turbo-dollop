"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { CronHealthOut } from "@/lib/api/types";

// Deliberately doesn't go through the shared useApiResource helper --
// its own docstring says a hook needing "real extra behavior" should keep
// its own module instead. Unlike the FMP flag (restart-only, no polling by
// design -- see useFmpStatus), cron health changes live every night with no
// backend restart, so this needs its own refreshInterval for the banner to
// pick up a new failure/overdue job without requiring a page reload.
const REFRESH_INTERVAL_MS = 5 * 60 * 1000;

export function useCronHealth() {
  return useSWR<CronHealthOut>("/config/cron-health", (path: string) => apiFetch<CronHealthOut>(path), {
    refreshInterval: REFRESH_INTERVAL_MS,
  });
}
