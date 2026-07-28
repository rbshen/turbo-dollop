"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { MoatScoreConfigOut } from "@/lib/api/types";

export function useMoatConfig() {
  return useApiResource<MoatScoreConfigOut>("/config/moat");
}
