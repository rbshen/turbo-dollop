"use client";

import { useCallback, useState } from "react";

import { ChartAxisMenu } from "@/components/chart/ChartAxisMenu";
import { TickerChart } from "@/components/chart/TickerChart";
import type { ZoomBounds } from "@/components/chart/TickerChart";
import { Button } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useTickerChart } from "@/lib/hooks/useTickerChart";
import { useTickerSummary } from "@/lib/hooks/useTickerSummary";
import type { ChartRange } from "@/lib/api/types";
import { DEFAULT_SIGNAL_TOGGLES, effectiveToggles, INTRADAY_CHART_RANGE, visibleToggleOptions } from "@/lib/chartToggles";
import type { SignalToggles } from "@/lib/chartToggles";
import { axisOptionsOffered, DEFAULT_AXIS_OPTIONS, effectiveAxisOptions, loadAxisOptions, saveAxisOptions } from "@/lib/chartAxis";
import type { AxisOptions } from "@/lib/chartAxis";

interface Props {
  ticker: string;
  /** The ETF page: funds report no earnings, so the Earnings overlay toggle is hidden (and forced off). */
  isEtf?: boolean;
}

const RANGE_OPTIONS: { key: ChartRange; label: string }[] = [
  { key: "2H_90D", label: "2H · 90D" },
  { key: "D_6M", label: "D · 6M" },
  { key: "D_1Y", label: "D · 1Y" },
  { key: "D_2Y", label: "D · 2Y" },
  { key: "W_4Y", label: "W · 4Y" },
];

