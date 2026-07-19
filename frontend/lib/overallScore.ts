// Weights for the Overall Assessment card's weighted average across the 4
// currently-implemented steps. These sum to 100% and intentionally have no
// allocation for Step 3, which doesn't exist yet -- revisit once Step 3
// ships (the whole set will need rebalancing, not just adding a slice).
export const STEP_WEIGHTS = {
  step1: 0.35,
  step2: 0.22,
  step4: 0.28,
  step5: 0.15,
} as const;

export type StepKey = keyof typeof STEP_WEIGHTS;

export const IMPLEMENTED_STEPS = Object.keys(STEP_WEIGHTS).length;
export const TOTAL_METHODOLOGY_STEPS = 5;

export type StepStatus = "loading" | "ok" | "exempt" | "error" | "incomplete";

export interface StepSnapshot {
  key: StepKey;
  label: string;
  hasError: boolean;
  // undefined while the step's own data hasn't loaded yet.
  data: { score: number | null; verdict: string } | undefined;
}

export interface StepBreakdownEntry {
  key: StepKey;
  label: string;
  baseWeight: number;
  // The weight actually used in the calculation, renormalized across
  // applicable steps -- null when the step was excluded (exempt) or when no
  // score could be computed at all (incomplete/loading).
  effectiveWeight: number | null;
  score: number | null;
  verdict: string | null;
  status: StepStatus;
}

export interface OverallAssessment {
  status: "loading" | "complete" | "incomplete";
  score: number | null;
  verdict: "Strong Pass" | "Pass" | null;
  breakdown: StepBreakdownEntry[];
  incompleteSteps: string[];
  failingSteps: string[];
  assessedCount: number;
  totalMethodologySteps: number;
}

function statusFor(snapshot: StepSnapshot): StepStatus {
  if (snapshot.hasError) return "error";
  if (!snapshot.data) return "loading";
  if (snapshot.data.score === null) {
    // "not_supported" (currently only Step 5, for Banks -- CET1 data isn't
    // available from FMP) is a legitimate structural exemption. Any other
    // null-score verdict (e.g. "insufficient_data") means the figures this
    // ticker needed just weren't available -- that's missing data, not a
    // "doesn't apply" case, so it's treated the same as a fetch error.
    return snapshot.data.verdict === "not_supported" ? "exempt" : "incomplete";
  }
  return "ok";
}

/** Pure, framework-agnostic calculation so it's unit-testable without
 * mocking SWR/React -- the OverallAssessmentCard component is a thin wrapper
 * around this that supplies live hook data. */
export function computeOverallAssessment(steps: StepSnapshot[]): OverallAssessment {
  const withStatus = steps.map((s) => ({ ...s, status: statusFor(s) }));

  if (withStatus.some((s) => s.status === "loading")) {
    return {
      status: "loading",
      score: null,
      verdict: null,
      breakdown: withStatus.map((s) => ({
        key: s.key,
        label: s.label,
        baseWeight: STEP_WEIGHTS[s.key],
        effectiveWeight: null,
        score: null,
        verdict: null,
        status: s.status,
      })),
      incompleteSteps: [],
      failingSteps: [],
      assessedCount: IMPLEMENTED_STEPS,
      totalMethodologySteps: TOTAL_METHODOLOGY_STEPS,
    };
  }

  const incomplete = withStatus.filter((s) => s.status === "error" || s.status === "incomplete");
  const ok = withStatus.filter((s) => s.status === "ok");
  const totalWeight = ok.reduce((sum, s) => sum + STEP_WEIGHTS[s.key], 0);

  // A confident score requires every non-exempt step to have real data --
  // presenting a weighted average built on missing data would be
  // misleading, so this short-circuits to an explicit incomplete state
  // rather than silently computing a partial number.
  const canCompute = incomplete.length === 0 && totalWeight > 0;
  const score = canCompute
    ? Math.round(ok.reduce((sum, s) => sum + STEP_WEIGHTS[s.key] * (s.data!.score as number), 0) / totalWeight)
    : null;

  const failingSteps = ok.filter((s) => s.data!.verdict === "Fail").map((s) => s.label);

  return {
    status: canCompute ? "complete" : "incomplete",
    score,
    // No hard-fail override here -- deliberately a pure weighted average
    // (unlike every individual step). A low score just reads as a low
    // "Pass"; the failingSteps warning note is the separate, non-blocking
    // signal for "worth reviewing directly".
    verdict: score !== null ? (score > 90 ? "Strong Pass" : "Pass") : null,
    breakdown: withStatus.map((s) => ({
      key: s.key,
      label: s.label,
      baseWeight: STEP_WEIGHTS[s.key],
      effectiveWeight: canCompute && s.status === "ok" ? STEP_WEIGHTS[s.key] / totalWeight : null,
      score: s.data?.score ?? null,
      verdict: s.data?.verdict ?? null,
      status: s.status,
    })),
    incompleteSteps: canCompute ? [] : incomplete.map((s) => s.label),
    failingSteps,
    assessedCount: IMPLEMENTED_STEPS,
    totalMethodologySteps: TOTAL_METHODOLOGY_STEPS,
  };
}
