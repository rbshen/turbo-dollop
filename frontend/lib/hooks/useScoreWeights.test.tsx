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
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: { moat: null } }) }));
vi.mock("@/lib/hooks/useMoatConfig", () => ({ useMoatConfig: () => ({ data: { wide_moat_score: 100, narrow_moat_score: 65, no_moat_score: 0 } }) }));

function payload(
  overall: { financials: number; growth: number; profitability: number; debt: number },
  recompute: { state: string } | null = null,
): ScoreWeightsOut {
  return { weights: { overall, step1: {}, step2: {}, step4: {}, step5: {} }, moat_weight: 31, overall_total: 69, weights_version: 2, recompute } as unknown as ScoreWeightsOut;
}
const DEFAULT_OVERALL = { financials: 24, growth: 10, profitability: 20, debt: 15 };

beforeEach(() => {
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

  it("maps the payload to what the Overall blend needs, with Moat's locked percent from the endpoint", () => {
    expect(overallBlendWeights(payload({ financials: 17, growth: 17, profitability: 17, debt: 18 }))).toEqual({
      overall: { financials: 17, growth: 17, profitability: 17, debt: 18 },
      overallTotal: 69,
      moatWeight: 31,
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

  it("blends with the saved set: defaults give 76, a debt-heavy set gives 71", () => {
    h.weights = payload(DEFAULT_OVERALL);
    expect(renderHook(() => useOverallAssessment("AAPL")).result.current.score).toBe(76);
    h.weights = payload({ financials: 15, growth: 8, profitability: 16, debt: 30 });
    expect(renderHook(() => useOverallAssessment("AAPL")).result.current.score).toBe(71);
  });
});
