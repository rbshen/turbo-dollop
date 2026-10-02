import type { ChartRange } from "@/lib/api/types";

// The Chart tab's overlay toggles and which of them each range offers. A toggle that a range does not offer is both
// hidden from the button row AND forced off in what the chart is told (effectiveToggles) -- but the user's saved
// choice for it is never touched, so switching back to a range that offers it restores it (the Stage precedent).

export interface SignalToggles {
  bbRsi: boolean;
  warren: boolean;
  earnings: boolean;
  dividends: boolean;
  lpSupport: boolean;
  lpResistance: boolean;
  bollinger: boolean;
  ema21: boolean;
  sma50: boolean;
  sma200: boolean;
  stage: boolean;
}

export const DEFAULT_SIGNAL_TOGGLES: SignalToggles = {
  bbRsi: true,
  warren: true,
  earnings: true,
  dividends: true,
  lpSupport: true,
  lpResistance: true,
  bollinger: true,
  ema21: true,
  sma50: true,
  sma200: true,
  // Off by default; W/4Y only (see STAGE_TOGGLE_RANGE).
  stage: false,
};

export const TOGGLE_OPTIONS: { key: keyof SignalToggles; label: string }[] = [
  { key: "bbRsi", label: "BB+RSI" },
  { key: "warren", label: "Warren" },
  { key: "earnings", label: "Earnings" },
  { key: "dividends", label: "Dividends" },
  { key: "lpSupport", label: "LP Support" },
  { key: "lpResistance", label: "LP Resistance" },
  { key: "bollinger", label: "BB" },
  { key: "ema21", label: "EMA 21" },
  { key: "sma50", label: "SMA 50" },
  { key: "sma200", label: "SMA 200" },
  { key: "stage", label: "Stage" },
];

// The Weinstein "Stage" toggle only exists on the weekly view.
export const STAGE_TOGGLE_RANGE: ChartRange = "W_4Y";

// The 2H·90D range draws candles, the two signal marker sets and the LP lines, and nothing else: no MA/Bollinger
// lines, no Stage, no earnings/dividend letters.
export const INTRADAY_CHART_RANGE: ChartRange = "2H_90D";
const INTRADAY_TOGGLE_KEYS: ReadonlySet<keyof SignalToggles> = new Set(["bbRsi", "warren", "lpSupport", "lpResistance"]);

export function isToggleOffered(key: keyof SignalToggles, range: ChartRange, isEtf: boolean): boolean {
  if (range === INTRADAY_CHART_RANGE) return INTRADAY_TOGGLE_KEYS.has(key);
  if (key === "stage") return range === STAGE_TOGGLE_RANGE;
  if (key === "earnings") return !isEtf;
  return true;
}

export function visibleToggleOptions(range: ChartRange, isEtf: boolean) {
  return TOGGLE_OPTIONS.filter((opt) => isToggleOffered(opt.key, range, isEtf));
}

/** What the chart is actually told: the saved toggle, ANDed with "this range offers it". */
export function effectiveToggles(toggles: SignalToggles, range: ChartRange, isEtf: boolean): SignalToggles {
  const out = { ...toggles };
  for (const key of Object.keys(out) as (keyof SignalToggles)[]) {
    out[key] = toggles[key] && isToggleOffered(key, range, isEtf);
  }
  return out;
}
