"use client";

import useSWR from "swr";

import { apiFetch } from "@/lib/api/client";
import type { DiscountRateConfigOut } from "@/lib/api/types";

export function useDiscountRateConfig() {
  return useSWR<DiscountRateConfigOut>("/config/discount-rate", (path: string) => apiFetch<DiscountRateConfigOut>(path));
}
