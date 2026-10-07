import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  computeOverallAssessment as computeWith,
  DEFAULT_NARROW_MOAT_MULTIPLIER,
  MOAT_NOT_RATED_NOTE,
  moatMultiplier,
  NARROW_MOAT_MULTIPLIER_OPTIONS,
  NO_MOAT_MULTIPLIER,
  WIDE_MOAT_MULTIPLIER,
  type MoatValue,
  type OverallBlendWeights,
  type OverallWeights,
  type StepSnapshot,
} from "@/lib/overallScore";
import { pySum, roundHalfEven } from "@/lib/pyNumeric";

// The shared fixture (also read by backend/tests/test_overall_multiplier.py). Its `defaults` are tied to the backend's constants by a backend
// test, so these tests need no weight or multiplier constants of their own. Regenerate it with
// backend/tests/fixtures/generate_overall_verdict_cases.py.
const FIXTURE = JSON.parse(
  readFileSync(path.resolve(__dirname, "../../backend/tests/fixtures/overall_verdict_cases.json"), "utf-8"),
);

function blendWeights(overall: OverallWeights): OverallBlendWeights {
  return { overall, overallTotal: FIXTURE.defaults.overall_total };
}
const DEFAULT_WEIGHTS = blendWeights(FIXTURE.defaults.overall);

// Every call in this file that does not name weights runs under the defaults (30/20/20/30), and one that does not name a Narrow
// multiplier under the default 0.85.
function computeOverallAssessment(
  steps: StepSnapshot[],
  moat?: MoatValue | null,
  moatLoading = false,
  weights: OverallBlendWeights = DEFAULT_WEIGHTS,
  narrow: number = DEFAULT_NARROW_MOAT_MULTIPLIER
) {
  return computeWith(steps, moat, moatLoading, weights, narrow);
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

const STEPS_90: StepSnapshot[] = ["step1", "step2", "step4", "step5"].map((k) => snapshot(k as StepSnapshot["key"], k, 90, "Pass"));

const uniform = (score: number, verdict: string, step5Verdict = verdict): StepSnapshot[] => [
  snapshot("step1", "Step 1", score, verdict),
  snapshot("step2", "Step 2", score, verdict),
  snapshot("step4", "Step 4", score, verdict),
  snapshot("step5", "Step 5", score, step5Verdict),
];

describe("computeOverallAssessment: the Steps score", () => {
  it("is the weighted average of the four steps, unrounded: 90*.30 + 80*.20 + 70*.20 + 60*.30 = 75", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 80, "Pass"),
      snapshot("step4", "Step 4", 70, "Pass"),
      snapshot("step5", "Step 5", 60, "Pass"),
    ];
    const result = computeOverallAssessment(steps, "wide_moat");
    expect(result.status).toBe("complete");
    expect(result.stepsScore).toBeCloseTo(75, 10);
    expect(result.score).toBe(75);
    expect(result.verdict).toBe("Pass");
  });

  it("all steps at 100 with a Wide moat scores exactly 100, Strong Pass", () => {
    const result = computeOverallAssessment(BASE, "wide_moat");
    expect(result.score).toBe(100);
    expect(result.verdict).toBe("Strong Pass");
  });

  it("renormalizes weights when a step is structurally exempt (not_supported)", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      { key: "step5", label: "Step 5", hasError: false, data: { score: null, verdict: "not_supported" } },
    ];
    const result = computeOverallAssessment(steps, "wide_moat");
    expect(result.status).toBe("complete");
    expect(result.score).toBe(90);
    const step5 = result.breakdown.find((b) => b.key === "step5")!;
    expect(step5.status).toBe("exempt");
    expect(step5.effectiveWeight).toBeNull();
    expect(result.breakdown.find((b) => b.key === "step1")!.effectiveWeight).toBeCloseTo(0.3 / 0.7, 10);
  });

  it("renormalization actually shifts the score when remaining scores differ: (100*30 + 0*20 + 100*20)/70 = 71.43 -> 71", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 100, "Strong Pass"),
      snapshot("step2", "Step 2", 0, "Fail"),
      snapshot("step4", "Step 4", 100, "Strong Pass"),
      { key: "step5", label: "Step 5", hasError: false, data: { score: null, verdict: "not_supported" } },
    ];
    expect(computeOverallAssessment(steps, "wide_moat").score).toBe(71);
  });

  it("the breakdown has no Moat row and its effective weights add up to one", () => {
    const result = computeOverallAssessment(STEPS_90, "wide_moat");
    expect(result.breakdown.map((b) => b.key)).toEqual(["step1", "step2", "step4", "step5"]);
    expect(result.breakdown.map((b) => b.effectiveWeight)).toEqual([0.3, 0.2, 0.2, 0.3]);
  });
});

