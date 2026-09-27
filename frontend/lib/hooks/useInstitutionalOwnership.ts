"use client";
import { useApiResource } from "@/lib/hooks/useApiResource";
import type { InstitutionalOwnershipOut } from "@/lib/api/types";

// Per-ticker Institutional Ownership tab (see GET
// /api/tickers/{ticker}/institutional-ownership). Always resolves to a real
// object (never null) -- the four states (group disabled / no coverage /
// plausibility-degraded / normal) are represented as fields on
// InstitutionalOwnershipOut itself, not by the whole response being absent.
//
// Shelved, not deleted (2026-09-27) -- see data/institutional_ownership_data.py's
// top-of-file comment. Unused by any component in the tree right now, kept
// for the revival path.
export function useInstitutionalOwnership(ticker: string) {
  return useApiResource<InstitutionalOwnershipOut>(`/tickers/${ticker}/institutional-ownership`);
}
