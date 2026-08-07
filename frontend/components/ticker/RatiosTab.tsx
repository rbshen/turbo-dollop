"use client";

import { RatiosTable } from "@/components/ticker/RatiosTable";
import { RatioTrendsGrid } from "@/components/ticker/RatioTrendsGrid";
import { useRatios } from "@/lib/hooks/useRatios";

interface Props {
  ticker: string;
}

export function RatiosTab({ ticker }: Props) {
  const { data, error } = useRatios(ticker);

  if (error) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-negative">
          Couldn&apos;t load {ticker} — {error.message}
        </span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <span className="text-sm text-text-tertiary animate-pulse">Loading {ticker}…</span>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      <div className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-text-secondary">Historical Trends</h2>
        <RatioTrendsGrid ticker={ticker} />
      </div>

      <div className="space-y-4">
        <p className="text-xs text-text-tertiary">
          Annual figures (oldest to newest) plus a trailing-twelve-month (TTM) column. Quarterly ratios aren&apos;t
          available on our current data plan.
          {data.reported_currency && data.reported_currency !== "USD" && (
            <>
              {" "}
              Per-share/money rows are in {data.reported_currency}, as reported by {ticker}, not converted to USD
              (unlike the Valuation tab).
            </>
          )}
        </p>
        <RatiosTable data={data} />
      </div>
    </div>
  );
}
