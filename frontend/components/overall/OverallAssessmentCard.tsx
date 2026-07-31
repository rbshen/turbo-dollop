"use client";

import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { useOverallAssessment } from "@/lib/hooks/useOverallAssessment";
import type { StepBreakdownEntry } from "@/lib/overallScore";
import { chipClassFor } from "@/lib/tierColor";

interface Props {
  ticker: string;
}

function chipLabel(entry: StepBreakdownEntry): string {
  if (entry.status === "exempt") return `${entry.label} · N/A`;
  const pct = entry.effectiveWeight != null ? `${Math.round(entry.effectiveWeight * 100)}%` : `${Math.round(entry.baseWeight * 100)}%`;
  return `${entry.label} · ${pct} · ${entry.score ?? "—"}`;
}

export function OverallAssessmentCard({ ticker }: Props) {
  const result = useOverallAssessment(ticker);

  if (result.status === "loading") {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Overall Assessment…</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Overall Assessment</h2>
        {result.score != null && result.verdict != null && <ScoreBadge score={result.score} verdict={result.verdict} size="lg" />}
      </div>

      {result.status === "incomplete" ? (
        <p className="text-sm text-red-400">
          Incomplete — could not load {result.incompleteSteps.join(", ")}. A confident overall score needs every
          implemented step&apos;s data, so no partial number is shown.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {result.breakdown.map((entry) => (
              <span key={entry.key} className={`rounded-full border px-3 py-1 text-xs font-medium ${chipClassFor(entry.score, entry.verdict)}`}>
                {chipLabel(entry)}
              </span>
            ))}
          </div>

          {result.failingSteps.length > 0 && (
            <p className="text-sm text-amber-300">
              ⚠️ {result.failingSteps.join(", ")} failed — reflected in the weighted score above, but worth reviewing
              directly.
            </p>
          )}

          {result.cautionSteps.length > 0 && (
            <p className="text-sm text-amber-400">
              ⚠️ {result.cautionSteps.join(", ")} passed with caution — a real breach was excused by its tiebreaker,
              reflected in the weighted score above, but worth reviewing directly.
            </p>
          )}
        </>
      )}
    </div>
  );
}