describe("computeOverallAssessment: incomplete and loading", () => {
  it("shows an incomplete state instead of a partial score when a step errors", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), { key: "step5", label: "Step 5", hasError: true, data: undefined }];
    const result = computeOverallAssessment(steps, "wide_moat");
    expect(result.status).toBe("incomplete");
    expect(result.score).toBeNull();
    expect(result.stepsScore).toBeNull();
    expect(result.moatMultiplier).toBeNull();
    expect(result.incompleteSteps).toEqual(["Step 5"]);
  });

  it("shows an incomplete state when a step has insufficient_data (missing data, not exempt), and no unrated note", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), snapshot("step5", "Step 5", null, "insufficient_data")];
    const result = computeOverallAssessment(steps, null);
    expect(result.status).toBe("incomplete");
    expect(result.score).toBeNull();
    expect(result.moatNote).toBeNull();
  });

  it("stays in loading status until every step has settled", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), { key: "step5", label: "Step 5", hasError: false, data: undefined }];
    const result = computeOverallAssessment(steps, "wide_moat");
    expect(result.status).toBe("loading");
    expect(result.score).toBeNull();
  });

  it("moatLoading holds the whole result in loading status", () => {
    const result = computeOverallAssessment(BASE, "narrow_moat", true);
    expect(result.status).toBe("loading");
    expect(result.score).toBeNull();
    expect(result.verdict).toBeNull();
    // A loading Moat is still loading, not "not rated".
    expect(computeOverallAssessment(BASE, null, true).moatNote).toBeNull();
  });

  it("lists every incomplete step by name when more than one fails to load", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      { key: "step2", label: "Step 2", hasError: true, data: undefined },
      snapshot("step4", "Step 4", 90, "Pass"),
      { key: "step5", label: "Step 5", hasError: true, data: undefined },
    ];
    expect(computeOverallAssessment(steps, "wide_moat").incompleteSteps).toEqual(["Step 2", "Step 5"]);
  });

  it("a Moat rating does not rescue an incomplete steps blend", () => {
    const steps: StepSnapshot[] = [...BASE.slice(0, 3), snapshot("step5", "Step 5", null, "insufficient_data")];
    const result = computeOverallAssessment(steps, "wide_moat");
    expect(result.status).toBe("incomplete");
    expect(result.score).toBeNull();
  });
});

