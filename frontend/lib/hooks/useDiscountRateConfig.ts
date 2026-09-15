"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { DiscountRateConfigOut } from "@/lib/api/types";

export function useDiscountRateConfig() {
  return useApiResource<DiscountRateConfigOut>("/config/discount-rate");
}

// Every region seeded so far (see backend helpers/discount_rate_config.py::
// list_discount_rate_configs) -- backs the /settings "Discount Rate by
// Country" section, which supersedes the single-region form above.
export function useDiscountRateConfigs() {
  return useApiResource<DiscountRateConfigOut[]>("/config/discount-rates");
}
