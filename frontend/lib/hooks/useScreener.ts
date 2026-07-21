"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { ScreenerMeta, TickerScoreOut } from "@/lib/api/types";

export function useScreener() {
  return useSWR<TickerScoreOut[]>("/screener", (path: string) => apiFetch<TickerScoreOut[]>(path));
}

export function useScreenerMeta() {
  return useSWR<ScreenerMeta>("/screener/meta", (path: string) => apiFetch<ScreenerMeta>(path));
}
