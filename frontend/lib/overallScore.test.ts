import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  computeOverallAssessment as computeWith,
  MOAT_NOT_RATED_REASON,
  MOAT_NOT_RATED_VERDICT,
  type MoatSnapshot,
  type OverallBlendWeights,
  type OverallWeights,
  type StepSnapshot,
} from "@/lib/overallScore";
import { pySum, roundHalfEven } from "@/lib/pyNumeric";

// The shared fixture (also read by backend/tests/test_moat_not_rated.py). Its `defaults` are tied to the backend's DEFAULT_WEIGHTS by a
// backend test, so these tests need no weight constants of their own.
const FIXTURE = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../backend/tests/fixtures/overall_verdict_cases.json"), "utf-8"),
);

function blendWeights(overall: OverallWeights): OverallBlendWeights {
  return { overall, overallTotal: FIXTURE.defaults.overall_total, moatWeight: FIXTURE.defaults.moat_weight };
}
const DEFAULT_WEIGHTS = blendWeights(FIXTURE.defaults.overall);
// The defaults as fractions of the 69 points, the way the backend's STEP_WEIGHTS holds them.
const STEP_WEIGHTS = {
  step1: DEFAULT_WEIGHTS.overall.financials / DEFAULT_WEIGHTS.overallTotal,
  step2: DEFAULT_WEIGHTS.overall.growth / DEFAULT_WEIGHTS.overallTotal,
  step4: DEFAULT_WEIGHTS.overall.profitability / DEFAULT_WEIGHTS.overallTotal,
  step5: DEFAULT_WEIGHTS.overall.debt / DEFAULT_WEIGHTS.overallTotal,
};

// Every call in this file that does not name weights runs under the defaults.
function computeOverallAssessment(
  steps: StepSnapshot[],
  moat?: MoatSnapshot | null,
  moatLoading = false,
  weights: OverallBlendWeights = DEFAULT_WEIGHTS
) {
  return computeWith(steps, moat, moatLoading, weights);
}

function snapshot(key: StepSnapshot["key"], label: string, score: number | null, verdict: string): StepSnapshot {
  return { key, label, hasError: false, data: { score, verdict } };
}

const BASE: StepSnapshot[] = [
  snapshot("step1", "Step 1", 100, "Strong Pass"),
  snapshot("step2", "Step 2", 100, "Strong Pass"),
  snapshot("step4", "Step 4", 100, "Strong Pass"),
  snapshot("step5", "Step 5", 100, "Strong Pass"),
];