// Chart-tab-only overlay visibility toggles (types, defaults, and which toggles each range offers are in
// lib/chartToggles.ts) -- scoped to this tab's own TickerChart rendering (see TickerChart.tsx's
// showXxx props); the Technical tab's BbRsiEntrySignalCard/WarrenSignalCard and the EMA/SMA/Bollinger/LP series data
// itself are otherwise untouched -- toggling one of these only flips series/marker visibility, never refetches or
// recomputes anything. Persisted the same way Watchlist sort rules are (app/watchlist/page.tsx) -- a single
// localStorage key, read/written inside try/catch for private-window/blocked-storage cases, silently falling back
// to the default (all on) rather than throwing during render.
const SIGNAL_TOGGLE_STORAGE_KEY = "fathom-chart-signal-toggles";

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
    <div className="h-[630px] rounded-lg border border-border-card bg-page relative flex items-end gap-[2px] px-4 pb-10 animate-pulse">
      {_SKELETON_HEIGHTS.map((h, i) => (
        <div key={i} className="flex-1 bg-surface-2 rounded-t-[1px]" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

export function ChartTab({ ticker, isEtf }: Props) {
  const [range, setRange] = useState<ChartRange>("D_6M");
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
  // Axis readability options (lib/chartAxis.ts): all off by default, kept for the browser session only (sessionStorage,
  // loaded during render like the toggles above), and only handed to a range that offers them -- every other range is
  // told all-off.
  const [axisState, setAxisState] = useState<{ loaded: boolean; options: AxisOptions }>({ loaded: false, options: DEFAULT_AXIS_OPTIONS });
  if (!axisState.loaded) {
    setAxisState({ loaded: true, options: loadAxisOptions() });
  }
  const axisOptions = axisState.options;
  const { data, error, isLoading } = useTickerChart(ticker, range);
  // What the chart is told: each saved toggle ANDed with "this range offers it" (hidden toggles are forced off but
  // their saved value is left alone, so switching back restores it).
  const shown = effectiveToggles(signalToggles, range, !!isEtf);
  const chartShown = !error && !!data && data.chart_available;
  // Same SWR key TickerTabsContainer's own header fetch already uses -- a
  // cache hit, not a new request. OHLC prices are quote-domain (the
  // ticker's actual traded market currency), same as the header's own
  // price -- must never disagree with it.
  const { data: summary } = useTickerSummary(ticker);
  const quoteCurrency = summary?.quote_currency ?? "USD";

  // Zoom is fully controlled here -- TickerChart owns no zoom state of its own, it
  // just applies whichever index this is and reports back whether either button
  // should be enabled (bounds depend on the chart's own live pane width, which only
  // TickerChart has access to). handleZoomBoundsChange is stable across renders so
  // TickerChart's zoom-apply effect doesn't re-run purely because ChartTab re-rendered.
  const [zoomIndex, setZoomIndex] = useState(0);
  const [zoomBounds, setZoomBounds] = useState<ZoomBounds>({ canZoomIn: true, canZoomOut: false });
  const handleZoomBoundsChange = useCallback((bounds: ZoomBounds) => setZoomBounds(bounds), []);

  function handleToggleChange(key: keyof SignalToggles) {
    const next = { ...signalToggles, [key]: !signalToggles[key] };
    setToggleState({ loaded: true, toggles: next });
    saveSignalToggles(next);
  }

  function handleAxisChange(key: keyof AxisOptions) {
    const next = { ...axisOptions, [key]: !axisOptions[key] };
    setAxisState({ loaded: true, options: next });
    saveAxisOptions(next);
  }

  function handleRangeChange(next: ChartRange) {
    setRange(next);
    setZoomIndex(0); // a new range has its own bar count/fit level -- start back at fitContent()'s equivalent
    setZoomBounds({ canZoomIn: true, canZoomOut: false }); // the next chart reports its own; never carry the last one's
  }

  return (
    <div className="space-y-4 py-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-text-tertiary">Chart</h2>
        </div>
        <SegmentedControl
          aria-label="Chart range"
          value={range}
          onValueChange={(next) => handleRangeChange(next as ChartRange)}
          options={RANGE_OPTIONS.map((opt) => ({ value: opt.key, label: opt.label }))}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1">
          {visibleToggleOptions(range, !!isEtf).map((opt) => (
            <Button
              key={opt.key}
              variant="outline"
              size="sm"
              onClick={() => handleToggleChange(opt.key)}
              aria-pressed={signalToggles[opt.key]}
              className={signalToggles[opt.key] ? "bg-surface-2 text-text-primary" : undefined}
            >
              {opt.label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          {axisOptionsOffered(range) && (
            <ChartAxisMenu options={axisOptions} onChange={handleAxisChange} />
          )}
          <Button variant="outline" size="sm" onClick={() => setZoomIndex((i) => Math.max(0, i - 1))} disabled={!chartShown || !zoomBounds.canZoomOut}>
            Zoom out
          </Button>
          <Button variant="outline" size="sm" onClick={() => setZoomIndex((i) => i + 1)} disabled={!chartShown || !zoomBounds.canZoomIn}>
            Zoom in
          </Button>
        </div>
      </div>

      {error && <p className="py-6 text-sm text-negative">Couldn&apos;t load the chart — {error.message}</p>}

      {!error && isLoading && !data && <ChartSkeleton />}

      {!error && data && !data.chart_available && (
        <div className="flex h-48 items-center justify-center rounded-lg border border-border-card bg-page text-xs text-text-tertiary">
          <div className="text-center">
            <p>No chart data available for {ticker}.</p>
            {range === INTRADAY_CHART_RANGE && (
              <p className="mt-1">2-hour data is not available for this ticker right now (e.g. a non-US listing).</p>
            )}
          </div>
        </div>
      )}

      {!error && data && data.chart_available && (
        <TickerChart
          key={range}
          data={data}
          quoteCurrency={quoteCurrency}
          showBbRsi={shown.bbRsi}
          showWarren={shown.warren}
          showEarnings={shown.earnings}
          showDividends={shown.dividends}
          showLpSupport={shown.lpSupport}
          showLpResistance={shown.lpResistance}
          showBollinger={shown.bollinger}
          showEma21={shown.ema21}
          showSma50={shown.sma50}
          showSma200={shown.sma200}
          showStage={shown.stage}
          axisOptions={effectiveAxisOptions(axisOptions, range)}
          zoomIndex={zoomIndex}
          onZoomBoundsChange={handleZoomBoundsChange}
        />
      )}
    </div>
  );
}
