"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { MomentumOut, MomentumPeriod } from "@/lib/api/types";

export function useMomentum(period: MomentumPeriod) {
  return useApiResource<MomentumOut>(`/momentum?period=${period}`);
}
