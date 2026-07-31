import { classFor } from "@/lib/tierColor";

// Color depends on both verdict and score: 70-74 and 75-90 both display
// the text "Pass" (see CLAUDE.md's "Scoring rubric deviations") but need
// different shades, so color can't be chosen from verdict text alone.
// Conversely, Fail must override the score-based tiers rather than being
// derived from them -- Step 2's Fail is gated on projected growth being
// negative, not on the blended score, so a "Pass" verdict can occur at any
// score (e.g. positive-but-modest growth dragged down by analyst
// disagreement) and must never render red. See lib/tierColor.ts for the
// exact tiering, shared with ScreenerCard/OverallAssessmentCard's chips.

interface Props {
  score: number;
  verdict: string;
}

export function ScoreBadge({ score, verdict }: Props) {
  const cls = classFor(score, verdict);
  return (
    <span className={`inline-flex items-center gap-3 rounded-lg border px-4 py-2 ${cls}`}>
      <span className="font-mono text-3xl font-bold leading-none tabular-nums">{score}</span>
      <span className="text-sm font-semibold">{verdict}</span>
    </span>
  );
}
