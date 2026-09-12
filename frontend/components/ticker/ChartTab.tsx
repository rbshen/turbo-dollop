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

// Chart-tab-only overlay visibility toggles -- scoped to this tab's own TickerChart rendering (see TickerChart.tsx's
// showXxx props); the Technical tab's BbRsiEntrySignalCard/WarrenSignalCard and the EMA/SMA/Bollinger/LP series data
// itself are otherwise untouched -- toggling one of these only flips series/marker visibility, never refetches or
// recomputes anything. Persisted the same way Watchlist sort rules are (app/watchlist/page.tsx) -- a single
// localStorage key, read/written inside try/catch for private-window/blocked-storage cases, silently falling back
// to the default (all on) rather than throwing during render.
const SIGNAL_TOGGLE_STORAGE_KEY = "fathom-chart-signal-toggles";

interface SignalToggles {
  bbRsi: boolean;
  warren: boolean;
  lpSupport: boolean;
  lpResistance: boolean;
  bollinger: boolean;
  ema21: boolean;
  sma50: boolean;
  sma200: boolean;
}

const DEFAULT_SIGNAL_TOGGLES: SignalToggles = {
  bbRsi: true,
  warren: true,
  lpSupport: true,
  lpResistance: true,
  bollinger: true,
  ema21: true,
  sma50: true,
  sma200: true,
};

const TOGGLE_OPTIONS: { key: keyof SignalToggles; label: string }[] = [
  { key: "bbRsi", label: "BB+RSI" },
  { key: "warren", label: "Warren" },
  { key: "lpSupport", label: "LP Support" },
  { key: "lpResistance", label: "LP Resistance" },
  { key: "bollinger", label: "BB" },
  { key: "ema21", label: "EMA 21" },
  { key: "sma50", label: "SMA 50" },
  { key: "sma200", label: "SMA 200" },
];

function loadSignalToggles(): SignalToggles {
  if (typeof window === "undefined") return DEFAULT_SIGNAL_TOGGLES;
  try {
    const raw = window.localStorage.getItem(SIGNAL_TOGGLE_STORAGE_KEY);
    if (!raw) return DEFAULT_SIGNAL_TOGGLES;
    const parsed = JSON.parse(raw);
    const result = { ...DEFAULT_SIGNAL_TOGGLES };
    for (const key of Object.keys(DEFAULT_SIGNAL_TOGGLES) as (keyof SignalToggles)[]) {
      if (typeof parsed[key] === "boolean") result[key] = parsed[key];
    }
    return result;
  } catch {
    return DEFAULT_SIGNAL_TOGGLES;
  }
}

function saveSignalToggles(toggles: SignalToggles) {
  try {
    window.localStorage.setItem(SIGNAL_TOGGLE_STORAGE_KEY, JSON.stringify(toggles));
  } catch {
    // localStorage unavailable (private window, blocked site data, quota) -- the in-memory state still updates
    // for this session, it just won't survive a reload.
  }
}

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
  // Loaded from localStorage during render, not in an effect -- mirrors Watchlist sort rules' own "adjust state
  // during rendering" pattern (app/watchlist/page.tsx's sortState/activeId), which this project's lint config
  // requires over calling setState from inside a useEffect body. `loaded` starts false so this only runs once
  // per mount.
  const [toggleState, setToggleState] = useState<{ loaded: boolean; toggles: SignalToggles }>({
    loaded: false,
    toggles: DEFAULT_SIGNAL_TOGGLES,
  });
  if (!toggleState.loaded) {
    setToggleState({ loaded: true, toggles: loadSignalToggles() });
  }
  const signalToggles = toggleState.toggles;
  const { data, error, isLoading } = useTickerChart(ticker, range);

  function handleToggleChange(key: keyof SignalToggles) {
    const next = { ...signalToggles, [key]: !signalToggles[key] };
    setToggleState({ loaded: true, toggles: next });
    saveSignalToggles(next);
  }

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

      <div className="flex flex-wrap items-center gap-1">
        {TOGGLE_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => handleToggleChange(opt.key)}
            aria-pressed={signalToggles[opt.key]}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              signalToggles[opt.key] ? "bg-zinc-700 text-zinc-100" : "text-text-tertiary hover:text-text-secondary hover:bg-surface-2"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {error && <p className="py-6 text-sm text-negative">Couldn&apos;t load the chart — {error.message}</p>}

      {!error && isLoading && !data && <ChartSkeleton />}

      {!error && data && !data.chart_available && (
        <div className="flex h-48 items-center justify-center rounded-lg border border-border-card bg-zinc-950 text-sm text-text-tertiary">
          No chart data available for {ticker}.
        </div>
      )}

      {!error && data && data.chart_available && (
        <TickerChart
          key={range}
          data={data}
          showBbRsi={signalToggles.bbRsi}
          showWarren={signalToggles.warren}
          showLpSupport={signalToggles.lpSupport}
          showLpResistance={signalToggles.lpResistance}
          showBollinger={signalToggles.bollinger}
          showEma21={signalToggles.ema21}
          showSma50={signalToggles.sma50}
          showSma200={signalToggles.sma200}
        />
      )}
    </div>
  );
}
