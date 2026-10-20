"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { OpportunityDateOut, OpportunityRunOut, ScorecardFlagsOut, ScorecardOut, ScorecardPicksOut } from "@/lib/api/types";

/** Every stored run, newest first (the snapshot date picker). */
export function useOpportunityDates(enabled = true) {
  return useApiResource<OpportunityDateOut[]>(enabled ? "/opportunities/dates" : null);
}

/** One stored run: the latest when `asOf` is null, else that date's. Read-only; there is no mutating call. */
export function useOpportunityRun(asOf: string | null, enabled = true) {
  return useApiResource<OpportunityRunOut>(enabled ? (asOf ? `/opportunities/${asOf}` : "/opportunities/latest") : null);
}

export interface ScorecardFilters {
  rulesVersion: string | null;
  triggersVersion: string | null;
  weightsVersion: number | null;
}

function scorecardQuery(f: ScorecardFilters, withTriggers: boolean): string {
  const q = new URLSearchParams();
  if (f.rulesVersion) q.set("rules_version", f.rulesVersion);
  if (withTriggers && f.triggersVersion) q.set("triggers_version", f.triggersVersion);
  if (withTriggers && f.weightsVersion != null) q.set("weights_version", String(f.weightsVersion));
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** The Scorecard's groups (all four horizons and both benchmarks in one response). `enabled` false skips the request. Read-only. */
export function useScorecard(f: ScorecardFilters, enabled = true) {
  return useApiResource<ScorecardOut>(enabled ? `/opportunities/scorecard${scorecardQuery(f, true)}` : null);
}

export function useScorecardFlags(f: ScorecardFilters, enabled = true) {
  return useApiResource<ScorecardFlagsOut>(enabled ? `/opportunities/scorecard/flags${scorecardQuery(f, true)}` : null);
}

export function useScorecardPicks(f: ScorecardFilters, enabled = true) {
  return useApiResource<ScorecardPicksOut>(enabled ? `/opportunities/scorecard/picks${scorecardQuery(f, false)}` : null);
}
