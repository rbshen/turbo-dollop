import { textClassFor } from "@/lib/tierColor";

// Color depends on both verdict and score: 70-74 and 75-90 both display
// the text "Pass" (see CLAUDE.md's "Scoring rubric deviations") but need
// different shades, so color can't be chosen from verdict text alone.
// Conversely, Fail must override the score-based tiers rather than being
// derived from them -- Step 2's Fail is gated on projected growth being
// negative, not on the blended score, so a "Pass" verdict can occur at any
// score (e.g. positive-but-modest growth dragged down by analyst
// disagreement) and must never render red. See lib/tierColor.ts for the
// exact tiering, shared with ScreenerCard's flat score/OverallAssessmentCard's
// headline.

interface Props {
  score: number;
  verdict: string;
}

// No rectangle/background -- ScreenerCard's own compact score readout:
// score number stacked above its verdict, both right-aligned, colored
// (not boxed) by tier.
export function ScoreBadge({ score, verdict }: Props) {
  const cls = textClassFor(score, verdict);
  return (
    <div className={`flex shrink-0 flex-col items-end text-right ${cls}`}>
      <span className="font-mono text-3xl font-bold leading-none tabular-nums">{score}</span>
      <span className="text-sm font-semibold leading-tight">{verdict}</span>
    </div>
  );
}
