import { pySum, roundHalfEven } from "@/lib/pyNumeric";

// Overall Assessment = Fundamentals score x Moat multiplier: a TypeScript mirror of backend/scoring/overall.py::compute_overall_assessment. The Fundamentals
// score is the weighted blend of the four automated steps (Financials, Growth Rate, Profitability, Debt), kept unrounded; Economic Moat is not
// a blend component, it scales that score, and Overall is rounded once, after the multiplication. The step weights are the saved set
// (GET /api/config/score-weights, hook useScoreWeights), whole numbers adding up to `overallTotal` (100), passed in by the caller so the
// backend's scoring/weights.py stays the one definition; the Narrow multiplier is the saved setting (GET /api/config/moat). Both
// implementations read the shared fixture backend/tests/fixtures/overall_verdict_cases.json.
export interface OverallWeights {
  financials: number;
  growth: number;
  profitability: number;
  debt: number;
}

export interface OverallBlendWeights {
  overall: OverallWeights;
  /** What the four overall weights add up to (100). */
  overallTotal: number;
}

const STEP_WEIGHT_FIELD = { step1: "financials", step2: "growth", step4: "profitability", step5: "debt" } as const;

/** The canonical step order the backend always blends in. Floating-point addition is order-dependent, so the blend never follows
 * the caller's array order. */
const STEP_ORDER = ["step1", "step2", "step4", "step5"] as const;

export type StepKey = (typeof STEP_ORDER)[number];

function stepFraction(weights: OverallBlendWeights, key: StepKey): number {
  return weights.overall[STEP_WEIGHT_FIELD[key]] / weights.overallTotal;
}

function inCanonicalOrder<T extends { key: StepKey }>(items: T[]): T[] {
  return [...items].sort((a, b) => STEP_ORDER.indexOf(a.key) - STEP_ORDER.indexOf(b.key));
}

// Moat multipliers. Wide and No moat are fixed (backend scoring/overall.py::WIDE_MOAT_MULTIPLIER / NO_MOAT_MULTIPLIER); Narrow is the
// saved setting, one of NARROW_MOAT_MULTIPLIER_OPTIONS (default 0.85). A ticker with Moat unset is scored as No moat.
export const WIDE_MOAT_MULTIPLIER = 1.0;
export const NO_MOAT_MULTIPLIER = 0.7;
export const NARROW_MOAT_MULTIPLIER_OPTIONS = [0.8, 0.82, 0.85, 0.87, 0.9] as const;
export const DEFAULT_NARROW_MOAT_MULTIPLIER = 0.85;

// Shown beside the verdict when Moat is unset. Mirrors backend/scoring/overall.py::MOAT_NOT_RATED_NOTE.
export const MOAT_NOT_RATED_NOTE = "Moat not rated, scored as No moat";

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

export type MoatValue = "no_moat" | "narrow_moat" | "wide_moat";

export const MOAT_LABELS: Record<MoatValue, string> = {
  no_moat: "No Moat",
  narrow_moat: "Narrow Moat",
  wide_moat: "Wide Moat",
};

/** The multiplier for a Moat state (null/undefined = unset = No moat) under the saved Narrow setting. */
export function moatMultiplier(moat: MoatValue | null | undefined, narrowMultiplier: number = DEFAULT_NARROW_MOAT_MULTIPLIER): number {
  if (moat === "wide_moat") return WIDE_MOAT_MULTIPLIER;
  if (moat === "narrow_moat") return narrowMultiplier;
  return NO_MOAT_MULTIPLIER;
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
  key: StepKey;
  label: string;
  baseWeight: number;
  // The weight actually used in the calculation, renormalized across
  // applicable steps (they add up to 1) -- null when the step was excluded
  // (exempt) or when no score could be computed at all (incomplete/loading).
  effectiveWeight: number | null;
  score: number | null;
  verdict: string | null;
  status: StepStatus;
}

export interface OverallAssessment {
  status: "loading" | "complete" | "incomplete";
  /** Overall: round(stepsScore x moatMultiplier), rounded once. */
  score: number | null;
  /** The weighted blend of the steps, UNROUNDED (show one decimal). null when loading or incomplete. */
  stepsScore: number | null;
  /** The multiplier applied (1.0 / the saved Narrow value / 0.7). null when loading or incomplete. */
  moatMultiplier: number | null;
  verdict: "Strong Pass" | "Pass" | "Pass with caution" | "Fail" | null;
  /** The Moat rating the multiplier came from (null = unset, scored as No moat). */
  moat: MoatValue | null;
  /** MOAT_NOT_RATED_NOTE when Moat is unset (complete assessments only); null otherwise. */
  moatNote: string | null;
  breakdown: StepBreakdownEntry[];
  incompleteSteps: string[];
  failingSteps: string[];
  // Steps whose verdict is "Pass with caution" (currently only Step 5's
  // Borderline-breach-excused-by-tiebreaker state) -- a real breach
  // occurred, so this is surfaced separately from failingSteps rather than
  // silently blending into a plain Pass.
  cautionSteps: string[];
  /** Steps below the pass line (score under 70, or a stored "Fail" verdict): "May not pass". Exempt steps are never in it. Listed
   * whatever the Overall verdict; it only drives the caution when the Overall passes. */
  weakSteps: string[];
  /** Why the verdict reads "Pass with caution" (empty for every other verdict): "step_caution" (a step's own caution flag) and/or
   * "weak_step" (a step below the pass line beside an Overall of 70 or more). Both can apply. */
  cautionReasons: CautionReason[];
}

export type CautionReason = "step_caution" | "weak_step";

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

