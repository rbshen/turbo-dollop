"use client";

import { ScoreBadge } from "@/components/step1/ScoreBadge";
import type { MoatScoreConfigOut } from "@/lib/api/types";
import { useMoatConfig } from "@/lib/hooks/useMoatConfig";
import { useStep1 } from "@/lib/hooks/useStep1";
import { useStep2 } from "@/lib/hooks/useStep2";
import { useStep4 } from "@/lib/hooks/useStep4";
import { useStep5 } from "@/lib/hooks/useStep5";
import { useTickerMoat } from "@/lib/hooks/useTickerMoat";
import { computeOverallAssessment, type MoatSnapshot, type StepBreakdownEntry, type StepSnapshot } from "@/lib/overallScore";

interface Props {
  ticker: string;
}

const STEP_LABELS = {
  step1: "Step 1 · Track Record",
  step2: "Step 2 · Growth Rate",
  step4: "Step 4 · Profitability",
  step5: "Step 5 · Debt",
} as const;

const MOAT_SCORE_FIELD: Record<"no_moat" | "narrow_moat" | "wide_moat", (config: MoatScoreConfigOut) => number> = {
  no_moat: (config) => config.no_moat_score,
  narrow_moat: (config) => config.narrow_moat_score,
  wide_moat: (config) => config.wide_moat_score,
};

function chipClass(entry: StepBreakdownEntry): string {
  if (entry.status === "exempt") return "border-zinc-800 bg-zinc-900 text-zinc-500";
  if (entry.verdict === "Fail") return "border-red-800/40 bg-red-900/20 text-red-400";
  if (entry.score != null && entry.score > 90) return "border-emerald-700/40 bg-emerald-900/20 text-emerald-300";
  return "border-zinc-700 bg-zinc-800/60 text-zinc-300";
}

function chipLabel(entry: StepBreakdownEntry): string {
  if (entry.status === "exempt") return `${entry.label} · N/A`;
  const pct = entry.effectiveWeight != null ? `${Math.round(entry.effectiveWeight * 100)}%` : `${Math.round(entry.baseWeight * 100)}%`;
  return `${entry.label} · ${pct} · ${entry.score ?? "—"}`;
}

export function OverallAssessmentCard({ ticker }: Props) {
  const step1 = useStep1(ticker);
  const step2 = useStep2(ticker);
  const step4 = useStep4(ticker);
  const step5 = useStep5(ticker);
  const tickerMoat = useTickerMoat(ticker);
  const moatConfig = useMoatConfig();

  const snapshots: StepSnapshot[] = [
    { key: "step1", label: STEP_LABELS.step1, hasError: !!step1.error, data: step1.data ? { score: step1.data.score, verdict: step1.data.verdict } : undefined },
    { key: "step2", label: STEP_LABELS.step2, hasError: !!step2.error, data: step2.data ? { score: step2.data.score, verdict: step2.data.verdict } : undefined },
    { key: "step4", label: STEP_LABELS.step4, hasError: !!step4.error, data: step4.data ? { score: step4.data.score, verdict: step4.data.verdict } : undefined },
    { key: "step5", label: STEP_LABELS.step5, hasError: !!step5.error, data: step5.data ? { score: step5.data.score, verdict: step5.data.verdict } : undefined },
  ];

  // tickerMoat.data.moat === null means confirmed "not set" -- no moat
  // config lookup needed in that case, so moatLoading only waits on
  // moatConfig when a moat is actually set.
  const moatLoading = !tickerMoat.data || (tickerMoat.data.moat !== null && !moatConfig.data);
  const moat: MoatSnapshot | null =
    tickerMoat.data?.moat && moatConfig.data
      ? { moat: tickerMoat.data.moat, score: MOAT_SCORE_FIELD[tickerMoat.data.moat](moatConfig.data) }
      : null;

  const result = computeOverallAssessment(snapshots, moat, moatLoading);

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
          <p className="text-xs text-zinc-600">
            {result.assessedCount} of {result.totalMethodologySteps} steps assessed — Step 3 not yet available.
          </p>

          <div className="flex flex-wrap gap-2">
            {result.breakdown.map((entry) => (
              <span key={entry.key} className={`rounded-full border px-3 py-1 text-xs font-medium ${chipClass(entry)}`}>
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
        </>
      )}
    </div>
  );
}
