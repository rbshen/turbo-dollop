"use client";

import useSWR, { mutate } from "swr";

import { apiFetch, apiPut } from "@/lib/api/client";
import type { DataGroupUpdateIn, DataGroupsOut } from "@/lib/api/types";

const KEY = "/config/data-groups";
// Group state changes live (toggles, a 402 auto-detection, a re-probe) with no
// restart, so unlike the old restart-only FMP flag this polls gently.
const REFRESH_INTERVAL_MS = 60 * 1000;

export function useDataGroups() {
  return useSWR<DataGroupsOut>(KEY, (path: string) => apiFetch<DataGroupsOut>(path), {
    refreshInterval: REFRESH_INTERVAL_MS,
  });
}

async function put(path: string, body: unknown): Promise<DataGroupsOut> {
  const next = await apiPut<DataGroupsOut>(path, body);
  await mutate(KEY, next, { revalidate: false });
  return next;
}

export const setMaster = (master_on: boolean) => put(`${KEY}/master`, { master_on });
export const setFmpPlan = (fmp_plan: string) => put(`${KEY}/plan`, { fmp_plan });
export const updateGroup = (group: string, body: DataGroupUpdateIn) => put(`${KEY}/${group}`, body);
