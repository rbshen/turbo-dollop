"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { DiscountRateConfigOut } from "@/lib/api/types";

export function useDiscountRateConfig() {
  return useApiResource<DiscountRateConfigOut>("/config/discount-rate");
}
