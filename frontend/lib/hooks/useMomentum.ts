"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { EtfMomentumOut, MomentumOut, MomentumPeriod } from "@/lib/api/types";

export function useMomentum(period: MomentumPeriod) {
  return useApiResource<MomentumOut>(`/momentum?period=${period}`);
}

export function useEtfMomentum(period: MomentumPeriod) {
  return useApiResource<EtfMomentumOut>(`/momentum/etf?period=${period}`);
}
