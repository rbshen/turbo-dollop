"use client";

import { useState } from "react";
import Link from "next/link";
import { CaretDown, CaretUp, Warning } from "@phosphor-icons/react";

import { CircularScoreBadge } from "@/components/overall/CircularScoreBadge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Verdict } from "@/components/ui/status";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
import { useOverallAssessment } from "@/lib/hooks/useOverallAssessment";
import { useTickerScore } from "@/lib/hooks/useTickerScore";
import type { TickerScoreOut } from "@/lib/api/types";
import {
  displayedReview,
  REVIEW_STATUS_LABEL,
  REVIEW_STATUS_TONE,
  reviewHintLabel,
  reviewStepName,
  type DisplayedReview,
} from "@/lib/reviewStatus";
import {
  DEFAULT_NARROW_MOAT_MULTIPLIER,
  MOAT_LABELS,
  NO_MOAT_MULTIPLIER,
  WIDE_MOAT_MULTIPLIER,
  type OverallAssessment,
  type StepBreakdownEntry,
} from "@/lib/overallScore";
import { TONE_TEXT_CLASS, toneFor, toneForNullable, pillLabel, verdictLabel } from "@/lib/tierColor";

interface Props {
  ticker: string;
}

// One-line rollup summary, generated from the same breakdown data the
// chips below already show -- not a fabricated blurb, just a plain-English
// count of the real weighted components.
function rollupSummary(breakdown: StepBreakdownEntry[]): string {
  const counted = breakdown.filter((b) => b.score != null);
  const passing = counted.filter((b) => b.verdict !== "Fail").length;
  return `${passing} of ${counted.length} weighted components at Pass level or better.`;
}

// The three multipliers the description quotes: Wide and No moat are fixed, Narrow is the saved setting.
export interface MoatMultipliers {
  wide: number;
  narrow: number;
  noMoat: number;
}

const DEFAULT_MULTIPLIERS: MoatMultipliers = {
  wide: WIDE_MOAT_MULTIPLIER,
  narrow: DEFAULT_NARROW_MOAT_MULTIPLIER,
  noMoat: NO_MOAT_MULTIPLIER,
};

// 1 reads "1.0", everything else two decimals (0.85, 0.70).
export const fmtMultiplier = (m: number): string => (m === 1 ? "1.0" : m.toFixed(2));

/** A weight as a percent, one decimal only when it is not whole (30%, 42.9%). */
export const fmtWeightPct = (fraction: number): string => `${Number((fraction * 100).toFixed(1))}%`;

export function OverallAssessmentCard({ ticker }: Props) {
  const result = useOverallAssessment(ticker);
  // The stored TickerScore row (Refresh and a Moat PUT revalidate every /tickers/{t}/... key, this one included).
  const { data: stored } = useTickerScore(ticker);
  const { data: moatConfig } = useMoatConfig();
  const multipliers: MoatMultipliers = {
    wide: moatConfig?.wide_moat_multiplier ?? WIDE_MOAT_MULTIPLIER,
    narrow: moatConfig?.narrow_moat_multiplier ?? DEFAULT_NARROW_MOAT_MULTIPLIER,
    noMoat: moatConfig?.no_moat_multiplier ?? NO_MOAT_MULTIPLIER,
  };
  return <OverallAssessmentView result={result} stored={stored} multipliers={multipliers} />;
}

// How the Overall score is built, in words: the weights come from the breakdown (so they follow the saved weights and any exempt
// step), the multipliers from the moat config.
function MultiplierDescription({ result, multipliers }: { result: OverallAssessment; multipliers: MoatMultipliers }) {
  const weights = result.breakdown
    .filter((b) => b.effectiveWeight != null)
    .map((b) => `${b.label} ${fmtWeightPct(b.effectiveWeight as number)}`)
    .join(", ");
  return (
    <div className="space-y-2 text-xs text-text-tertiary" data-testid="weighting-note">
      <p>
        The Steps score is the weighted blend of the checks ({weights}), using your saved weights. The Overall score is the Steps
        score times a Moat multiplier: Wide moat × {fmtMultiplier(multipliers.wide)}, Narrow moat × {fmtMultiplier(multipliers.narrow)},
        No moat × {fmtMultiplier(multipliers.noMoat)}. A ticker with no Moat rated is scored as No moat.{" "}
        <Link href="/settings?section=score-weighting" className="underline underline-offset-2 hover:text-text-secondary">
          Adjust the weights
        </Link>{" "}
        or{" "}
        <Link href="/settings?section=economic-moat" className="underline underline-offset-2 hover:text-text-secondary">
          the Narrow multiplier
        </Link>
        .
      </p>
    </div>
  );
}