describe("computeOverallAssessment: failing, caution and the verdict bands", () => {
  it("flags a Fail-warning when a step's verdict is Fail, with no override of the score", () => {
    const steps = [snapshot("step1", "Step 1", 90, "Pass"), snapshot("step2", "Step 2", 90, "Pass"), snapshot("step4", "Step 4", 90, "Pass"), snapshot("step5", "Step 5", 0, "Fail")];
    const result = computeOverallAssessment(steps, "wide_moat");
    expect(result.score).toBe(63);
    expect(result.failingSteps).toEqual(["Step 5"]);
    expect(computeOverallAssessment(BASE, "wide_moat").failingSteps).toEqual([]);
  });

  it("lists every failing step by name when more than one Fails", () => {
    const steps = [snapshot("step1", "Step 1", 0, "Fail"), snapshot("step2", "Step 2", 90, "Pass"), snapshot("step4", "Step 4", 90, "Pass"), snapshot("step5", "Step 5", 0, "Fail")];
    expect(computeOverallAssessment(steps, "wide_moat").failingSteps).toEqual(["Step 1", "Step 5"]);
  });

  it("a caution step propagates to the displayed verdict of a passing score, and never softens a Fail", () => {
    const caution = [...BASE.slice(0, 3), snapshot("step5", "Step 5", 74, "Pass with caution")];
    const wide = computeOverallAssessment(caution, "wide_moat");
    expect(wide.score).toBe(92); // the underlying score is untouched
    expect(wide.verdict).toBe("Pass with caution");
    expect(wide.cautionSteps).toEqual(["Step 5"]);
    // Unrated: 92.2 x 0.7 = 64.5 -> 64, a Fail, which a caution never softens.
    expect(computeOverallAssessment(caution, null).verdict).toBe("Fail");
    expect(computeOverallAssessment(BASE, "wide_moat").cautionSteps).toEqual([]);
  });

  it("bands: 69 is Fail, 70 is Pass, 90 is Pass, 91 is Strong Pass", () => {
    expect(computeOverallAssessment(uniform(69, "Fail"), "wide_moat").verdict).toBe("Fail");
    expect(computeOverallAssessment(uniform(70, "Pass"), "wide_moat").verdict).toBe("Pass");
    expect(computeOverallAssessment(uniform(90, "Pass"), "wide_moat").verdict).toBe("Pass");
    expect(computeOverallAssessment(uniform(91, "Strong Pass"), "wide_moat").verdict).toBe("Strong Pass");
  });
});

describe("computeOverallAssessment: the Moat multiplier", () => {
  it("resolves the multipliers (unset is No moat; Narrow is the saved setting)", () => {
    expect(moatMultiplier("wide_moat")).toBe(1);
    expect(moatMultiplier("narrow_moat")).toBe(0.85);
    expect(moatMultiplier("narrow_moat", 0.9)).toBe(0.9);
    expect(moatMultiplier("no_moat")).toBe(0.7);
    expect(moatMultiplier(null)).toBe(0.7);
    expect(moatMultiplier(undefined, 0.9)).toBe(0.7);
    expect([WIDE_MOAT_MULTIPLIER, NO_MOAT_MULTIPLIER]).toEqual([1.0, 0.7]);
    expect([...NARROW_MOAT_MULTIPLIER_OPTIONS]).toEqual([0.8, 0.82, 0.85, 0.87, 0.9]);
  });

  it("Wide, Narrow and No moat worked examples on steps of 90", () => {
    expect(computeOverallAssessment(STEPS_90, "wide_moat")).toMatchObject({ score: 90, verdict: "Pass", moatMultiplier: 1 });
    // 90 x 0.85 = 76.5 -> 76 (half to even)
    expect(computeOverallAssessment(STEPS_90, "narrow_moat")).toMatchObject({ score: 76, verdict: "Pass", moatMultiplier: 0.85 });
    // 90 x 0.70 = 63
    expect(computeOverallAssessment(STEPS_90, "no_moat")).toMatchObject({ score: 63, verdict: "Fail", moatMultiplier: 0.7 });
  });

  it("the Analysis card example: Steps 83.8 x Narrow 0.85 = 71", () => {
    const steps = [snapshot("step1", "S1", 84, "Pass"), snapshot("step2", "S2", 84, "Pass"), snapshot("step4", "S4", 83, "Pass"), snapshot("step5", "S5", 84, "Pass")];
    const result = computeOverallAssessment(steps, "narrow_moat");
    expect(result.stepsScore!.toFixed(1)).toBe("83.8");
    expect(result.score).toBe(71);
  });

  it("keeps the Steps score unrounded and rounds once after the multiplier: Steps 81.6 x 0.85 = 69.36 -> 69, not 70", () => {
    const steps = [snapshot("step1", "S1", 81, "Pass"), snapshot("step2", "S2", 83, "Pass"), snapshot("step4", "S4", 82, "Pass"), snapshot("step5", "S5", 81, "Pass")];
    const result = computeOverallAssessment(steps, "narrow_moat");
    expect(result.stepsScore).toBeCloseTo(81.6, 10);
    expect(result.score).toBe(69);
    expect(result.verdict).toBe("Fail");
  });

  it.each([...NARROW_MOAT_MULTIPLIER_OPTIONS])("applies the saved Narrow multiplier %s", (narrow) => {
    const result = computeOverallAssessment(STEPS_90, "narrow_moat", false, DEFAULT_WEIGHTS, narrow);
    expect(result.moatMultiplier).toBe(narrow);
    expect(result.score).toBe(roundHalfEven(90 * narrow));
  });

  it("a perfect steps score with No moat reaches exactly 70 (the one way a No moat ticker can read Pass)", () => {
    expect(computeOverallAssessment(BASE, "no_moat")).toMatchObject({ score: 70, verdict: "Pass" });
  });

  it("applies on top of a renormalized steps blend with an exempt step", () => {
    const steps: StepSnapshot[] = [...STEPS_90.slice(0, 3), { key: "step5", label: "Step 5", hasError: false, data: { score: null, verdict: "not_supported" } }];
    expect(computeOverallAssessment(steps, "narrow_moat").score).toBe(76);
  });
});

