// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isScoreKey, overallBlendWeights, RECOMPUTE_POLL_MS, useRecomputeStatus, useScoreWeights } from "@/lib/hooks/useScoreWeights";
import { useOverallAssessment } from "@/lib/hooks/useOverallAssessment";
import type { ScoreWeightsOut } from "@/lib/api/types";

const h = vi.hoisted(() => ({
  weights: undefined as unknown,
  swrCalls: [] as unknown[][],
  mutate: vi.fn(),
  moat: null as string | null,
  step: (score: number) => ({ data: { score, verdict: "Pass" }, error: undefined }),
}));

vi.mock("swr", () => ({
  default: (...args: unknown[]) => {
    h.swrCalls.push(args);
    return { data: h.weights };
  },
  mutate: (...args: unknown[]) => h.mutate(...args),
}));
vi.mock("@/lib/hooks/useStep1", () => ({ useStep1: () => h.step(90) }));
vi.mock("@/lib/hooks/useStep2", () => ({ useStep2: () => h.step(80) }));
vi.mock("@/lib/hooks/useStep4", () => ({ useStep4: () => h.step(70) }));
vi.mock("@/lib/hooks/useStep5", () => ({ useStep5: () => h.step(60) }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: { moat: h.moat } }) }));
vi.mock("@/lib/hooks/useMoatConfig", () => ({ useMoatConfig: () => ({ data: { wide_moat_multiplier: 1, narrow_moat_multiplier: 0.9, no_moat_multiplier: 0.7 } }) }));

function payload(
  overall: { financials: number; growth: number; profitability: number; debt: number },
  recompute: { state: string } | null = null,
): ScoreWeightsOut {
  return { weights: { overall, step1: {}, step2: {}, step4: {}, step5: {} }, overall_total: 100, weights_version: 2, formula_version: 2, recompute } as unknown as ScoreWeightsOut;
}
const DEFAULT_OVERALL = { financials: 30, growth: 20, profitability: 20, debt: 30 };

beforeEach(() => {
  h.moat = null;
  h.weights = undefined;
  h.swrCalls = [];
});
afterEach(() => vi.clearAllMocks());

describe("useScoreWeights", () => {
  it("reads the settings endpoint", () => {
    renderHook(() => useScoreWeights());
    expect(h.swrCalls[0][0]).toBe("/config/score-weights");
  });

  it("polls every 1.5 s while a recompute is running, and not otherwise", () => {
    renderHook(() => useScoreWeights());
    const { refreshInterval } = h.swrCalls[0][2] as { refreshInterval: (latest?: ScoreWeightsOut) => number };
    expect(refreshInterval(payload(DEFAULT_OVERALL, { state: "running" }))).toBe(RECOMPUTE_POLL_MS);
    expect(RECOMPUTE_POLL_MS).toBe(1500);
    expect(refreshInterval(payload(DEFAULT_OVERALL, { state: "done" }))).toBe(0);
    expect(refreshInterval(payload(DEFAULT_OVERALL, null))).toBe(0);
    expect(refreshInterval(undefined)).toBe(0);
  });

  it("maps the payload to what the Overall blend needs: the four weights and what they add up to (Moat is not a weight)", () => {
    expect(overallBlendWeights(payload({ financials: 25, growth: 25, profitability: 25, debt: 25 }))).toEqual({
      overall: { financials: 25, growth: 25, profitability: 25, debt: 25 },
      overallTotal: 100,
    });
  });
});

describe("isScoreKey", () => {
  it.each(["/screener?universe=all", "/screener/meta", "/tickers/AAPL/score", "/tickers/AAPL/step1", "/watchlists", "/watchlists/3/rows", "/momentum?period=current"])("matches %s", (key) => {
    expect(isScoreKey(key)).toBe(true);
  });
  it.each(["/config/score-weights", "/config/moat", "/etf-screener", ["/screener"], undefined])("does not match %j", (key) => {
    expect(isScoreKey(key)).toBe(false);
  });
});

describe("useRecomputeStatus", () => {
  it("revalidates every score-bearing key when a running recompute stops, and not before", () => {
    h.weights = payload(DEFAULT_OVERALL, { state: "running" });
    const { rerender } = renderHook(() => useRecomputeStatus());
    expect(h.mutate).not.toHaveBeenCalled();
    h.weights = payload(DEFAULT_OVERALL, { state: "done" });
    rerender();
    expect(h.mutate).toHaveBeenCalledTimes(1);
    expect(h.mutate.mock.calls[0][0]).toBe(isScoreKey);
    rerender();
    expect(h.mutate).toHaveBeenCalledTimes(1);
  });

  it("revalidates when the run fails too, and never for a run that was not running", () => {
    h.weights = payload(DEFAULT_OVERALL, { state: "done" });
    const { rerender } = renderHook(() => useRecomputeStatus());
    rerender();
    expect(h.mutate).not.toHaveBeenCalled();
    h.weights = payload(DEFAULT_OVERALL, { state: "running" });
    rerender();
    h.weights = payload(DEFAULT_OVERALL, { state: "failed" });
    rerender();
    expect(h.mutate).toHaveBeenCalledTimes(1);
  });
});

describe("useOverallAssessment reads the saved weights", () => {
  it("stays loading, with no score, until the weights have arrived", () => {
    const { result } = renderHook(() => useOverallAssessment("AAPL"));
    expect(result.current.status).toBe("loading");
    expect(result.current.score).toBeNull();
  });

  it("blends with the saved set: the defaults give a Fundamentals score of 75 (unrated: x0.70 = 52), a debt-heavy set 68.8 (48)", () => {
    h.weights = payload(DEFAULT_OVERALL);
    const defaults = renderHook(() => useOverallAssessment("AAPL")).result.current;
    expect([defaults.stepsScore, defaults.score, defaults.moatNote]).toEqual([75, 52, "Moat not rated, scored as No moat"]);
    h.weights = payload({ financials: 15, growth: 8, profitability: 27, debt: 50 });
    const debtHeavy = renderHook(() => useOverallAssessment("AAPL")).result.current;
    expect(debtHeavy.stepsScore).toBeCloseTo(68.8, 10);
    expect(debtHeavy.score).toBe(48);
  });

  it("applies the saved Narrow multiplier for a Narrow rating (0.9 here) and 1.0 for a Wide one", () => {
    h.weights = payload(DEFAULT_OVERALL);
    h.moat = "narrow_moat";
    expect(renderHook(() => useOverallAssessment("AAPL")).result.current).toMatchObject({ moatMultiplier: 0.9, score: 68, moatNote: null }); // 75 x 0.9 = 67.5 -> 68
    h.moat = "wide_moat";
    expect(renderHook(() => useOverallAssessment("AAPL")).result.current).toMatchObject({ moatMultiplier: 1, score: 75 });
  });
});
