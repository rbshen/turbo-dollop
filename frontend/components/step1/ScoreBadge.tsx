const VERDICT_STYLES: Record<string, string> = {
  "Strong Pass": "bg-emerald-900/40 text-emerald-300 border-emerald-700/40",
  "Pass with caution": "bg-amber-900/40 text-amber-300 border-amber-700/40",
  "May not pass — investigate": "bg-orange-900/40 text-orange-300 border-orange-700/40",
  Fail: "bg-red-900/40 text-red-400 border-red-800/40",
};

interface Props {
  score: number;
  verdict: string;
}

export function ScoreBadge({ score, verdict }: Props) {
  const cls = VERDICT_STYLES[verdict] ?? "bg-zinc-800 text-zinc-400 border-zinc-700/40";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-semibold ${cls}`}>
      <span className="font-mono tabular-nums">{score}</span>
      {verdict}
    </span>
  );
}
