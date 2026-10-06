"use client";

import { useApiResource } from "@/lib/hooks/useApiResource";
import type { ScoreWeightsOut } from "@/lib/api/types";
import type { OverallBlendWeights } from "@/lib/overallScore";

/** The saved score weights, their defaults, the locked Moat weight, the bounds and the latest recompute run. */
export function useScoreWeights() {
  return useApiResource<ScoreWeightsOut>("/config/score-weights");
}

/** What the Overall blend needs from the payload (the four step weights, what they add up to, Moat's locked percent). */
export function overallBlendWeights(data: ScoreWeightsOut): OverallBlendWeights {
  return {
    overall: {
      financials: data.weights.overall.financials,
      growth: data.weights.overall.growth,
      profitability: data.weights.overall.profitability,
      debt: data.weights.overall.debt,
    },
    overallTotal: data.overall_total,
    moatWeight: data.moat_weight,
  };
}
