"use client";

import Link from "next/link";
import { Warning } from "@phosphor-icons/react";

import { CircularScoreBadge } from "@/components/overall/CircularScoreBadge";
import { Status, Verdict } from "@/components/ui/status";
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
import { toneFor, toneForNullable, pillLabel, verdictLabel } from "@/lib/tierColor";

interface Props {
  ticker: string;
}

function chipLabel(entry: StepBreakdownEntry): string {
  if (entry.status === "exempt") return `${entry.label} · N/A`;
  const pct = entry.effectiveWeight != null ? `${Math.round(entry.effectiveWeight * 100)}%` : `${Math.round(entry.baseWeight * 100)}%`;
  return `${entry.label} · ${pct} · ${entry.score ?? "—"}`;
}

// "N/A" alone reads ambiguously (temporary gap vs. deliberate exemption) --
// a tooltip on hover makes clear this step's weight was deliberately
// redistributed among the rest, not just missing.
function chipTitle(entry: StepBreakdownEntry): string | undefined {
  if (entry.status !== "exempt") return undefined;
  return `${entry.label} doesn't apply to this company and isn't scored — its weight is redistributed across the other steps below.`;
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

// The arithmetic behind the score: each step with its score, weight and points, then the Steps score, then Steps x multiplier = Overall.
function ArithmeticBlock({ result }: { result: OverallAssessment }) {
  if (result.stepsScore == null || result.moatMultiplier == null || result.score == null) return null;
  const moatName = result.moat ? pillLabel(MOAT_LABELS[result.moat]) : "No moat";
  const rows = result.breakdown;
  return (
    <div className="space-y-2" data-testid="score-arithmetic">
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
          {rows.map((entry) =>
            entry.effectiveWeight != null && entry.score != null ? (
              <tr key={entry.key}>
                <td className="py-0.5 font-sans">{entry.label}</td>
                <td className="py-0.5 text-right">{entry.score}</td>
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
      <p className="text-sm text-text-primary" data-testid="score-equation">
        Steps {result.stepsScore.toFixed(1)} × {moatName} {fmtMultiplier(result.moatMultiplier)} = <span className="font-semibold">{result.score}</span>
      </p>
    </div>
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

          <div className="flex flex-wrap gap-2">
            {result.breakdown.map((entry) => (
              <Status key={entry.key} tone={toneForNullable(entry.score, entry.verdict)} title={chipTitle(entry)}>
                {pillLabel(chipLabel(entry))}
              </Status>
            ))}
          </div>

          <ArithmeticBlock result={result} />

          <MultiplierDescription result={result} multipliers={multipliers} />

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
