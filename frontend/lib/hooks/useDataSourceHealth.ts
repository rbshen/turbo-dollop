"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { DataSourceHealthOut } from "@/lib/api/types";

export function useDataSourceHealth() {
  return useApiResource<DataSourceHealthOut>("/config/data-source-health");
}
