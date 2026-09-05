import { FLAT_VERDICT_STYLES, VERDICT_STYLES } from "@/components/ticker/FairValuePill";
import type { PerfVsSpyStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type RenderableStatus = Exclude<PerfVsSpyStatus, "no_data">;

// Exported for reuse by screenerFilters.ts's filter-option list (same
// precedent as VALUATION_LABELS living in ValuationBadge.tsx) -- one label
// source, not duplicated between the pill and the filter dropdown. "no_data"
// stays in this map (needed for the filter dropdown's own label) even though
// the pill itself never renders it -- see the render guard below.
//
// outperform/underperform share one static label (2026-09-05) -- direction
// is now conveyed by color alone (STATUS_TO_VERDICT's undervalued/overvalued
// mapping below, via VERDICT_STYLES/FLAT_VERDICT_STYLES), not by distinct
// wording, matching how ScreenerCard's own "screener" label set already
// worked. match/no_data are untouched -- "Match" has no direction to convey
// via color (STATUS_TO_VERDICT maps it to the neutral "fair" style), so it
// keeps its own distinct word rather than reading as a false "5Y vs SPY"
// outperform/underperform claim.
export const PERF_VS_SPY_LABELS: Record<PerfVsSpyStatus, string> = {
  outperform: "5Y vs SPY",
  underperform: "5Y vs SPY",
  match: "Match",
  no_data: "No data",
};

// Screener card: state is conveyed by color alone (see STATUS_TO_VERDICT
// below) -- every status renders the same literal text here.
const LABELS_SCREENER: Record<RenderableStatus, string> = {
  outperform: "5Y vs SPY",
  underperform: "5Y vs SPY",
  match: "5Y vs SPY",
};

const LABEL_SETS: Record<"full" | "screener", Record<RenderableStatus, string>> = {
  full: PERF_VS_SPY_LABELS,
  screener: LABELS_SCREENER,
};

// Reuses Valuation's own 3-state palette directly (VERDICT_STYLES/
// FLAT_VERDICT_STYLES, exported by FairValuePill.tsx) rather than matching
// copies of the same values -- vs-SPY and Valuation share one visual
// vocabulary this way and can't drift independently if that palette ever
// changes. Outperform maps to Undervalued's stronger green, Underperform to
// Overvalued's red, Match to Fairvalued's lighter green (not a neutral/gray
// tone -- Valuation's 3-state palette has no gray tier at all).
// Exported so WatchlistTable's SignalBars cell can compose
// VERDICT_SIGNAL_LEVEL/VERDICT_SIGNAL_COLOR[STATUS_TO_VERDICT[status]]
// without duplicating this status->verdict mapping.
export const STATUS_TO_VERDICT: Record<RenderableStatus, string> = {
  outperform: "undervalued",
  underperform: "overvalued",
  match: "fair",
};

const INSUFFICIENT_HISTORY_NOTE =
  "Reflects return since listing, not a full 5-year window -- this ticker has under 5 years of trading history. The same limitation affects the 5Y/10Y Performance figures above.";

interface Props {
  // null/undefined (SPY's own page) or "no_data" (a genuinely uncomputable
  // spread -- this ticker's own "5Y" figure couldn't be fetched) both render
  // nothing. Unlike the shipped behavior, "no_data" is no longer shown as a
  // muted pill here -- callers in a fixed-width context (WatchlistTable) that
  // need *something* in that slot render their own "-" fallback instead of
  // relying on this component.
  status: PerfVsSpyStatus | null | undefined;
  insufficientHistory?: boolean;
  // "chip" (default): bordered pill, used in TickerHeader's chip row.
  // "flat": borderless, same height as ScreenerCard/WatchlistTable's other pills.
  variant?: "chip" | "flat";
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to the
  // full label set: static "5Y vs SPY" for outperform/underperform (color
  // conveys direction), "Match" for a literal tie.
  labelSet?: "full" | "screener";
}

export function PerfVsSpyPill({ status, insufficientHistory = false, variant = "chip", labelSet = "full" }: Props) {
  if (!status || status === "no_data") return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? VERDICT_STYLES[STATUS_TO_VERDICT[status]] : FLAT_VERDICT_STYLES[STATUS_TO_VERDICT[status]]
      )}
      title={insufficientHistory ? INSUFFICIENT_HISTORY_NOTE : undefined}
    >
      {LABEL_SETS[labelSet][status]}
    </span>
  );
}
