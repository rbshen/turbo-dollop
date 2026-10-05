import { Verdict } from "@/components/ui/status";
import { toneFor, verdictLabel } from "@/lib/tierColor";

// Color depends on both verdict and score: 70-74 and 75-90 both display
// the text "Pass" (see CLAUDE.md's "Scoring rubric deviations") but need
// different shades, so color can't be chosen from verdict text alone.
// Conversely, Fail must override the score-based tiers rather than being
// derived from them -- Step 2's Fail is gated on projected growth being
// negative, not on the blended score, so a "Pass" verdict can occur at any
// score (e.g. positive-but-modest growth dragged down by analyst
// disagreement) and must never render red. See lib/tierColor.ts for the
// exact tiering, shared with OverallAssessmentCard's headline.

interface Props {
  score: number;
  verdict: string;
}

// ScreenerCard's compact score readout: the score number stacked above its
// verdict pill, both right-aligned. The number is neutral (text-primary) --
// the pill alone carries the tone (docs/design-system.md, "Pills").
export function ScoreBadge({ score, verdict }: Props) {
  return (
    <div className="flex shrink-0 flex-col items-end gap-1 text-right">
      <span className="font-mono text-3xl font-bold leading-none tabular-nums text-text-primary">{score}</span>
      <Verdict tone={toneFor(score, verdict)}>{verdictLabel(verdict)}</Verdict>
    </div>
  );
}
