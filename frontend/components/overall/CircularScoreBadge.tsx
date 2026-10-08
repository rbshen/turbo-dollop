import { toneFor, type ScoreTone } from "@/lib/tierColor";

interface Props {
  score: number;
  verdict: string;
  size?: number;
}

// The ring stroke carries the tone (full-strength, no fill); the number stays
// neutral text-primary like every other score beside a status pill
// (docs/design-system.md, "Pills"). Class strings are literal so Tailwind
// sees them.
const RING_CLASS: Record<ScoreTone, string> = {
  strong: "border-positive-strong",
  positive: "border-positive",
  caution: "border-caution",
  "negative-soft": "border-negative-soft",
  // No score to colour: a quiet neutral ring.
  neutral: "border-text-tertiary",
};

// Overall Assessment's own top badge, distinct from ScoreBadge's stacked
// score/verdict readout (used by ScreenerCard) -- the design handoff calls
// for a circular badge here specifically, since this card sits above and
// summarizes all 4 step cards. Shows the real
// numeric score, not a fabricated letter grade (Fathom's scoring model has
// no such concept).
export function CircularScoreBadge({ score, verdict, size = 72 }: Props) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full border-2 ${RING_CLASS[toneFor(score, verdict)]}`}
      style={{ width: size, height: size }}
    >
      <span className="font-mono text-2xl font-bold tabular-nums text-text-primary">{score}</span>
    </span>
  );
}
