import { classFor } from "@/lib/tierColor";

interface Props {
  score: number;
  verdict: string;
  size?: number;
}

// Overall Assessment's own top badge, distinct from ScoreBadge's
// rectangular pill (used by the 4 per-step Analysis cards and elsewhere) --
// the design handoff calls for a circular badge here specifically, since
// this card sits above and summarizes all 4 step cards. Shows the real
// numeric score, not a fabricated letter grade (Fathom's scoring model has
// no such concept).
export function CircularScoreBadge({ score, verdict, size = 72 }: Props) {
  const cls = classFor(score, verdict);
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full border-2 ${cls}`}
      style={{ width: size, height: size }}
    >
      <span className="font-mono text-2xl font-bold tabular-nums">{score}</span>
    </span>
  );
}
