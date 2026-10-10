// Display helpers for the Dashboard tab (docs/specs/dashboard.md). Pure. Nothing here recomputes a verdict: a step pill is the STORED
// score and verdict drawn with the app's existing label helpers, exactly as the header and the Screener draw them.
import type { StatusTone } from "@/components/ui/status";
import type { DashboardDebtRatio, DashboardFairValue } from "@/lib/api/types";
import { debtVerdictDisplay, toneForNullable, verdictLabel } from "@/lib/tierColor";

export interface StepPill {
  tone: StatusTone;
  label: string;
  /** The stored score shown beside the pill; null when there is none. */
  score: number | null;
}

// A stored step verdict that is not a scored result: insufficient data, or Debt "not supported" (Bank without CET1, Insurance).
const NOT_SCORED_VERDICTS = new Set(["insufficient_data", "not_supported"]);

/** The pill for one scored step from its stored score and verdict. Missing or insufficient_data reads the neutral "Not scored". */
export function stepPill(score: number | null | undefined, verdict: string | null | undefined, kind: "default" | "debt" = "default"): StepPill {
  if (score == null || !verdict || NOT_SCORED_VERDICTS.has(verdict)) return { tone: "neutral", label: "Not scored", score: null };
  return {
    tone: toneForNullable(score, verdict),
    label: kind === "debt" ? debtVerdictDisplay(verdict) : verdictLabel(verdict),
    score,
  };
}

/** Money and ratio formats for the gauges. */
export const fmtRatioX = (n: number): string => `${n.toFixed(2)}x`;
export const fmtPct1 = (n: number): string => `${n.toFixed(1)}%`;
export const fmtPctWhole = (n: number): string => (Number.isInteger(n) ? `${n}%` : `${n.toFixed(1)}%`);

export function debtFormat(unit: DashboardDebtRatio["unit"]): (n: number) => string {
  return unit === "x" ? fmtRatioX : fmtPct1;
}

const CFO_EXEMPT_NOUN: Record<string, string> = {
  Bank: "a bank",
  Insurance: "an insurer",
  "Property Developer": "a REIT or property developer",
  "Commodity Company": "a commodity company",
};

/** "Not scored for a bank: revenue and net income only" for the exempt Step 1 types; null when CFO is scored. */
export function cfoNotScoredText(reason: string | null): string | null {
  if (!reason) return null;
  return `Not scored for ${CFO_EXEMPT_NOUN[reason] ?? reason.toLowerCase()}: revenue and net income only`;
}

/** Why there is no fair value, in plain words. */
export function fairValueUnavailableText(fv: Pick<DashboardFairValue, "unavailable_reason" | "unavailable_detail">): string {
  switch (fv.unavailable_reason) {
    case "pass_method":
      return fv.unavailable_detail ? `no valuation method applies (${fv.unavailable_detail.replace(/\.$/, "")})` : "no valuation method applies to this company";
    case "insufficient_data":
      return "there is not enough cached history to value it";
    case "no_price":
      return "there is no price to compare with";
    case "not_scored":
      return "it has not been scored yet";
    default:
      return "none is available";
  }
}

/** The growth basis in words ("EPS" / "revenue"). */
export function growthBasisText(basis: string | null): string {
  return basis === "eps" ? "EPS" : basis === "revenue" ? "revenue" : "analyst";
}
