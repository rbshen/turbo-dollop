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

// Shared 0-69/70-90/91-100 verdict bands used everywhere else in the app
// (see CLAUDE.md's "Scoring rubric deviations") -- must match backend
// scoring/overall.py::_verdict_for exactly.
export const STRONG_PASS_THRESHOLD = 90;
export const PASS_THRESHOLD = 70;

function verdictFor(score: number): "Strong Pass" | "Pass" | "Fail" {
  if (score > STRONG_PASS_THRESHOLD) return "Strong Pass";
  if (score >= PASS_THRESHOLD) return "Pass";
  return "Fail";
}

export const IMPLEMENTED_STEPS = Object.keys(STEP_WEIGHTS).length;
export const TOTAL_METHODOLOGY_STEPS = 5;

// Once a ticker has an Economic Moat set (any of the 3 real states -- "not
// set" is unaffected and uses the pure Steps 1/2/4/5 blend above, untouched),
// Steps 1+2+4+5 combined occupy 69% of Overall Assessment and Moat occupies
// the other 31%. Mirrors backend/scoring/overall.py::MOAT_WEIGHT exactly --
// see STEP_WEIGHTS's own comment above on why these two implementations must
// never drift.
export const MOAT_WEIGHT = 0.31;

export type MoatValue = "no_moat" | "narrow_moat" | "wide_moat";

export const MOAT_LABELS: Record<MoatValue, string> = {
  no_moat: "No Moat",
  narrow_moat: "Narrow Moat",
  wide_moat: "Wide Moat",
};

export interface MoatSnapshot {
  moat: MoatValue;
  // Resolved point value (0-100) from MoatScoreConfig for this moat state --
  // callers resolve this before calling computeOverallAssessment.
  score: number;
}

export type StepStatus = "loading" | "ok" | "exempt" | "error" | "incomplete";

export interface StepSnapshot {
  key: StepKey;
  label: string;
  hasError: boolean;
  // undefined while the step's own data hasn't loaded yet.
  data: { score: number | null; verdict: string } | undefined;
}

export interface StepBreakdownEntry {
  key: StepKey | "moat";
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
  verdict: "Strong Pass" | "Pass" | "Fail" | null;
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
 * around this that supplies live hook data.
 *
 * `moat`: omitted/`undefined` or `null` both mean confirmed "not set" (the
 * default -- byte-identical to the pre-Moat behavior below, and the
 * omitted-arg form every existing call site/test uses); a `MoatSnapshot`
 * means a moat is set and its point value has been resolved. `moatLoading`
 * is a SEPARATE flag (default `false`, so omitting it never changes
 * existing behavior) the caller sets while its moat/moat-config SWR hooks
 * haven't settled yet -- kept distinct from `moat` itself so "not set" and
 * "still loading" can't be confused the way overloading `undefined` for
 * both would. Once resolved, Moat is applied as a SECOND stage on top of
 * the Steps 1/2/4/5 blend (`0.69 * stepsScore + 0.31 * moat.score`), not
 * folded into a single flat weight table -- mirrors
 * backend/scoring/overall.py::compute_overall_assessment exactly; see that
 * module's docstring for why a flat renormalization doesn't reduce to this
 * formula once a step is also exempt/missing. */
export function computeOverallAssessment(
  steps: StepSnapshot[],
  moat?: MoatSnapshot | null,
  moatLoading = false
): OverallAssessment {
  const withStatus = steps.map((s) => ({ ...s, status: statusFor(s) }));

  if (withStatus.some((s) => s.status === "loading") || moatLoading) {
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
  const stepsScore = canCompute
    ? Math.round(ok.reduce((sum, s) => sum + STEP_WEIGHTS[s.key] * (s.data!.score as number), 0) / totalWeight)
    : null;

  const failingSteps = ok.filter((s) => s.data!.verdict === "Fail").map((s) => s.label);

  let score: number | null;
  let displayScale: number;
  if (!moat) {
    score = stepsScore;
    displayScale = 1;
  } else if (stepsScore === null) {
    score = null;
    displayScale = 1 - MOAT_WEIGHT;
  } else {
    score = Math.round((1 - MOAT_WEIGHT) * stepsScore + MOAT_WEIGHT * moat.score);
    displayScale = 1 - MOAT_WEIGHT;
  }

  const breakdown: StepBreakdownEntry[] = withStatus.map((s) => ({
    key: s.key,
    label: s.label,
    baseWeight: STEP_WEIGHTS[s.key],
    effectiveWeight: canCompute && s.status === "ok" ? (STEP_WEIGHTS[s.key] / totalWeight) * displayScale : null,
    score: s.data?.score ?? null,
    verdict: s.data?.verdict ?? null,
    status: s.status,
  }));
  if (moat) {
    breakdown.push({
      key: "moat",
      label: "Economic Moat",
      baseWeight: MOAT_WEIGHT,
      effectiveWeight: score !== null ? MOAT_WEIGHT : null,
      score: moat.score,
      // Deliberately not "Pass"/"Fail" text -- keeps Moat out of
      // failingSteps above, which filters on verdict === "Fail".
      verdict: MOAT_LABELS[moat.moat],
      status: "ok",
    });
  }

  return {
    status: canCompute ? "complete" : "incomplete",
    score,
    // No hard-fail override among the 4 computed steps themselves --
    // deliberately a pure weighted average there; the failingSteps warning
    // note is the separate, non-blocking signal for "worth reviewing
    // directly". Moat is the one deliberate exception: since it's
    // user-asserted, not computed, a No Moat score of 0 combined with the
    // 69/31 split can cap the overall score below the 70 Pass threshold
    // regardless of how the 4 steps blend -- that's intended, not a bug.
    // The verdict BAND, though, must match the shared bands used everywhere
    // else in the app -- a score under 70 showing "Pass" was a bug.
    verdict: score !== null ? verdictFor(score) : null,
    breakdown,
    incompleteSteps: canCompute ? [] : incomplete.map((s) => s.label),
    failingSteps,
    assessedCount: IMPLEMENTED_STEPS,
    totalMethodologySteps: TOTAL_METHODOLOGY_STEPS,
  };
}
