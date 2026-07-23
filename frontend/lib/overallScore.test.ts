import { describe, expect, it } from "vitest";

import { computeOverallAssessment, type MoatSnapshot, type StepSnapshot } from "@/lib/overallScore";

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
    // 90*0.35 + 80*0.22 + 70*0.28 + 60*0.15 = 31.5 + 17.6 + 19.6 + 9 = 77.7 -> 78
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("complete");
    expect(result.score).toBe(78);
    expect(result.verdict).toBe("Pass");
  });

  it("all steps at 100 scores exactly 100, Strong Pass", () => {
    const result = computeOverallAssessment(BASE);
    expect(result.score).toBe(100);
    expect(result.verdict).toBe("Strong Pass");
  });

  it("renormalizes weights when a step is structurally exempt (not_supported)", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 90, "Pass"),
      snapshot("step2", "Step 2", 90, "Pass"),
      snapshot("step4", "Step 4", 90, "Pass"),
      snapshot("step5", "Step 5", null, "not_supported"),
    ];
    // Step 5 excluded; remaining weights (0.35+0.22+0.28=0.85) renormalize
    // to sum to 1 -- since all 3 remaining scores are equal (90), the
    // renormalized weighted average is still exactly 90 regardless of the
    // individual renormalized weights.
    const result = computeOverallAssessment(steps);
    expect(result.status).toBe("complete");
    expect(result.score).toBe(90);
    const step5Entry = result.breakdown.find((b) => b.key === "step5")!;
    expect(step5Entry.status).toBe("exempt");
    expect(step5Entry.effectiveWeight).toBeNull();
    const step1Entry = result.breakdown.find((b) => b.key === "step1")!;
    expect(step1Entry.effectiveWeight).toBeCloseTo(0.35 / 0.85, 5);
  });

  it("renormalization actually shifts the score when remaining scores differ", () => {
    const steps: StepSnapshot[] = [
      snapshot("step1", "Step 1", 100, "Strong Pass"),
      snapshot("step2", "Step 2", 0, "Fail"),
      snapshot("step4", "Step 4", 100, "Strong Pass"),
      snapshot("step5", "Step 5", null, "not_supported"),
    ];
    // Without step5: (100*0.35 + 0*0.22 + 100*0.28) / (0.35+0.22+0.28)
    // = 63 / 0.85 = 74.117... -> 74
    const result = computeOverallAssessment(steps);
    expect(result.score).toBe(74);
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
    expect(result.score).toBe(round(90 * 0.35 + 90 * 0.22 + 90 * 0.28 + 0 * 0.15));
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
    expect(result.verdict).toBe("Pass");
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
    expect(result.verdict).toBe("Pass"); // 90 is the Pass/Strong Pass boundary
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
