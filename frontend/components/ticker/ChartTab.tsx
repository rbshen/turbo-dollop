"use client";

import { useState } from "react";

import { TickerChart } from "@/components/chart/TickerChart";
import { useTickerChart } from "@/lib/hooks/useTickerChart";
import type { ChartRange } from "@/lib/api/types";

interface Props {
  ticker: string;
}

const RANGE_OPTIONS: { key: ChartRange; label: string }[] = [
  { key: "D_6M", label: "D · 6M" },
  { key: "D_1Y", label: "D · 1Y" },
  { key: "D_2Y", label: "D · 2Y" },
  { key: "W_4Y", label: "W · 4Y" },
];

// Approximates a plausible price-chart silhouette while the on-demand fetch
// (see data/chart_data.py -- there's no nightly precompute for this
// feature, so every range switch is a real fetch) is in flight. Adapted
// from Options Tracker's own ChartSkeleton -- the "Fetching live data..."
// label it also had doesn't apply here, since every load here is a fetch,
// there's no cache-vs-live distinction to call out.
const _SKELETON_HEIGHTS = [
  40, 55, 48, 62, 50, 70, 45, 65, 52, 75, 58, 68, 44, 72, 56, 63, 50, 80, 60, 46, 70, 53, 66, 49, 59, 73, 46, 69, 56, 61, 47, 78, 62, 44, 67, 54,
  71, 50, 64, 48,
];

function ChartSkeleton() {
  return (
    <div className="h-[630px] rounded-lg border border-border-card bg-zinc-950 relative flex items-end gap-[2px] px-4 pb-10 animate-pulse">
      {_SKELETON_HEIGHTS.map((h, i) => (
        <div key={i} className="flex-1 bg-zinc-800 rounded-t-[1px]" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

export function ChartTab({ ticker }: Props) {
  const [range, setRange] = useState<ChartRange>("D_1Y");
  const { data, error, isLoading } = useTickerChart(ticker, range);

  return (
    <div className="space-y-4 py-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Chart</h2>
          <p className="mt-1 text-sm text-text-secondary">
            OHLC price chart with EMA(21), SMA(50/200), Bollinger Bands(20, 2), Full Stochastic(5, 3, 3), and RSI(14). Informational only.
          </p>
        </div>
        <div className="flex items-center gap-1">
          {RANGE_OPTIONS.map((opt) => (
            <button
              key={opt.key}
              onClick={() => setRange(opt.key)}
              className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                range === opt.key ? "bg-zinc-700 text-zinc-100" : "text-text-tertiary hover:text-text-secondary hover:bg-surface-2"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="py-6 text-sm text-negative">Couldn&apos;t load the chart — {error.message}</p>}

      {!error && isLoading && !data && <ChartSkeleton />}

      {!error && data && !data.chart_available && (
        <div className="flex h-48 items-center justify-center rounded-lg border border-border-card bg-zinc-950 text-sm text-text-tertiary">
          No chart data available for {ticker}.
        </div>
      )}

      {!error && data && data.chart_available && (
        <>
          <TickerChart key={range} data={data} />
          {!data.entry_signal_available && !data.zones_available ? (
            // Both features share the exact same W1-W5 scope
            // (see chart_data.py) -- when neither has ever run for this
            // ticker, one combined line reads cleaner than two identical
            // "not tracked" sentences stacked on top of each other.
            <p className="text-xs text-text-tertiary">
              Not tracked for entry signals or Liquidity Zone (LP) levels — this ticker isn&apos;t on a watchlist
              named W1 through W5.
            </p>
          ) : (
            <div className="space-y-1">
              <p className="text-xs text-text-tertiary">
                {data.entry_signal_available
                  ? data.entry_signal_markers.length > 0
                    ? "Markers show past BB+RSI (2h) entry signals in this range."
                    : "Tracked for BB+RSI entry signals — none fired in this range."
                  : "Not tracked for entry signals — this ticker isn't on a watchlist named W1 through W5."}
              </p>
              <p className="text-xs text-text-tertiary">
                {data.zones_available
                  ? data.zones.length > 0
                    ? "Green/red lines show unbreached support/resistance levels from Liquidity Zone (LP) detection."
                    : "Tracked for Liquidity Zone (LP) detection — no zones in this range."
                  : "Not tracked for Liquidity Zone (LP) detection — this ticker isn't on a watchlist named W1 through W5."}
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}
