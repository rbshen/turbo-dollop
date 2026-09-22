import type { TrendAnalysisOut, WeinsteinPendingEtaScenarioOut, WeinsteinPendingOut } from "@/lib/api/types";

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

// ---------------------------------------------------------------------------
// "Pending confirmation" + ETA -- see docs/
// weinstein_pending_confirmation_investigation_2026-09-22.md for the full
// design and backend/analysis/trend_structure/weinstein_pending.py for the
// calculation this formats. All logic (never just presentation) lives here,
// matching the rest of this file's convention -- WeinsteinStagePill/
// WeinsteinStageCard stay thin renderers.
// ---------------------------------------------------------------------------

export type WeinsteinPendingDirection = WeinsteinPendingOut["direction"];
export type WeinsteinPendingScenarioKey = "flat" | "trend_5" | "trend_13";

// Same numbering convention as WEINSTEIN_STAGE_LABEL -- the stage a
// "pending_advance"/"pending_decline" flag is heading toward, not the
// ticker's current stage.
export const WEINSTEIN_PENDING_TARGET_LABEL: Record<WeinsteinPendingDirection, string> = {
  advance: "Stage 2 (Advance)",
  decline: "Stage 4 (Decline)",
};

// Order matters for display -- flat first (the literal ask), then the two
// momentum reads from most to least reactive.
export const WEINSTEIN_PENDING_SCENARIO_ORDER: WeinsteinPendingScenarioKey[] = ["flat", "trend_5", "trend_13"];

export const WEINSTEIN_PENDING_SCENARIO_LABEL: Record<WeinsteinPendingScenarioKey, string> = {
  flat: "If price holds near today's level (flat)",
  trend_5: "If price keeps its recent 5-week pace",
  trend_13: "If price keeps its recent 13-week pace",
};

const PROJECTION_HORIZON_WEEKS = 104; // mirrors weinstein_pending.py's own PROJECTION_HORIZON_WEEKS (2y)

// weeks_away=1 means "the next full weekly close," not exactly 7 calendar
// days -- the engine always treats the latest (possibly partial) week as
// "today" (see the design doc's caveat #4). Kept as plain "~N week(s) away"
// text rather than a calendar-day count for this reason.
export function formatWeinsteinPendingEtaScenario(scenario: WeinsteinPendingEtaScenarioOut, fmtDate: (iso: string) => string): string {
  if (scenario.horizon_exceeded) {
    // Round-2 validation finding (2026-09-22): this is NOT flat-specific --
    // any scenario whose assumed growth rate has the wrong sign/shape for
    // the pending direction can hit the identical "chase never converges"
    // shape once the projection window is fully synthetic (confirmed on
    // trend_5/trend_13 scenarios too, e.g. AXON/CDE/CTSH), so the wording
    // below deliberately says "under this assumption," never "under a flat
    // price."
    return scenario.band_lapsed_before_confirmation
      ? `Doesn't confirm within ${PROJECTION_HORIZON_WEEKS} weeks — under this assumption, an older price move ages out of the 30-week window before the trend math ever catches up.`
      : `Doesn't confirm within ${PROJECTION_HORIZON_WEEKS} weeks.`;
  }
  const weeks = scenario.weeks_away ?? 0;
  const weekWord = weeks === 1 ? "week" : "weeks";
  const dateSuffix = scenario.projected_date ? ` (week of ${fmtDate(scenario.projected_date)})` : "";
  return `~${weeks} ${weekWord} away${dateSuffix}`;
}

// Thin cushion = one ordinary-sized weekly move could un-clear the band
// (see weinstein_pending.py::_band_cushion_pct's own docstring).
export function weinsteinPendingCushionIsThin(pending: WeinsteinPendingOut): boolean {
  return (
    pending.band_cushion_pct != null && pending.typical_weekly_move_pct != null && pending.band_cushion_pct < pending.typical_weekly_move_pct
  );
}

export function formatWeinsteinPendingCushion(pending: WeinsteinPendingOut): string | null {
  if (pending.band_cushion_pct == null || pending.typical_weekly_move_pct == null) return null;
  const thinness = weinsteinPendingCushionIsThin(pending) ? "thin" : "comfortable";
  return `Band cushion: ${pending.band_cushion_pct >= 0 ? "+" : ""}${pending.band_cushion_pct.toFixed(1)}pp past threshold vs. a typical weekly move of ~${pending.typical_weekly_move_pct.toFixed(1)}pp (${thinness}).`;
}

// A "long" flat-scenario ETA, for the cushion-vs-ETA divergence note below --
// picked from the round-2 validation's own named divergence cases (JBL,
// IONQ, MPWR, TTWO), whose flat ETAs ran 8-10 weeks. Not a precise
// threshold, just the boundary past which a thin cushion reading
// "one bad week could erase this" alongside "but confirmation is still
// N weeks out" starts to look contradictory rather than merely cautious.
export const WEINSTEIN_PENDING_LONG_ETA_WEEKS = 8;

// The band-cushion diagnostic (price-level fragility) and the ETA
// (slope inertia) measure genuinely different things and can legitimately
// disagree for the same ticker -- confirmed on JBL/IONQ/MPWR/TTWO in
// the round-2 validation, all of which combine a razor-thin cushion with a
// long flat-scenario ETA because their current slope is still running hard
// in the OLD (non-pending) direction. Surfaced as its own note, distinct
// from the pending state itself, so it doesn't read as contradictory.
export function weinsteinPendingHasCushionEtaDivergence(pending: WeinsteinPendingOut): boolean {
  const flat = pending.eta.flat;
  if (!weinsteinPendingCushionIsThin(pending)) return false;
  if (!flat || flat.weeks_away == null) return false;
  return flat.weeks_away >= WEINSTEIN_PENDING_LONG_ETA_WEEKS;
}

export const WEINSTEIN_PENDING_CUSHION_ETA_DIVERGENCE_NOTE =
  "The cushion above looks thin, but the estimate below still runs several weeks out — these measure different things (how close price already is to the threshold, vs. how long the current MA slope trend takes to reverse) and can genuinely disagree for the same ticker. Neither reading is wrong.";

export const WEINSTEIN_PENDING_NOT_A_PREDICTION_NOTE =
  "These estimates say how long the slope math would need under each stated price assumption — not a forecast of what price will actually do.";

export const WEINSTEIN_PENDING_CANCELS_NOT_PAUSES_NOTE =
  "A move back under the band cancels the pending state outright rather than pausing the countdown — this can happen well before any of the estimates above.";

// The pill's own tooltip line -- kept short (a header pill's tooltip is
// plain text, not a rich block like the Technical tab's card). Only the
// flat scenario is surfaced here; the full 3-scenario breakdown lives on
// the Technical tab's WeinsteinStageCard instead.
export function weinsteinPendingTooltipLine(pending: WeinsteinPendingOut, fmtDate: (iso: string) => string): string {
  const flat = pending.eta.flat;
  const etaText = flat ? formatWeinsteinPendingEtaScenario(flat, fmtDate) : "";
  return `⚠ Pending ${WEINSTEIN_PENDING_TARGET_LABEL[pending.direction]} — price has cleared the band but the MA slope hasn't turned yet. ${etaText} (flat-price estimate; not a prediction).`;
}
