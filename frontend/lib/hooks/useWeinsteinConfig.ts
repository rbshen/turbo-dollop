"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { WeinsteinConfigOut } from "@/lib/api/types";

export function useWeinsteinConfig() {
  return useApiResource<WeinsteinConfigOut>("/config/weinstein");
}
