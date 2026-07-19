// Color is chosen from the numeric score, not the verdict string: 70-74
// and 75-90 both display the text "Pass" (see CLAUDE.md's "Scoring rubric
// deviations") but need different shades, so a verdict-keyed lookup can't
// tell them apart.
function classFor(score: number): string {
  if (score > 90) return "bg-emerald-900/40 text-emerald-300 border-emerald-700/40"; // Strong Pass
  if (score >= 75) return "bg-emerald-900/20 text-emerald-400 border-emerald-800/30"; // Pass (light green)
  if (score >= 70) return "bg-amber-900/40 text-amber-300 border-amber-700/40"; // Pass (neutral)
  return "bg-red-900/40 text-red-400 border-red-800/40"; // Fail
}

interface Props {
  score: number;
  verdict: string;
}

export function ScoreBadge({ score, verdict }: Props) {
  const cls = classFor(score);
  return (
    <span className={`inline-flex items-center gap-3 rounded-lg border px-4 py-2 ${cls}`}>
      <span className="font-mono text-3xl font-bold leading-none tabular-nums">{score}</span>
      <span className="text-sm font-semibold">{verdict}</span>
    </span>
  );
}
