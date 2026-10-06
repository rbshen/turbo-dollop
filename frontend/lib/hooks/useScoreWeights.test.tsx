// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { overallBlendWeights, useScoreWeights } from "@/lib/hooks/useScoreWeights";
import { useOverallAssessment } from "@/lib/hooks/useOverallAssessment";
import type { ScoreWeightsOut } from "@/lib/api/types";

const h = vi.hoisted(() => ({
  weights: undefined as unknown,
  step: (score: number) => ({ data: { score, verdict: "Pass" }, error: undefined }),
}));

vi.mock("@/lib/hooks/useApiResource", () => ({ useApiResource: vi.fn(() => ({ data: h.weights })) }));
vi.mock("@/lib/hooks/useStep1", () => ({ useStep1: () => h.step(90) }));
vi.mock("@/lib/hooks/useStep2", () => ({ useStep2: () => h.step(80) }));
vi.mock("@/lib/hooks/useStep4", () => ({ useStep4: () => h.step(70) }));
vi.mock("@/lib/hooks/useStep5", () => ({ useStep5: () => h.step(60) }));
vi.mock("@/lib/hooks/useTickerMoat", () => ({ useTickerMoat: () => ({ data: { moat: null } }) }));
vi.mock("@/lib/hooks/useMoatConfig", () => ({ useMoatConfig: () => ({ data: { wide_moat_score: 100, narrow_moat_score: 65, no_moat_score: 0 } }) }));

function payload(overall: { financials: number; growth: number; profitability: number; debt: number }): ScoreWeightsOut {
  return {
    weights: { overall, step1: {}, step2: {}, step4: {}, step5: {} },
    moat_weight: 31,
    overall_total: 69,
    weights_version: 2,
  } as unknown as ScoreWeightsOut;
}

beforeEach(() => {
  h.weights = undefined;
});
afterEach(() => vi.clearAllMocks());

describe("useScoreWeights", () => {
  it("reads the settings endpoint", async () => {
    const { useApiResource } = await import("@/lib/hooks/useApiResource");
    renderHook(() => useScoreWeights());
    expect(useApiResource).toHaveBeenCalledWith("/config/score-weights");
  });

  it("maps the payload to what the Overall blend needs, with Moat's locked percent from the endpoint", () => {
    expect(overallBlendWeights(payload({ financials: 17, growth: 17, profitability: 17, debt: 18 }))).toEqual({
      overall: { financials: 17, growth: 17, profitability: 17, debt: 18 },
      overallTotal: 69,
      moatWeight: 31,
    });
  });
});

describe("useOverallAssessment reads the saved weights", () => {
  it("stays loading, with no score, until the weights have arrived", () => {
    const { result } = renderHook(() => useOverallAssessment("AAPL"));
    expect(result.current.status).toBe("loading");
    expect(result.current.score).toBeNull();
  });

  it("blends with the saved set: defaults give 76, a debt-heavy set gives 71", () => {
    h.weights = payload({ financials: 24, growth: 10, profitability: 20, debt: 15 });
    expect(renderHook(() => useOverallAssessment("AAPL")).result.current.score).toBe(76);
    h.weights = payload({ financials: 15, growth: 8, profitability: 16, debt: 30 });
    expect(renderHook(() => useOverallAssessment("AAPL")).result.current.score).toBe(71);
  });
});
