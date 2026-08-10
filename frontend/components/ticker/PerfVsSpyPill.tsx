import type { PerfVsSpyStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

type RenderableStatus = Exclude<PerfVsSpyStatus, "no_data">;

// Exported for reuse by screenerFilters.ts's filter-option list (same
// precedent as VALUATION_LABELS living in ValuationBadge.tsx) -- one label
// source, not duplicated between the pill and the filter dropdown. "no_data"
// stays in this map (needed for the filter dropdown's own label) even though
// the pill itself never renders it -- see the render guard below.
export const PERF_VS_SPY_LABELS: Record<PerfVsSpyStatus, string> = {
  outperform: "Outperform SPY",
  underperform: "Underperform SPY",
  match: "Match",
  no_data: "No data",
};

// Watchlist column: drops the " SPY" suffix (the column header already
// establishes the "vs SPY" context) but otherwise unabbreviated.
const LABELS_WATCHLIST: Record<RenderableStatus, string> = {
  outperform: "Outperform",
  underperform: "Underperform",
  match: "Match",
};

// Screener card: space-constrained further still, next to the Valuation pill.
const LABELS_SCREENER: Record<RenderableStatus, string> = {
  outperform: "Out",
  underperform: "Under",
  match: "Match",
};

const LABEL_SETS: Record<"full" | "watchlist" | "screener", Record<RenderableStatus, string>> = {
  full: PERF_VS_SPY_LABELS,
  watchlist: LABELS_WATCHLIST,
  screener: LABELS_SCREENER,
};

// outperform/underperform reuse the shared positive/negative tokens (same
// pattern as MoatPill). match reuses the "warn" (amber) token -- this app's
// color system already uses it for "neutral middle result" (see
// tierColor.ts's Pass/70-74 tier), not just literal warnings, so it reads as
// a real third outcome rather than an alert. Neither STYLES record needs a
// "no_data" entry -- the render guard below returns null before ever
// indexing into either one for that status.
const STYLES: Record<RenderableStatus, string> = {
  outperform: "bg-positive/16 text-positive border-positive/40",
  underperform: "bg-negative/16 text-negative border-negative/40",
  match: "bg-warn/16 text-warn border-warn/40",
};

const STYLES_FLAT: Record<RenderableStatus, string> = {
  outperform: "bg-positive/16 text-positive",
  underperform: "bg-negative/16 text-negative",
  match: "bg-warn/16 text-warn",
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
  // full "Outperform SPY"/"Underperform SPY"/"Match" wording.
  labelSet?: "full" | "watchlist" | "screener";
}

export function PerfVsSpyPill({ status, insufficientHistory = false, variant = "chip", labelSet = "full" }: Props) {
  if (!status || status === "no_data") return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? STYLES[status] : STYLES_FLAT[status]
      )}
      title={insufficientHistory ? INSUFFICIENT_HISTORY_NOTE : undefined}
    >
      {LABEL_SETS[labelSet][status]}
    </span>
  );
}
