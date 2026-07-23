"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { MoatScoreConfigOut } from "@/lib/api/types";

export function useMoatConfig() {
  return useSWR<MoatScoreConfigOut>("/config/moat", (path: string) => apiFetch<MoatScoreConfigOut>(path));
}
