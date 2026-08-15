"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { FmpStatusOut } from "@/lib/api/types";

export function useFmpStatus() {
  return useApiResource<FmpStatusOut>("/config/fmp-status");
}
