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
  if (verdict === "Fail") return "bg-red-900/40 text-red-400 border-red-800/40";
  // Step 5's "Pass with caution" (a Borderline breach excused by its
  // tiebreaker) must read as visually distinct from BOTH a clean Pass and
  // a Fail -- checked before the score-based tiers, same priority as Fail,
  // since a real breach occurred regardless of how high the blended score is.
  if (verdict === "Pass with caution") return "bg-amber-900/30 text-amber-400 border-amber-700/50";
  if (score > 90) return "bg-emerald-900/40 text-emerald-300 border-emerald-700/40"; // Strong Pass
  if (score >= 75) return "bg-emerald-900/20 text-emerald-400 border-emerald-800/30"; // Pass (light green)
  return "bg-amber-900/40 text-amber-300 border-amber-700/40"; // Pass (neutral)
}

// score == null covers both "no score computed for this ticker/step" and
// "structurally exempt" (e.g. Step 5 not_supported for Banks) -- callers
// never have a real verdict to color without a score.
export function chipClassFor(score: number | null, verdict: string | null): string {
  if (score == null) return "border-zinc-800 bg-zinc-900 text-zinc-600";
  if (verdict === "Fail") return "border-red-800/40 bg-red-900/20 text-red-400";
  if (verdict === "Pass with caution") return "border-amber-700/50 bg-amber-900/20 text-amber-400";
  if (score > 90) return "border-emerald-700/40 bg-emerald-900/20 text-emerald-300";
  return "border-zinc-700 bg-zinc-800/60 text-zinc-300";
}
