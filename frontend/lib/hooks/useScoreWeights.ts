"use client";

import { useEffect, useRef } from "react";
import useSWR, { mutate } from "swr";

import { apiFetch } from "@/lib/api/client";
import type { RecomputeRunOut, ScoreWeightsOut } from "@/lib/api/types";
import type { OverallBlendWeights } from "@/lib/overallScore";

const KEY = "/config/score-weights";
/** How often the status is re-read while a recompute is running. */
export const RECOMPUTE_POLL_MS = 1500;

/** The saved score weights, their defaults, the locked Moat weight, the bounds and the latest recompute run. It re-reads itself every
 * 1.5 s while a recompute is running (every subscriber shares the one SWR entry), and not at all otherwise. */
export function useScoreWeights() {
  return useSWR<ScoreWeightsOut>(KEY, (path: string) => apiFetch<ScoreWeightsOut>(path), {
    refreshInterval: (latest) => (latest?.recompute?.state === "running" ? RECOMPUTE_POLL_MS : 0),
  });
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

/** Every SWR key whose payload carries a score or a step's weights: the Screener, the ticker pages' score and step reads, the
 * Watchlist rows and Momentum. Revalidated when a recompute finishes and right after weights are saved. */
export function isScoreKey(key: unknown): boolean {
  return (
    typeof key === "string" &&
    (key.startsWith("/screener") || key.startsWith("/tickers/") || key.startsWith("/watchlists") || key.startsWith("/momentum"))
  );
}

export function revalidateScores(): Promise<unknown> {
  return mutate(isScoreKey);
}

/** The latest recompute run, and whether one is running. When a run that was running stops (done or failed), every score-bearing
 * key is revalidated so open pages show the new numbers without a reload. */
export function useRecomputeStatus(): { run: RecomputeRunOut | null; running: boolean } {
  const { data } = useScoreWeights();
  const run = data?.recompute ?? null;
  const running = run?.state === "running";
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) void revalidateScores();
    wasRunning.current = running;
  }, [running]);
  return { run, running };
}

/** Re-reads the weights/status now (after a save that starts a recompute, so the polling begins at once). */
export function refreshScoreWeights(): Promise<unknown> {
  return mutate(KEY);
}
