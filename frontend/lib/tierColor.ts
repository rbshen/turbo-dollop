// Shared score/verdict -> Tailwind color-class tiering, used by every card
// that renders a step's score or verdict as a color. Two shapes, same
// priority order and same Fail/caution/91+/75+/else tiers, so a step never
// reads as a different severity between its full badge and its summary
// chip:
//  - classFor: ScoreBadge's own full-badge styling (bg+border).
//  - flatChipClassFor: borderless summary-chip styling (TickerHeader's
//    Assessment chip, OverallAssessmentCard, WatchlistTable).

export function classFor(score: number, verdict: string): string {
  if (verdict === "Fail") return "bg-negative/16 text-negative border-negative/40";
  // "Pass with caution" (a Borderline breach excused by its tiebreaker, or
  // that flag propagated up from a contributing step into Overall
  // Assessment) must read as visually distinct from Fail, a plain Pass,
  // AND Strong Pass -- checked before the score-based tiers, same priority
  // as Fail, since a real breach occurred regardless of how high the
  // blended score is.
  if (verdict === "Pass with caution") return "bg-caution/16 text-caution border-caution/40";
  // Strong Pass (91-100) gets a deeper shade than a plain Pass (75-90) --
  // both used to share one "positive" token; positive-strong distinguishes
  // score magnitude instead of collapsing them.
  if (score > 90) return "bg-positive-strong/16 text-positive-strong border-positive-strong/40";
  if (score >= 75) return "bg-positive/16 text-positive border-positive/40";
  return "bg-warn/16 text-warn border-warn/40"; // Pass (neutral, 70-74)
}

// Text-only variant of classFor's same tiering -- for a plain verdict
// headline (Overall Assessment) where a full bg/border chip would look
// like an unwanted highlight box around the text.
export function textClassFor(score: number, verdict: string): string {
  if (verdict === "Fail") return "text-negative";
  if (verdict === "Pass with caution") return "text-caution";
  if (score > 90) return "text-positive-strong";
  if (score >= 75) return "text-positive";
  return "text-warn";
}

// score == null covers both "no score computed for this ticker/step" and
// "structurally exempt" (e.g. Step 5 not_supported for Banks) -- callers
// never have a real verdict to color without a score. Same tiers as
// classFor, borderless.
export function flatChipClassFor(score: number | null, verdict: string | null): string {
  if (score == null) return "bg-surface-2 text-text-tertiary";
  if (verdict === "Fail") return "bg-negative/16 text-negative";
  if (verdict === "Pass with caution") return "bg-caution/16 text-caution";
  if (score > 90) return "bg-positive-strong/16 text-positive-strong";
  if (score >= 75) return "bg-positive/16 text-positive";
  return "bg-warn/16 text-warn"; // Pass (70-74)
}
