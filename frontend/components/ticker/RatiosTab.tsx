"use client";

import { RatiosTable } from "@/components/ticker/RatiosTable";
import { useRatios } from "@/lib/hooks/useRatios";

interface Props {
  ticker: string;
}

export function RatiosTab({ ticker }: Props) {
  const { data, error } = useRatios(ticker);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-red-400">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
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
    <div className="space-y-4 py-6">
      <p className="text-xs text-zinc-500">
        Annual figures (oldest to newest) plus a trailing-twelve-month (TTM) column. Quarterly ratios aren&apos;t
        available on our current data plan.
      </p>
      <RatiosTable data={data} />
    </div>
  );
}