describe("computeOverallAssessment: Moat not rated", () => {
  it("is scored exactly as No moat, with the note, and never reads a 'moat_not_rated' verdict", () => {
    const unrated = computeOverallAssessment(STEPS_90, null);
    const rated = computeOverallAssessment(STEPS_90, "no_moat");
    expect([unrated.score, unrated.verdict, unrated.moatMultiplier, unrated.stepsScore]).toEqual([rated.score, rated.verdict, rated.moatMultiplier, rated.stepsScore]);
    expect(unrated.moatNote).toBe(MOAT_NOT_RATED_NOTE);
    expect(MOAT_NOT_RATED_NOTE).toBe("Moat not rated, scored as No moat");
    expect(rated.moatNote).toBeNull();
    expect(computeOverallAssessment(BASE, undefined).verdict).toBe("Pass"); // 100 x 0.7 = 70, the boundary
  });

  it("an unrated Pass-range steps score reads a Fail from its x0.7 score", () => {
    expect(computeOverallAssessment(uniform(95, "Strong Pass"), null)).toMatchObject({ score: 66, verdict: "Fail" });
  });
});

// The same cases backend/tests/test_overall_multiplier.py runs through scoring/overall.py: the two implementations of Overall = Steps x
// Moat multiplier must agree on every one. A case's optional `weights.overall` is the saved weight set it runs under and its optional
// `narrow_multiplier` the saved Narrow setting.
interface SharedCase {
  name: string;
  weights?: { overall: OverallWeights };
  narrow_multiplier?: number;
  steps: { key: StepSnapshot["key"]; score: number | null; verdict: string }[];
  moat: MoatValue | null;
  expected: {
    status: string;
    score: number | null;
    verdict: string | null;
    steps_score: number | null;
    moat_multiplier: number | null;
    moat_note: string | null;
  };
}

function runCase(c: SharedCase) {
  const steps = c.steps.map((s) => snapshot(s.key, s.key, s.score, s.verdict));
  const weights = c.weights ? blendWeights(c.weights.overall) : DEFAULT_WEIGHTS;
  const result = computeWith(steps, c.moat, false, weights, c.narrow_multiplier ?? FIXTURE.defaults.narrow_multiplier);
  return {
    status: result.status,
    score: result.score,
    verdict: result.verdict,
    steps_score: result.stepsScore,
    moat_multiplier: result.moatMultiplier,
    moat_note: result.moatNote,
  };
}

describe("the fixture's defaults match this file's constants", () => {
  it("multipliers, options and the note", () => {
    expect(FIXTURE.defaults.wide_multiplier).toBe(WIDE_MOAT_MULTIPLIER);
    expect(FIXTURE.defaults.no_moat_multiplier).toBe(NO_MOAT_MULTIPLIER);
    expect(FIXTURE.defaults.narrow_multiplier).toBe(DEFAULT_NARROW_MOAT_MULTIPLIER);
    expect(FIXTURE.defaults.narrow_multiplier_options).toEqual([...NARROW_MOAT_MULTIPLIER_OPTIONS]);
    expect(FIXTURE.defaults.not_rated_note).toBe(MOAT_NOT_RATED_NOTE);
    expect(FIXTURE.defaults.overall_total).toBe(100);
  });
});