describe("computeOverallAssessment", () => {
  it("computes a standard weighted average when every step has a real score", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 80, "Pass"),
      snapshot("step4", "Step 4", 70, "Pass"),
      snapshot("step5", "Step 5", 60, "Pass"),
    ];
    // 90*(24/69) + 80*(10/69) + 70*(20/69) + 60*(15/69) = 5260/69 = 76.23 -> 76
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("complete");
    expect(result.score).toBe(76);
    expect(result.verdict).toBe(MOAT_NOT_RATED_VERDICT); // steps-only Pass, Moat unset
  });

  it("all steps at 100 scores exactly 100, Strong Pass", () => {
    const result = computeOverallAssessment(BASE);
    expect(result.score).toBe(100);
    expect(result.verdict).toBe(MOAT_NOT_RATED_VERDICT); // steps-only Strong Pass, Moat unset
  });

  it("renormalizes weights when a step is structurally exempt (not_supported)", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      snapshot("step5", "Step 5", null, "not_supported"),
    ];
    // Step 5 excluded; remaining weights (step1+step2+step4) renormalize to
    // sum to 1 -- since all 3 remaining scores are equal (90), the
    // renormalized weighted average is still exactly 90 regardless of the
    // individual renormalized weights.
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("complete");
    expect(result.score).toBe(90);
    const step5Entry = result.breakdown.find((b) => b.key === "step5")!;
    expect(step5Entry.status).toBe("exempt");
    expect(step5Entry.effectiveWeight).toBeNull();
    const step1Entry = result.breakdown.find((b) => b.key === "step1")!;
    const remaining = STEP_WEIGHTS.step1 + STEP_WEIGHTS.step2 + STEP_WEIGHTS.step4;
    expect(step1Entry.effectiveWeight).toBeCloseTo(STEP_WEIGHTS.step1 / remaining, 5);
  });

  it("renormalization actually shifts the score when remaining scores differ", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 100, "Strong Pass"),
      snapshot("step2", "Step 2", 0, "Fail"),
      snapshot("step4", "Step 4", 100, "Strong Pass"),
      snapshot("step5", "Step 5", null, "not_supported"),
    ];
    // Without step5: (100*24/69 + 0*10/69 + 100*20/69) / (24/69+10/69+20/69)
    // = 4400/69 / (54/69) = 4400/54 = 81.48 -> 81
    const result = computeOverallAssessment(steps);
    expect(result.score).toBe(81);
  });

  it("shows an incomplete state instead of a partial score when a step errors", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), { key: "step5", label: "Step 5", hasError: true, data: undefined }];
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("incomplete");
    expect(result.score).toBeNull();
    expect(result.incompleteSteps).toEqual(["Step 5"]);
  });

  it("shows an incomplete state when a step has insufficient_data (missing data, not exempt)", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), snapshot("step5", "Step 5", null, "insufficient_data")];
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("incomplete");
    expect(result.score).toBeNull();
    expect(result.incompleteSteps).toEqual(["Step 5"]);
  });

  it("stays in loading status until every step has settled", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), { key: "step5", label: "Step 5", hasError: false, data: undefined }];
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("loading");
    expect(result.score).toBeNull();
  });

  it("lists every incomplete step by name when more than one fails to load", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      { key: "step2", label: "Step 2", hasError: true, data: undefined },
      snapshot("step4", "Step 4", 90, "Pass"),
      { key: "step5", label: "Step 5", hasError: true, data: undefined },
    ];
    const result = computeOverallAssessment(steps);
    expect(result.incompleteSteps).toEqual(["Step 2", "Step 5"]);
  });

  it("flags a Fail-warning when any implemented step's verdict is Fail", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      snapshot("step5", "Step 5", 0, "Fail"),
    ];
    const result = computeOverallAssessment(steps);
    // No hard-fail override -- the score is still a plain weighted average.
    expect(result.score).toBe(round(90 * STEP_WEIGHTS.step1 + 90 * STEP_WEIGHTS.step2 + 90 * STEP_WEIGHTS.step4 + 0 * STEP_WEIGHTS.step5));
    expect(result.failingSteps).toEqual(["Step 5"]);
  });

  it("stays silent (no failingSteps) when nothing failed", () => {
    const result = computeOverallAssessment(BASE);
    expect(result.failingSteps).toEqual([]);
  });

  it("lists every failing step by name when more than one Fails", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 0, "Fail"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      snapshot("step5", "Step 5", 0, "Fail"),
    ];
    const result = computeOverallAssessment(steps);
    expect(result.failingSteps).toEqual(["Step 1", "Step 5"]);
  });

  it("flags a caution-warning when a step's verdict is Pass with caution, and propagates it to the displayed verdict", () => {
    // Mirrors Step 5's real shape -- a Borderline breach excused by its
    // tiebreaker must surface here too, not just blend silently into the
    // weighted score (previously missing -- see OverallAssessmentCard's
    // chip fix, same underlying gap). The propagated verdict overrides
    // what would otherwise be a green Strong Pass display; the underlying
    // blended `score` itself is untouched.
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      snapshot("step5", "Step 5", 95, "Pass with caution"),
    ];
    const result = computeOverallAssessment(steps);
    expect(result.cautionSteps).toEqual(["Step 5"]);
    expect(result.failingSteps).toEqual([]);
    // 90*(54/69) + 95*(15/69) = (4860+1425)/69 = 91.09 -> 91 (coincidentally
    // unchanged from the pre-rebalance weights for this particular input)
    expect(result.score).toBe(91);
    expect(result.verdict).toBe(MOAT_NOT_RATED_VERDICT); // Moat unset outranks the caution flag
    expect(computeOverallAssessment(steps, { moat: "wide_moat", score: 100 }).verdict).toBe("Pass with caution");
  });

  it("stays silent (no cautionSteps) when nothing passed with caution", () => {
    const result = computeOverallAssessment(BASE);
    expect(result.cautionSteps).toEqual([]);
    expect(computeOverallAssessment(BASE, { moat: "wide_moat", score: 100 }).verdict).toBe("Strong Pass");
  });

  it("caution propagation never overrides an already-failing blend", () => {
    // Fail must remain the strongest signal in the system -- a caution
    // flag never softens an already-failing blend into "Pass with caution".
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 30, "Fail"),
      snapshot("step2", "Step 2", 30, "Fail"),
      snapshot("step4", "Step 4", 30, "Fail"),
      snapshot("step5", "Step 5", 74, "Pass with caution"),
    ];
    const result = computeOverallAssessment(steps);
    expect(result.score).toBeLessThan(70);
    expect(result.verdict).toBe("Fail");
  });

  it("shows Fail, not Pass, when the score is under 70", () => {
    // Mirrors CCL's real shape -- a low blended score must read as "Fail",
    // matching the shared 0-69/70-90/91-100 bands used everywhere else in
    // the app (previously always read "Pass" regardless of how low).
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 57, "Fail"),
      snapshot("step2", "Step 2", 58, "Pass"),
      snapshot("step4", "Step 4", 20, "Fail"),
      snapshot("step5", "Step 5", 28, "Fail"),
    ];
    const result = computeOverallAssessment(steps);
    expect(result.score!).toBeLessThan(70);
    expect(result.verdict).toBe("Fail");
  });

  it("a score of exactly 70 is Pass, not Fail", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 70, "Pass"),
      snapshot("step2", "Step 2", 70, "Pass"),
      snapshot("step4", "Step 4", 70, "Pass"),
      snapshot("step5", "Step 5", 70, "Pass"),
    ];
    const result = computeOverallAssessment(steps);
    expect(result.score).toBe(70);
    expect(result.verdict).toBe(MOAT_NOT_RATED_VERDICT); // a 70 steps-only blend is Pass-band; Moat unset
  });

  it("a score of 69 is Fail", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 69, "Pass"),
      snapshot("step2", "Step 2", 69, "Pass"),
      snapshot("step4", "Step 4", 69, "Pass"),
      snapshot("step5", "Step 5", 69, "Pass"),
    ];
    const result = computeOverallAssessment(steps);
    expect(result.score).toBe(69);
    expect(result.verdict).toBe("Fail");
  });
});

