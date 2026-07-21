"use client";

import { MetricsGrid } from "@/components/ticker/MetricsGrid";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import { DEFAULT_METRICS } from "@/lib/metrics/config";

interface Props {
  ticker: string;
}

export function SummaryTab({ ticker }: Props) {
  const { data, error } = useTickerSummary(ticker);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-red-400">Couldn&apos;t load {ticker} — {error.message}</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-zinc-600 animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      {data.description && (
        <div className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Description</h2>
          <p className="text-sm leading-relaxed text-zinc-300">{data.description}</p>
        </div>
      )}

      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-zinc-400">Key Statistics</h2>
        <MetricsGrid metrics={DEFAULT_METRICS} values={data} outlierWarnings={data.outlier_warnings} />
      </div>
    </div>
  );
}