describe("computeOverallAssessment: the cases shared with the backend", () => {
  const cases: SharedCase[] = FIXTURE.cases;
  it("has the curated cases", () => {
    expect(cases.length).toBeGreaterThanOrEqual(25);
  });
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(runCase(c)).toEqual(c.expected);
  });
});

describe("computeOverallAssessment: exact .5 ties round half to even, like the backend", () => {
  const cases: SharedCase[] = FIXTURE.rounding_cases;
  it("has the cases the fixture promises", () => {
    expect(cases.length).toBeGreaterThanOrEqual(4);
  });
  it.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(runCase(c)).toEqual(c.expected);
  });
  it("is not Math.round: 42.5 reads 42 (steps 50, Narrow 0.85), where Math.round would say 43", () => {
    const result = computeOverallAssessment(uniform(50, "Pass"), "narrow_moat");
    expect(result.stepsScore! * result.moatMultiplier!).toBe(42.5);
    expect(result.score).toBe(42);
    expect(Math.round(50 * 0.85)).toBe(43);
  });
});

describe("computeOverallAssessment: random weight sets generated by the backend", () => {
  const cases: SharedCase[] = FIXTURE.parity_cases;
  it("covers many weight sets, every Moat state and every Narrow option", () => {
    expect(cases.length).toBeGreaterThanOrEqual(100);
    expect(new Set(cases.map((c) => JSON.stringify(c.weights))).size).toBeGreaterThanOrEqual(100);
    expect(new Set(cases.map((c) => c.moat))).toEqual(new Set(["wide_moat", "narrow_moat", "no_moat", null]));
    expect(new Set(cases.filter((c) => c.moat === "narrow_moat").map((c) => c.narrow_multiplier))).toEqual(new Set(NARROW_MOAT_MULTIPLIER_OPTIONS));
  });
  it("agrees with the backend on every one (status, score, verdict, Steps score, multiplier and note), bit for bit", () => {
    const wrong = cases.filter((c) => JSON.stringify(runCase(c)) !== JSON.stringify(c.expected)).map((c) => c.name);
    expect(wrong).toEqual([]);
  });
});

describe("computeOverallAssessment: custom weights", () => {
  const EQUAL: OverallBlendWeights = blendWeights({ financials: 25, growth: 25, profitability: 25, debt: 25 });
  const steps = [snapshot("step1", "S1", 90, "Pass"), snapshot("step2", "S2", 80, "Pass"), snapshot("step4", "S4", 70, "Pass"), snapshot("step5", "S5", 60, "Pass")];

  it("blends with the weights it is given", () => {
    const result = computeOverallAssessment(steps, "wide_moat", false, EQUAL);
    expect(result.stepsScore).toBe(75);
    expect(result.score).toBe(75);
    expect(result.breakdown[3].baseWeight).toBe(0.25);
  });

  it("is independent of the order the steps arrive in", () => {
    const shuffled = [steps[3], steps[1], steps[0], steps[2]];
    expect(computeOverallAssessment(shuffled, "wide_moat", false, EQUAL).stepsScore).toBe(computeOverallAssessment(steps, "wide_moat", false, EQUAL).stepsScore);
    // ...while the breakdown keeps the caller's order (it is what the card lists).
    expect(computeOverallAssessment(shuffled, "wide_moat", false, EQUAL).breakdown.map((b) => b.key)).toEqual(["step5", "step2", "step1", "step4"]);
  });

  it("the multiplier is independent of the weights: a perfect steps score is 100, 85 or 70 whatever the split", () => {
    for (const w of [{ financials: 50, growth: 5, profitability: 5, debt: 40 }, { financials: 10, growth: 50, profitability: 30, debt: 10 }]) {
      expect(computeOverallAssessment(BASE, "wide_moat", false, blendWeights(w)).score).toBe(100);
      expect(computeOverallAssessment(BASE, "narrow_moat", false, blendWeights(w)).score).toBe(85);
      expect(computeOverallAssessment(BASE, "no_moat", false, blendWeights(w)).score).toBe(70);
    }
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
