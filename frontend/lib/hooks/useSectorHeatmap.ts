"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { SectorHeatmapOut } from "@/lib/api/types";

export function useSectorHeatmap() {
  return useApiResource<SectorHeatmapOut>("/sector-heatmap");
}
