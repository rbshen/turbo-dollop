"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { LiquidityZoneConfigOut } from "@/lib/api/types";

export function useLiquidityZoneConfig() {
  return useApiResource<LiquidityZoneConfigOut>("/config/liquidity-zones");
}
