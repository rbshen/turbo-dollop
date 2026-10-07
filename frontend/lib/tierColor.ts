// Shared score/verdict -> pill tone tiering, used by every card that renders
// a step's score or verdict as a colour, so a step never reads as a different
// severity between its full badge and its summary chip:
//  - toneFor / toneForNullable: the Fail / caution / 91+ / 75+ / else tiers as
//    a components/ui/status.tsx StatusTone key, for every caller that renders
//    via Status/Verdict/Badge.
//  - pillLabel: the sentence-case display wording for any pill label.

import type { StatusTone } from "@/components/ui/status";

// The 5 score tiers map 1:1 onto 5 of Status's 7 tones. "neutral" is used only
// when there is no score to colour (toneForNullable). ("speculative" is never
// produced here.)
export type ScoreTone = Extract<StatusTone, "negative" | "caution" | "strong" | "positive" | "warn" | "neutral">;

// Color depends on both verdict and score: 70-74 and 75-90 both display the
// text "Pass" (see CLAUDE.md's "Scoring rubric deviations") but need
// different shades, so tone can't be chosen from verdict text alone. Fail and
// "Pass with caution" are checked before the score tiers -- a real breach
// occurred regardless of how high the blended score is, and Step 2's Fail is
// gated on projected growth being negative, not on the blended score.
export function toneFor(score: number, verdict: string): ScoreTone {
  if (verdict === "Fail") return "negative";
  if (verdict === "Pass with caution") return "caution";
  // Strong Pass (91-100) gets a deeper shade than a plain Pass (75-90).
  if (score > 90) return "strong";
  if (score >= 75) return "positive";
  return "warn"; // Pass (70-74)
}

// score == null covers both "no score computed for this ticker/step" and
// "structurally exempt" (e.g. Step 5 not_supported for Banks) -- callers
// never have a real verdict to color without a score. The score (not the
// verdict) is the only guard, so a null verdict alongside a real score still
// falls through to the score-based tiers rather than short-circuiting.
// "neutral" is the no-color tone, used whenever there's no score to color.
export function toneForNullable(score: number | null, verdict: string | null): StatusTone {
  if (score == null) return "neutral";
  return toneFor(score, verdict ?? "");
}

// The text colour of a tone, for a bare number that carries the tone itself (the Analysis card's arithmetic table), matching the text
// colour of the same tone's pill (components/ui/pill.tsx). Full literals so Tailwind sees them.
export const TONE_TEXT_CLASS: Record<StatusTone, string> = {
  strong: "text-positive-strong",
  positive: "text-positive",
  warn: "text-warn",
  caution: "text-caution",
  negative: "text-negative",
  speculative: "text-chart-purple",
  neutral: "text-text-secondary",
};

// Display wording for an Overall verdict (just pillLabel'd: the old "moat_not_rated" key was retired 2026-10-07, an unrated ticker now
// reads its verdict from its score). Use this wherever the Overall verdict itself is drawn.
export function verdictLabel(verdict: string): string {
  return pillLabel(verdict);
}

// Display wording for a Step 5 (Debt) verdict (2026-10-07): the stored key "Fail" reads "May not pass" on every Debt surface. Display only:
// every comparison (verdict === "Fail", the Review gate, the Overall rollup) still runs on the raw value, and the other steps and the
// Overall verdict keep saying "Fail".
export const DEBT_FAIL_LABEL = "May not pass";
export function debtVerdictLabel(verdict: string): string {
  return verdict === "Fail" ? DEBT_FAIL_LABEL : pillLabel(verdict);
}

// Display-only sentence casing for a pill label ("Strong Pass" -> "Strong
// pass", "Wide Moat" -> "Wide moat", "Growth Rate · 25% · 92" -> "Growth rate
// · 25% · 92"). Backend strings stay as-is -- every comparison
// (verdict === "Pass with caution") still runs on the raw value. Works per
// " · " segment: the first word keeps (gets) its capital, later plain
// Title-case words drop to lower case, and acronyms, numbers and proper nouns
// ("5Y vs SPY", "S&P 500", "Nasdaq" at a segment start) are left alone.
export function pillLabel(label: string): string {
  return label
    .split(" · ")
    .map((segment) =>
      segment
        .split(" ")
        .map((word, i) => {
          if (i === 0) return word.charAt(0).toUpperCase() + word.slice(1);
          return /^[A-Z][a-z]+$/.test(word) ? word.toLowerCase() : word;
        })
        .join(" "),
    )
    .join(" · ");
}