function round(n: number): number {
  return Math.round(n);
}

// --- Economic Moat (worked examples, ticker blending to 90 across Steps
// 1/2/4/5 with all four present) ---

const STEPS_BLENDING_TO_90: StepSnapshot[] = [
  snapshot("step1", "Step 1", 90, "Pass"),
  snapshot("step2", "Step 2", 90, "Pass"),
  snapshot("step4", "Step 4", 90, "Pass"),
  snapshot("step5", "Step 5", 90, "Pass"),
];

describe("computeOverallAssessment with moat", () => {
  it("omitted moat is byte-identical to the pre-Moat behavior", () => {
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90);
    expect(result.score).toBe(90);
    expect(result.verdict).toBe(MOAT_NOT_RATED_VERDICT); // 90 is the Pass band, but Moat unset can never pass
    expect(result.breakdown.some((b) => b.key === "moat")).toBe(false);
  });

  it("null moat behaves the same as omitted", () => {
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90, null);
    expect(result.score).toBe(90);
    expect(result.breakdown.some((b) => b.key === "moat")).toBe(false);
  });

  it("Wide Moat worked example: 0.69*90 + 0.31*100 = 93.1 -> 93", () => {
    const moat: MoatSnapshot = { moat: "wide_moat", score: 100 };
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90, moat);
    expect(result.score).toBe(93);
    expect(result.verdict).toBe("Strong Pass");
  });

  it("Narrow Moat worked example: 0.69*90 + 0.31*65 = 82.25 -> 82", () => {
    const moat: MoatSnapshot = { moat: "narrow_moat", score: 65 };
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90, moat);
    expect(result.score).toBe(82);
    expect(result.verdict).toBe("Pass");
  });

  it("No Moat worked example caps below the Pass threshold: 0.69*90 = 62.1 -> 62", () => {
    const moat: MoatSnapshot = { moat: "no_moat", score: 0 };
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90, moat);
    expect(result.score).toBe(62);
    expect(result.verdict).toBe("Fail");
  });

  it("No Moat caps even a perfect steps score at 69, Fail -- hard-fail-via-arithmetic by design", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 100, "Strong Pass"),
      snapshot("step2", "Step 2", 100, "Strong Pass"),
      snapshot("step4", "Step 4", 100, "Strong Pass"),
      snapshot("step5", "Step 5", 100, "Strong Pass"),
    ];
    const moat: MoatSnapshot = { moat: "no_moat", score: 0 };
    const result = computeOverallAssessment(steps, moat);
    expect(result.score).toBe(69);
    expect(result.verdict).toBe("Fail");
  });

  it("moat does not rescue an incomplete steps blend", () => {
    const steps: StepSnapshot[] = [
      ...STEPS_BLENDING_TO_90.slice(0, 3),
      { key: "step5", label: "Step 5", hasError: true, data: undefined },
    ];
    const moat: MoatSnapshot = { moat: "wide_moat", score: 100 };
    const result = computeOverallAssessment(steps, moat);
    expect(result.status).toBe("incomplete");
    expect(result.score).toBeNull();
  });

  it("moat applies on top of a renormalized steps blend with an exempt step", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      snapshot("step5", "Step 5", null, "not_supported"),
    ];
    // Steps-only blend renormalizes to 90 (all remaining scores equal) --
    // applying moat on top must still be 0.69*90 + 0.31*100 = 93.1 -> 93,
    // not a different number from a flat single-stage renormalization.
    const moat: MoatSnapshot = { moat: "wide_moat", score: 100 };
    const result = computeOverallAssessment(steps, moat);
    expect(result.score).toBe(93);
  });

  it("moat breakdown entry never appears in failingSteps", () => {
    const moat: MoatSnapshot = { moat: "no_moat", score: 0 };
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90, moat);
    expect(result.failingSteps).toEqual([]);
    const moatEntry = result.breakdown.find((b) => b.key === "moat")!;
    expect(moatEntry.verdict).toBe("No Moat");
    expect(moatEntry.score).toBe(0);
  });

  it("moatLoading holds the whole result in loading status", () => {
    const result = computeOverallAssessment(STEPS_BLENDING_TO_90, null, true);
    expect(result.status).toBe("loading");
    expect(result.score).toBeNull();
  });
});

