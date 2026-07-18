"use client";

import { FinancialsSection } from "@/components/step1/FinancialsSection";
import { MarginSection } from "@/components/step1/MarginSection";
import { ScoreBadge } from "@/components/step1/ScoreBadge";
import { useElementWidth } from "@/lib/hooks/useElementWidth";
import { useStep1 } from "@/lib/hooks/useStep1";

interface Props {
  ticker: string;
}

export function Step1Card({ ticker }: Props) {
  const { data, error } = useStep1(ticker);
  const [chartsRef, chartsWidth] = useElementWidth<HTMLDivElement>();

  if (error) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-red-400">Couldn&apos;t load Step 1 data — {error.message}</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
        <p className="text-sm text-zinc-600 animate-pulse">Loading Step 1…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 rounded-lg border border-zinc-800 bg-zinc-900/40 p-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">
          Step 1 · Revenue, income and cash flow
        </h2>
        <ScoreBadge score={data.score} verdict={data.verdict} />
      </div>

      <div ref={chartsRef} className="space-y-6">
        <FinancialsSection data={data} chartWidth={chartsWidth} />
        <MarginSection data={data} chartWidth={chartsWidth} />
      </div>
    </div>
  );
}
