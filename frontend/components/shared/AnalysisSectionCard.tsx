"use client";

import { CaretDown, CaretUp } from "@phosphor-icons/react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Tooltip } from "@/components/ui/tooltip";
import { Verdict } from "@/components/ui/status";
import { toneFor, verdictDisplay } from "@/lib/tierColor";

export interface ReasoningBullet {
  key: string;
  /** e.g. "Revenue (35%, 88/100): Grows every year" -- the metric/ratio
   * name + its weight/score/tier, already composed since bullets read as
   * one flowing sentence rather than a table's separate label/tier
   * columns. */
  text: string;
  tierClassName: string;
  /** Optional hover/focus explanation for this bullet's text. */
  tooltip?: string;
}

/** Formats the "(<weight%>, <score>/100)" suffix every Analysis-tab card's
 * per-component bullets use to show that component's own contribution to
 * its SECTION's blend -- e.g. Financials' own Revenue/Net Income/CFO/
 * Margins/FCF split, or Debt's Current Ratio/Debt-to-EBITDA/DSR split --
 * never the Overall Assessment step weight (Financials' 24% etc., which
 * this component no longer surfaces at all). Centralized here (rather than
 * duplicated per card) so the format stays identical across all 4 cards.
 * `weight` is the fraction (0-1) contributed within the section; a `null`/
 * `undefined` weight (a component with no defined weight of its own, e.g.
 * Debt's Interest Coverage Ratio tiebreaker) omits the weight rather than
 * fabricating one. */
export function weightScoreSuffix(weight: number | null | undefined, score: number): string {
  if (weight == null) return ` (${score}/100)`;
  return ` (${Math.round(weight * 100)}%, ${score}/100)`;
}

interface Props {
  title: string;
  score: number | null;
  verdict: string;
  /** The wording drawn in the pill; defaults to verdictDisplay(verdict). The tone and every comparison still use the raw `verdict`. */
  verdictText?: string;
  blurb: React.ReactNode;
  /** One-line, static (non-ticker-dependent) description of how this
   * section's score is actually calculated -- e.g. "A weighted blend of
   * Revenue, Net Income, ... " Shown under `blurb` on every ticker, so it
   * stays a fixed methodology summary rather than a per-ticker computation
   * (the per-ticker detail -- each component's own weight/score -- lives in
   * `bullets` instead). */
  methodology: React.ReactNode;
  /** Small secondary notes (exemption reasons, hard-fail caveats) -- text
   * only, never a chart/table (Analysis-tab cards are deliberately minimal
   * per the design handoff; the same series/ratios are shown in full on
   * the Financials/Ratios tabs instead). */
  notes?: React.ReactNode;
  bullets: ReasoningBullet[];
}

// Shared header+blurb+collapsible-reasoning shell for all 4 Analysis tab
// section cards (Step1/Step2/Step4/Step5): neutral score number + verdict pill
// on the left (the pill carries the tone -- docs/design-system.md, "Pills"), a
// text column next to it, and the "Show reasoning" toggle pinned top right.
//
// Layout (session 16): the row is [score column w-52] [text column]. The text
// column holds the title, blurb, methodology and notes (with the toggle at
// their top right) AND the expanded reasoning list below them, so the list's
// left edge is the paragraph's left edge in both states, and expanding only
// grows the column downward (its left edge never moves). The bullets are a
// list-outside `pl-5` list: the markers hang in that padding and the bullet
// text is indented one step (1.25rem) from the paragraph.
//
// Clicking anywhere in the header row (score/title/blurb included, not just the
// small toggle) still toggles the reasoning, per the design handoff. The button
// cannot wrap the text column (the list would sit inside a button), so it is the
// toggle alone and its ::after is stretched over the `relative` Collapsible root;
// the list is `relative` too, so it paints above that overlay and stays
// selectable and click-neutral, as it was when it sat outside the button.
export function AnalysisSectionCard({ title, score, verdict, verdictText, blurb, methodology, notes, bullets }: Props) {
  return (
    <div className="rounded-lg border border-border-card bg-surface p-6">
      <Collapsible className="relative">
        <div className="flex items-start justify-between gap-4">
          {/* Fixed width, not content-sized -- verdict text length varies
              a lot ("May not pass"/Pass/Strong pass vs. "Pass with
              caution"), and without a fixed column the title/blurb next
              to it would shift card to card. Widest real case is a "74"
              (Pass with caution is capped at 74, see CLAUDE.md's
              PASS_WITH_CAUTION_SCORE_CAP) beside a "Pass with caution"
              pill, ~160px; w-52 (208px) leaves headroom over that. */}
          {score != null && (
            <div className="flex w-52 shrink-0 items-center gap-2">
              <span className="font-mono text-sm tabular-nums text-text-primary">{score}</span>
              <Verdict tone={toneFor(score, verdict)}>{verdictText ?? verdictDisplay(verdict)}</Verdict>
            </div>
          )}
          <div data-slot="analysis-text-column" className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 space-y-1">
                <h2 className="font-heading text-sm font-semibold text-text-primary">{title}</h2>
                <p className="text-sm text-text-secondary">{blurb}</p>
                <p className="text-xs text-text-tertiary">{methodology}</p>
                {notes}
              </div>
              <CollapsibleTrigger className="group flex shrink-0 items-center gap-1 pt-0.5 text-left text-xs text-text-tertiary after:absolute after:inset-0">
                <span className="group-data-[panel-open]:hidden">Show reasoning</span>
                <span className="hidden group-data-[panel-open]:inline">Hide reasoning</span>
                <CaretDown size={12} aria-hidden="true" className="group-data-[panel-open]:hidden" />
                <CaretUp size={12} aria-hidden="true" className="hidden group-data-[panel-open]:block" />
              </CollapsibleTrigger>
            </div>
            {bullets.length > 0 && (
              <CollapsibleContent className="relative">
                <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm">
                  {bullets.map((b) => (
                    <li key={b.key} className={b.tierClassName}>
                      {b.tooltip ? <Tooltip content={b.tooltip} className="text-left">{b.text}</Tooltip> : b.text}
                    </li>
                  ))}
                </ul>
              </CollapsibleContent>
            )}
          </div>
        </div>
      </Collapsible>
    </div>
  );
}