// The result line: Steps score x multiplier = Overall.
function ScoreEquation({ result }: { result: OverallAssessment }) {
  if (result.stepsScore == null || result.moatMultiplier == null || result.score == null) return null;
  const moatName = result.moat ? pillLabel(MOAT_LABELS[result.moat]) : "No moat";
  return (
    <p className="text-sm text-text-primary" data-testid="score-equation">
      Steps {result.stepsScore.toFixed(1)} × {moatName} {fmtMultiplier(result.moatMultiplier)} = <span className="font-semibold">{result.score}</span>
    </p>
  );
}

// The arithmetic behind the score: each step with its score, weight and points, then the Steps score.
function ArithmeticTable({ result }: { result: OverallAssessment }) {
  if (result.stepsScore == null) return null;
  return (
    <div data-testid="score-arithmetic">
      <table className="w-full max-w-md text-sm">
        <thead>
          <tr className="text-left text-xs text-text-tertiary">
            <th className="pb-1 font-normal">Step</th>
            <th className="pb-1 text-right font-normal">Score</th>
            <th className="pb-1 text-right font-normal">Weight</th>
            <th className="pb-1 text-right font-normal">Points</th>
          </tr>
        </thead>
        <tbody className="font-mono text-text-secondary">
          {result.breakdown.map((entry) =>
            entry.effectiveWeight != null && entry.score != null ? (
              <tr key={entry.key}>
                <td className="py-0.5 font-sans">{entry.label}</td>
                {/* The score takes the tone the breakdown pills used to carry; weight, points and the Steps score stay plain. */}
                <td className={`py-0.5 text-right ${TONE_TEXT_CLASS[toneForNullable(entry.score, entry.verdict)]}`} data-testid={`score-${entry.key}`}>
                  {entry.score}
                </td>
                <td className="py-0.5 text-right">{fmtWeightPct(entry.effectiveWeight)}</td>
                <td className="py-0.5 text-right">{(entry.effectiveWeight * entry.score).toFixed(1)}</td>
              </tr>
            ) : (
              <tr key={entry.key} className="text-text-tertiary">
                <td className="py-0.5 font-sans">{entry.label}</td>
                <td className="py-0.5 text-right" colSpan={3}>
                  not scored for this company
                </td>
              </tr>
            ),
          )}
          <tr className="border-t border-border-subtle text-text-primary">
            <td className="pt-1 font-sans font-semibold">Steps score</td>
            <td />
            <td />
            <td className="pt-1 text-right font-semibold">{result.stepsScore.toFixed(1)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// The calculation, collapsed by default on every render (the state is not persisted): the one-line result and a toggle; expanded, the
// arithmetic table, the result line and the explanatory paragraph. Same toggle pattern as AnalysisSectionCard's "Show reasoning".
function CalculationSection({ result, multipliers }: { result: OverallAssessment; multipliers: MoatMultipliers }) {
  const [open, setOpen] = useState(false); // collapsed on every render; never persisted
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="space-y-3" data-testid="calculation">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
        {/* Collapsed: the one-line result sits beside the toggle. Expanded it moves under the table (below), as it always read. */}
        {open ? <span /> : <ScoreEquation result={result} />}
        <CollapsibleTrigger className="group flex shrink-0 items-center gap-1 text-left text-xs text-text-tertiary hover:text-text-secondary">
          <span className="group-data-[panel-open]:hidden">Show calculation</span>
          <span className="hidden group-data-[panel-open]:inline">Hide calculation</span>
          <CaretDown size={12} aria-hidden="true" className="group-data-[panel-open]:hidden" />
          <CaretUp size={12} aria-hidden="true" className="hidden group-data-[panel-open]:block" />
        </CollapsibleTrigger>
      </div>
      <CollapsibleContent className="space-y-3">
        <ArithmeticTable result={result} />
        <ScoreEquation result={result} />
        <MultiplierDescription result={result} multipliers={multipliers} />
      </CollapsibleContent>
    </Collapsible>
  );
}

// The Review status block: the stored status, one line per gated step with its evidence, and the conviction. Facts come
// from the stored reasons; nothing here decides a status.
function ReviewStatusBlock({ review }: { review: DisplayedReview }) {
  const tone = REVIEW_STATUS_TONE[review.status] === "caution" ? "text-caution" : "text-warn";
  return (
    <div className={`space-y-1.5 text-sm ${tone}`} data-testid="review-status">
      <p>
        <Warning size={16} weight="bold" aria-hidden="true" className="-mt-0.5 mr-1.5 inline" />
        <span className="sr-only">Warning: </span>
        <span className="font-semibold">{REVIEW_STATUS_LABEL[review.status]}</span>
        {review.conviction && <span> · Conviction: {review.conviction}</span>}
        <span> — the numeric score and verdict above are unchanged; this flags a step that failed badly.</span>
      </p>
      <ul className="list-disc space-y-1 pl-6">
        {review.reasons.map((reason) => (
          <li key={reason.step}>
            <span className="font-semibold">{reviewStepName(reason.step)}</span> scored {reason.score} ({reason.verdict}):{" "}
            {reason.evidence}
            {reason.guarded && ` If the data is confirmed this would read ${reviewHintLabel(reason.raw_hint)}.`}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Presentational card -- the assessment arrives as a prop, so /styleguide can
// render every state from mock data.
export function OverallAssessmentView({
  result,
  stored,
  multipliers = DEFAULT_MULTIPLIERS,
}: {
  result: OverallAssessment;
  stored?: TickerScoreOut | null;
  multipliers?: MoatMultipliers;
}) {
  // Only when the stored row's verdict is the one this card computes live; otherwise nothing (never a stale label).
  const review = result.status === "complete" ? displayedReview(stored, result.verdict) : null;

  if (result.status === "loading") {
    return (
      <div className="rounded-lg border border-border-card bg-surface p-6">
        <p className="text-sm text-text-tertiary animate-pulse">Loading Overall Assessment…</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-border-card bg-surface p-6">
      <h2 className="font-heading text-sm font-semibold text-text-primary">Overall Assessment</h2>

      {result.status === "incomplete" ? (
        <p className="text-sm text-negative">
          Incomplete — could not load {result.incompleteSteps.join(", ")}. A confident overall score needs every
          implemented step&apos;s data, so no partial number is shown.
        </p>
      ) : (
        <>
          {result.score != null && result.verdict != null && (
            <div className="flex items-center gap-4">
              <CircularScoreBadge score={result.score} verdict={result.verdict} />
              <div className="space-y-1.5">
                <Verdict tone={toneFor(result.score, result.verdict)}>{verdictLabel(result.verdict)}</Verdict>
                {result.moatNote && (
                  <p className="text-sm text-text-secondary" data-testid="moat-not-rated-note">
                    {result.moatNote}
                  </p>
                )}
                <p className="text-sm text-text-secondary">{rollupSummary(result.breakdown)}</p>
              </div>
            </div>
          )}

          <CalculationSection result={result} multipliers={multipliers} />

          {result.failingSteps.length > 0 && (
            <p className="text-sm text-warn">
              <Warning size={16} weight="bold" aria-hidden="true" className="-mt-0.5 mr-1.5 inline" />
              <span className="sr-only">Warning: </span>
              {result.failingSteps.join(", ")} failed — reflected in the weighted score above, but worth reviewing
              directly.
            </p>
          )}

          {review && <ReviewStatusBlock review={review} />}

          {result.cautionSteps.length > 0 && (
            <p className="text-sm text-caution">
              <Warning size={16} weight="bold" aria-hidden="true" className="-mt-0.5 mr-1.5 inline" />
              <span className="sr-only">Warning: </span>
              {result.cautionSteps.join(", ")} passed with caution — a real breach was excused by its tiebreaker,
              reflected in the weighted score above, but worth reviewing directly.
            </p>
          )}
        </>
      )}
    </div>
  );
}