// The same cases backend/tests/test_moat_not_rated.py runs through scoring/overall.py: the two implementations of the
// Overall verdict must agree on every one. A case's optional `weights.overall` is the saved weight set it runs under.
interface SharedCase {
  name: string;
  weights?: { overall: OverallWeights };
  steps: { key: StepSnapshot["key"]; score: number | null; verdict: string }[];
  moat: MoatSnapshot | null;
  expected: { status: string; score: number | null; verdict: string | null };
}

function runCase(c: SharedCase) {
  const steps = c.steps.map((s) => snapshot(s.key, s.key, s.score, s.verdict));
  const weights = c.weights ? blendWeights(c.weights.overall) : DEFAULT_WEIGHTS;
  const result = computeWith(steps, c.moat, false, weights);
  return { status: result.status, score: result.score, verdict: result.verdict };
}

describe("computeOverallAssessment: the cases shared with the backend", () => {
  const cases: SharedCase[] = FIXTURE.cases;
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(runCase(c)).toEqual(c.expected);
  });
});

describe("computeOverallAssessment: Moat not rated", () => {
  it("carries the reason only for the moat_not_rated verdict", () => {
    const unrated = computeOverallAssessment(BASE);
    expect(unrated.verdict).toBe(MOAT_NOT_RATED_VERDICT);
    expect(unrated.verdictReason).toBe(MOAT_NOT_RATED_REASON);
    const rated = computeOverallAssessment(BASE, { moat: "wide_moat", score: 100 });
    expect(rated.verdictReason).toBeNull();
    const failing = computeOverallAssessment([snapshot("step1", "S1", 40, "Fail"), snapshot("step2", "S2", 40, "Fail"), snapshot("step4", "S4", 40, "Fail"), snapshot("step5", "S5", 40, "Fail")]);
    expect(failing.verdict).toBe("Fail");
    expect(failing.verdictReason).toBeNull();
  });

  it("a loading moat is still loading, not Moat not rated", () => {
    expect(computeOverallAssessment(BASE, null, true).verdict).toBeNull();
  });
});

describe("computeOverallAssessment: exact .5 ties round half to even, like the backend", () => {
  const cases: SharedCase[] = FIXTURE.rounding_cases;
  it("has the cases the fixture promises", () => {
    expect(cases.length).toBeGreaterThanOrEqual(8);
  });
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(runCase(c)).toEqual(c.expected);
  });
  it("is not Math.round: 34.5 reads 34 (steps 50, No Moat), where Math.round would say 35", () => {
    const steps = ["step1", "step2", "step4", "step5"].map((k) => snapshot(k as StepSnapshot["key"], k, 50, "Pass"));
    const result = computeOverallAssessment(steps, { moat: "no_moat", score: 0 });
    expect(result.score).toBe(34);
    expect(Math.round((1 - 0.31) * 50 + 0.31 * 0)).toBe(35);
  });
});

