"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { OpportunityDateOut, OpportunityRunOut } from "@/lib/api/types";

/** Every stored run, newest first (the snapshot date picker). */
export function useOpportunityDates() {
  return useApiResource<OpportunityDateOut[]>("/opportunities/dates");
}

/** One stored run: the latest when `asOf` is null, else that date's. Read-only; there is no mutating call. */
export function useOpportunityRun(asOf: string | null) {
  return useApiResource<OpportunityRunOut>(asOf ? `/opportunities/${asOf}` : "/opportunities/latest");
}
