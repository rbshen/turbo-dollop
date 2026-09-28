import { TONE_TEXT_CLASS, Verdict } from "@/components/ui/status";
import { toneFor } from "@/lib/tierColor";

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

// No rectangle/background -- ScreenerCard's own compact score readout:
// score number stacked above its verdict, both right-aligned, colored
// (not boxed) by tier. Doesn't fit Status/Verdict's own single-line
// dot+word shape (a large 3xl score number and a small verdict word on
// separate lines), so the verdict word alone renders via Verdict while the
// score number shares its color from the same tone via the shared
// TONE_TEXT_CLASS map -- one color source either way, not two.
export function ScoreBadge({ score, verdict }: Props) {
  const tone = toneFor(score, verdict);
  return (
    <div className={`flex shrink-0 flex-col items-end text-right ${TONE_TEXT_CLASS[tone]}`}>
      <span className="font-mono text-3xl font-bold leading-none tabular-nums">{score}</span>
      <Verdict tone={tone} className="text-sm font-semibold leading-tight">
        {verdict}
      </Verdict>
    </div>
  );
}
