import type { TrendAnalysisOut } from "@/lib/api/types";

export type WeinsteinStage = NonNullable<TrendAnalysisOut["weinstein_stage"]>;

// "Stage N" numbering follows Stan Weinstein's own convention (1=Base,
// 2=Advance, 3=Top, 4=Decline) -- shown alongside the plain-English name
// since that numbering is what most readers of the original methodology
// will recognize first.
export const WEINSTEIN_STAGE_LABEL: Record<WeinsteinStage, string> = {
  base: "Stage 1 · Base",
  advance: "Stage 2 · Advance",
  top: "Stage 3 · Top",
  decline: "Stage 4 · Decline",
};

// advance=positive(green)/decline=negative(red) are the two directional
// extremes; top reuses the same amber `warn` token TrendContinuationCard's
// "pullback pending" state already uses (a caution, not yet a reversal);
// base is deliberately colorless -- reuses ReversalCard's exact "Not
// present" neutral precedent, since a base isn't bullish OR bearish.
export const WEINSTEIN_STAGE_STYLES_CHIP: Record<WeinsteinStage, string> = {
  advance: "bg-positive/16 text-positive border-positive/40",
  decline: "bg-negative/16 text-negative border-negative/40",
  top: "border-warn/40 bg-warn/16 text-warn",
  base: "border-border-card bg-surface-2 text-text-tertiary",
};

export const WEINSTEIN_STAGE_STYLES_FLAT: Record<WeinsteinStage, string> = {
  advance: "bg-positive/16 text-positive",
  decline: "bg-negative/16 text-negative",
  top: "bg-warn/16 text-warn",
  base: "bg-surface-2 text-text-tertiary",
};

// Plain text-color-only variant, for SummaryStrip's value text (no
// background/pill chrome there, matching how the Trend stat is colored).
export const WEINSTEIN_STAGE_TEXT_CLASS: Record<WeinsteinStage, string> = {
  advance: "text-positive",
  decline: "text-negative",
  top: "text-warn",
  base: "text-text-tertiary",
};

// "since [date]" vs "since at least [date]" -- the lower-bound flag means
// the stage never changed anywhere in the available (post-bootstrap)
// weekly history, so the true start predates the fetch window and this
// date is a floor, not a precise transition date.
export function formatWeinsteinSince(sinceDate: string, isLowerBound: boolean, fmtDate: (iso: string) => string): string {
  return isLowerBound ? `Since at least ${fmtDate(sinceDate)}` : `Since ${fmtDate(sinceDate)}`;
}

// Same data-visibility caveat wording as NearTermCard.tsx's
// TREND_STARTED_LOWER_BOUND_CAVEAT, for the identical shape of problem on a
// different lens (weekly stage vs. daily trend) -- shown alongside
// formatWeinsteinSince's "at least" framing wherever isLowerBound is true,
// so both "since" readings a user might encounter on this tab explain
// themselves the same way rather than one being a bare, unexplained date.
export const WEINSTEIN_LOWER_BOUND_CAVEAT =
  "Data starts here — the stage may have begun earlier than our price history shows.";

// Distinguishes WHY weinstein_stage is null -- found necessary after a real
// incident (CTAS/ABNB, 2026-09-06) where a stale, never-reprocessed row's
// null stage was indistinguishable in the UI from a genuine data gap, even
// though both tickers had years of real cached history. weinstein_weeks_available
// is null ONLY when this row has never been touched by a Weinstein-aware
// compute at all (a legacy/never-reprocessed row); a real (always sub-40)
// number means a compute genuinely ran and found too little history --
// see backend's models.py::TrendAnalysis for the full mechanism.
export type WeinsteinUnavailableReason = "not_yet_computed" | "insufficient_history";

export function weinsteinUnavailableReason(weeksAvailable: number | null): WeinsteinUnavailableReason {
  return weeksAvailable == null ? "not_yet_computed" : "insufficient_history";
}
