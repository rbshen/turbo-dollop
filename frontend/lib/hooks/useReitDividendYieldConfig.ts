"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { ReitDividendYieldConfigOut } from "@/lib/api/types";

export function useReitDividendYieldConfig() {
  return useApiResource<ReitDividendYieldConfigOut>("/config/reit-dividend-yield");
}