describe("computeOverallAssessment: random weight sets generated by the backend", () => {
  const cases: SharedCase[] = FIXTURE.parity_cases;
  it("covers many weight sets", () => {
    expect(cases.length).toBeGreaterThanOrEqual(100);
    expect(new Set(cases.map((c) => JSON.stringify(c.weights))).size).toBeGreaterThanOrEqual(100);
  });
  it("agrees with the backend on every one (status, score and verdict)", () => {
    const wrong = cases.filter((c) => JSON.stringify(runCase(c)) !== JSON.stringify(c.expected)).map((c) => c.name);
    expect(wrong).toEqual([]);
  });
});

describe("computeOverallAssessment: custom weights", () => {
  const EQUAL: OverallBlendWeights = blendWeights({ financials: 17, growth: 17, profitability: 17, debt: 18 });
  const steps = [snapshot("step1", "S1", 90, "Pass"), snapshot("step2", "S2", 80, "Pass"), snapshot("step4", "S4", 70, "Pass"), snapshot("step5", "S5", 60, "Pass")];

  it("blends with the weights it is given", () => {
    const result = computeOverallAssessment(steps, null, false, EQUAL);
    expect(result.score).toBe(roundHalfEven((90 * 17 + 80 * 17 + 70 * 17 + 60 * 18) / 69));
    expect(result.breakdown[3].baseWeight).toBeCloseTo(18 / 69, 10);
  });

  it("is independent of the order the steps arrive in", () => {
    const shuffled = [steps[3], steps[1], steps[0], steps[2]];
    expect(computeOverallAssessment(shuffled, null, false, EQUAL).score).toBe(computeOverallAssessment(steps, null, false, EQUAL).score);
    // ...while the breakdown keeps the caller's order (it is what the card lists).
    expect(computeOverallAssessment(shuffled, null, false, EQUAL).breakdown.map((b) => b.key)).toEqual(["step5", "step2", "step1", "step4"]);
  });

  it("No Moat at the default 0 points still caps perfect steps at 69, whatever the split", () => {
    const perfect = ["step1", "step2", "step4", "step5"].map((k) => snapshot(k as StepSnapshot["key"], k, 100, "Strong Pass"));
    for (const w of [{ financials: 30, growth: 5, profitability: 5, debt: 29 }, { financials: 10, growth: 30, profitability: 19, debt: 10 }]) {
      const result = computeOverallAssessment(perfect, { moat: "no_moat", score: 0 }, false, blendWeights(w));
      expect(result.score).toBe(69);
      expect(result.verdict).toBe("Fail");
    }
  });

  it("takes Moat's share from the payload, not from a constant", () => {
    const weights: OverallBlendWeights = { ...DEFAULT_WEIGHTS, moatWeight: 31 };
    const result = computeOverallAssessment(steps, { moat: "wide_moat", score: 100 }, false, weights);
    expect(result.breakdown.find((b) => b.key === "moat")!.baseWeight).toBe(0.31);
  });
});

describe("pyNumeric", () => {
  it.each([
    [0.5, 0],
    [1.5, 2],
    [2.5, 2],
    [3.5, 4],
    [34.5, 34],
    [65.5, 66],
    [2.4999, 2],
    [2.5001, 3],
    [-0.5, 0],
    [-1.5, -2],
  ])("roundHalfEven(%s) = %s", (x, expected) => {
    expect(roundHalfEven(x)).toBe(expected);
  });

  it("pySum is Python 3.12's compensated sum, not a left-to-right fold", () => {
    // sum([0.1] * 10) is 1.0 in Python 3.12 (Neumaier) but 0.9999999999999999 as a plain fold.
    const tenth = Array(10).fill(0.1);
    expect(tenth.reduce((a, b) => a + b, 0)).not.toBe(1);
    expect(pySum(tenth)).toBe(1);
  });

  it("pySum of nothing is 0 and of one value is that value", () => {
    expect(pySum([])).toBe(0);
    expect(pySum([0.3])).toBe(0.3);
  });
});
