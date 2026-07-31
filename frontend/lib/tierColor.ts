// Shared score/verdict -> Tailwind color-class tiering, used by every card
// that renders a step's score or verdict as a color. Two shapes, same
// priority order (Fail -> Pass with caution -> score>90 -> else) so a step
// never reads as a different severity between its full badge and its
// summary chip:
//  - classFor: ScoreBadge's own full-badge styling (splits the score-based
//    tiers into Strong Pass / light-green Pass / neutral Pass).
//  - chipClassFor: small summary-chip styling (ScreenerCard,
//    OverallAssessmentCard) -- fewer visual tiers, no split within Pass.

export function classFor(score: number, verdict: string): string {
  if (verdict === "Fail") return "bg-negative/16 text-negative border-negative/40";
  // Step 5's "Pass with caution" (a Borderline breach excused by its
  // tiebreaker) must read as visually distinct from BOTH a clean Pass and
  // a Fail -- checked before the score-based tiers, same priority as Fail,
  // since a real breach occurred regardless of how high the blended score is.
  if (verdict === "Pass with caution") return "bg-warn/16 text-warn border-warn/40";
  // Strong Pass and Pass (75-90) share the design system's one "positive"
  // token (the mockup's own Screener scale collapses both into the same
  // green too) -- Pass (70-74) reuses "warn" so the amber/green split this
  // app's rubric intentionally keeps within the Pass band (see CLAUDE.md)
  // survives with only the 3 semantic tokens the v2 palette defines.
  if (score >= 75) return "bg-positive/16 text-positive border-positive/40";
  return "bg-warn/16 text-warn border-warn/40"; // Pass (neutral, 70-74)
}

// Text-only variant of classFor's same tiering -- for a plain verdict
// headline (Overall Assessment) where a full bg/border chip would look
// like an unwanted highlight box around the text.
export function textClassFor(score: number, verdict: string): string {
  if (verdict === "Fail") return "text-negative";
  if (verdict === "Pass with caution") return "text-warn";
  if (score >= 75) return "text-positive";
  return "text-warn";
}

// score == null covers both "no score computed for this ticker/step" and
// "structurally exempt" (e.g. Step 5 not_supported for Banks) -- callers
// never have a real verdict to color without a score.
export function chipClassFor(score: number | null, verdict: string | null): string {
  if (score == null) return "border-border-input bg-surface-2 text-text-tertiary";
  if (verdict === "Fail") return "border-negative/40 bg-negative/16 text-negative";
  if (verdict === "Pass with caution") return "border-warn/40 bg-warn/16 text-warn";
  if (score > 90) return "border-positive/40 bg-positive/16 text-positive";
  return "border-border-input bg-surface-2 text-text-secondary";
}
