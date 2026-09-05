"use client";

import { CaretDown } from "@phosphor-icons/react";

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { textClassFor } from "@/lib/tierColor";

export interface ReasoningBullet {
  key: string;
  /** e.g. "Revenue: Grows every year" -- the metric/ratio name + its tier,
   * already composed since bullets read as one flowing sentence rather
   * than a table's separate label/tier columns. */
  text: string;
  tierClassName: string;
}

interface Props {
  title: string;
  score: number | null;
  verdict: string;
  blurb: React.ReactNode;
  /** One-line, static (non-ticker-dependent) description of how this
   * section's score is actually calculated -- e.g. "A weighted blend of
   * Revenue, Net Income, ... " Shown under `blurb` on every ticker, so it
   * stays a fixed methodology summary rather than a per-ticker computation
   * (the per-ticker detail already lives in `bullets`). */
  methodology: React.ReactNode;
  /** This section's own weight in the Overall Assessment blend, as a whole
   * percent (e.g. 24) -- sourced from `lib/overallScore.ts::overallWeightPct`,
   * never hardcoded at the call site. */
  weightPct: number;
  /** Small secondary notes (exemption reasons, hard-fail caveats) -- text
   * only, never a chart/table (Analysis-tab cards are deliberately minimal
   * per the design handoff; the same series/ratios are shown in full on
   * the Financials/Ratios tabs instead). */
  notes?: React.ReactNode;
  bullets: ReasoningBullet[];
}

// Shared header+blurb+collapsible-reasoning shell for all 4 Analysis tab
// section cards (Step1/Step2/Step4/Step5). Clicking anywhere in the row
// (score/title/blurb included, not just a small trigger) toggles the
// reasoning bullets -- per the design handoff's interaction spec and its
// own mockup screenshot: score+verdict as plain colored text on the left
// (no pill/box), title+blurb stacked next to it, "Show reasoning" toggle
// pinned to the right.
export function AnalysisSectionCard({ title, score, verdict, blurb, methodology, weightPct, notes, bullets }: Props) {
  return (
    <div className="rounded-lg border border-border-card bg-surface p-6">
      <Collapsible>
        <CollapsibleTrigger className="group flex w-full items-start justify-between gap-4 text-left">
          <div className="flex min-w-0 items-start gap-4">
            {/* Fixed width, not content-sized -- verdict text length varies
                a lot (Fail/Pass/Strong Pass vs. Step 5's "Pass with
                caution"), and without a fixed column the title/blurb next
                to it would shift card to card. Widest real case is "74 ·
                Pass with caution" (Pass with caution is capped at 74, see
                CLAUDE.md's PASS_WITH_CAUTION_SCORE_CAP) -- 22 monospace
                characters, ~185px at text-sm -- not "100 · Strong Pass"
                (18 chars, ~151px), which is shorter despite the extra
                digit. w-52 (208px) leaves headroom over that estimate. */}
            {score != null && (
              <span className={`w-52 shrink-0 whitespace-nowrap font-mono text-sm font-semibold ${textClassFor(score, verdict)}`}>
                {score} · {verdict}
              </span>
            )}
            <div className="min-w-0 space-y-1">
              <h2 className="font-heading text-sm font-semibold text-text-primary">{title}</h2>
              <p className="text-sm text-text-secondary">{blurb}</p>
              <p className="text-xs text-text-tertiary">{methodology}</p>
              {score != null && (
                <p className="text-xs text-text-tertiary">
                  Score: {score}/100 · Weight: {weightPct}% of Overall Assessment
                </p>
              )}
              {notes}
            </div>
          </div>
          <span className="flex shrink-0 items-center gap-1 pt-0.5 text-xs text-text-tertiary">
            <span className="group-data-[panel-open]:hidden">Show reasoning +</span>
            <span className="hidden group-data-[panel-open]:inline">Hide reasoning −</span>
            <CaretDown size={12} className="transition-transform duration-200 group-data-[panel-open]:rotate-180" />
          </span>
        </CollapsibleTrigger>

        {bullets.length > 0 && (
          <CollapsibleContent>
            {/* Indented to 80% of the score column's w-52 (13rem) width --
                roughly under the title/blurb text above rather than flush
                with the card's own left edge, without going all the way to
                a literal title-aligned indent. */}
            <ul className="mt-3 list-disc space-y-1.5 pl-[10.4rem] text-sm">
              {bullets.map((b) => (
                <li key={b.key} className={b.tierClassName}>
                  {b.text}
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        )}
      </Collapsible>
    </div>
  );
}