/** `weights` is the saved set (see OverallBlendWeights). The rounding and the summation order are the backend's exactly (pyNumeric.ts),
 * including its half-to-even rounding of an exact .5, so the live Analysis tab and the stored Screener row agree to the point.
 *
 * Pure, framework-agnostic calculation so it's unit-testable without
 * mocking SWR/React -- the OverallAssessmentCard component is a thin wrapper
 * around this that supplies live hook data.
 *
 * `moat`: omitted/`undefined` or `null` both mean confirmed "not set" (scored as No moat, with the note). `moatLoading` is a SEPARATE
 * flag the caller sets while its Moat reads (the ticker's rating, and the Narrow setting when it is Narrow) haven't settled yet --
 * kept distinct from `moat` itself so "not set" and "still loading" can't be confused. `narrowMultiplier` is the saved Narrow setting
 * (only read for a Narrow rating). Fundamentals score = the weighted average of the steps that apply (an exempt "not_supported" step is
 * excluded and the rest reweighted; any step with missing data makes the whole assessment incomplete, which no Moat rating can
 * rescue), unrounded; Overall = round(fundamentals score x multiplier). No cap and no hard-fail override: the verdict is read from the Overall
 * score; a Pass or Strong Pass reads "Pass with caution" when a step carries its own caution flag or any step is below the pass line. Mirrors
 * backend/scoring/overall.py::compute_overall_assessment exactly. */
export function computeOverallAssessment(
  steps: StepSnapshot[],
  moat: MoatValue | null | undefined,
  moatLoading: boolean,
  weights: OverallBlendWeights,
  narrowMultiplier: number = DEFAULT_NARROW_MOAT_MULTIPLIER
): OverallAssessment {
  // The breakdown keeps the caller's order (it is what the card lists); only the arithmetic below runs in canonical order.
  const withStatus = steps.map((s) => ({ ...s, status: statusFor(s) }));

  if (withStatus.some((s) => s.status === "loading") || moatLoading) {
    return {
      status: "loading",
      score: null,
      stepsScore: null,
      moatMultiplier: null,
      verdict: null,
      moat: moat ?? null,
      moatNote: null,
      breakdown: withStatus.map((s) => ({
        key: s.key,
        label: s.label,
        baseWeight: stepFraction(weights, s.key),
        effectiveWeight: null,
        score: null,
        verdict: null,
        status: s.status,
      })),
      incompleteSteps: [],
      failingSteps: [],
      cautionSteps: [],
      weakSteps: [],
      cautionReasons: [],
    };
  }

  const incomplete = withStatus.filter((s) => s.status === "error" || s.status === "incomplete");
  const ok = inCanonicalOrder(withStatus.filter((s) => s.status === "ok"));
  const totalWeight = pySum(ok.map((s) => stepFraction(weights, s.key)));

  // A confident score requires every non-exempt step to have real data --
  // presenting a weighted average built on missing data would be
  // misleading, so this short-circuits to an explicit incomplete state
  // rather than silently computing a partial number.
  const canCompute = incomplete.length === 0 && totalWeight > 0;
  const stepsScore = canCompute ? pySum(ok.map((s) => stepFraction(weights, s.key) * (s.data!.score as number))) / totalWeight : null;
  const multiplier = canCompute ? moatMultiplier(moat, narrowMultiplier) : null;
  const score = stepsScore !== null && multiplier !== null ? roundHalfEven(stepsScore * multiplier) : null;

  const failingSteps = ok.filter((s) => s.data!.verdict === "Fail").map((s) => s.label);
  const cautionSteps = ok.filter((s) => s.data!.verdict === "Pass with caution").map((s) => s.label);
  const weakSteps = ok.filter((s) => s.data!.verdict === "Fail" || (s.data!.score as number) < PASS_THRESHOLD).map((s) => s.label);

  const breakdown: StepBreakdownEntry[] = withStatus.map((s) => ({
    key: s.key,
    label: s.label,
    baseWeight: stepFraction(weights, s.key),
    effectiveWeight: canCompute && s.status === "ok" ? stepFraction(weights, s.key) / totalWeight : null,
    score: s.data?.score ?? null,
    verdict: s.data?.verdict ?? null,
    status: s.status,
  }));

  // The verdict BAND must match the shared bands used everywhere else in the app.
  const scoreVerdict = score !== null ? verdictFor(score) : null;
  // Two triggers turn an otherwise-green Pass/Strong Pass into "Pass with caution": a step's own "Pass with caution" flag, and (since
  // 2026-10-08) a step below the pass line that the other steps outweighed. Fail stays Fail (already the strongest signal).
  // This changes only the DISPLAYED verdict; `score` above is untouched.
  const passing = scoreVerdict !== null && scoreVerdict !== "Fail";
  const cautionReasons: CautionReason[] = passing
    ? [...(cautionSteps.length > 0 ? (["step_caution"] as const) : []), ...(weakSteps.length > 0 ? (["weak_step"] as const) : [])]
    : [];
  const verdict: OverallAssessment["verdict"] = cautionReasons.length > 0 ? "Pass with caution" : scoreVerdict;

  return {
    status: canCompute ? "complete" : "incomplete",
    score,
    stepsScore,
    moatMultiplier: multiplier,
    verdict,
    moat: moat ?? null,
    moatNote: !moat && canCompute ? MOAT_NOT_RATED_NOTE : null,
    breakdown,
    incompleteSteps: canCompute ? [] : incomplete.map((s) => s.label),
    failingSteps,
    cautionSteps,
    weakSteps,
    cautionReasons,
  };
}
