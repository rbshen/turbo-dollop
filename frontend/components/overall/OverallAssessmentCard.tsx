"use client";

import { CircularScoreBadge } from "@/components/overall/CircularScoreBadge";
import { useOverallAssessment } from "@/lib/hooks/useOverallAssessment";
import type { StepBreakdownEntry } from "@/lib/overallScore";
import { flatChipClassFor, textClassFor } from "@/lib/tierColor";

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

export function OverallAssessmentCard({ ticker }: Props) {
  const result = useOverallAssessment(ticker);

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
              <div>
                <p className={`font-heading text-xl font-bold ${textClassFor(result.score, result.verdict)}`}>{result.verdict}</p>
                <p className="text-sm text-text-secondary">{rollupSummary(result.breakdown)}</p>
              </div>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {result.breakdown.map((entry) => (
              <span
                key={entry.key}
                className={`rounded-md px-2 py-1 text-xs font-medium ${flatChipClassFor(entry.score, entry.verdict)}`}
                title={chipTitle(entry)}
              >
                {chipLabel(entry)}
              </span>
            ))}
          </div>

          {result.failingSteps.length > 0 && (
            <p className="text-sm text-warn">
              ⚠️ {result.failingSteps.join(", ")} failed — reflected in the weighted score above, but worth reviewing
              directly.
            </p>
          )}

          {result.cautionSteps.length > 0 && (
            <p className="text-sm text-caution">
              ⚠️ {result.cautionSteps.join(", ")} passed with caution — a real breach was excused by its tiebreaker,
              reflected in the weighted score above, but worth reviewing directly.
            </p>
          )}
        </>
      )}
    </div>
  );
}
