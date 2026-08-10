import type { PerfVsSpyStatus } from "@/lib/api/types";
import { cn } from "@/lib/utils";

// Exported for reuse by screenerFilters.ts's filter-option list (same
// precedent as VALUATION_LABELS living in ValuationBadge.tsx) -- one label
// source, not duplicated between the pill and the filter dropdown.
export const PERF_VS_SPY_LABELS: Record<PerfVsSpyStatus, string> = {
  outperform: "Outperform SPY",
  underperform: "Underperform SPY",
  no_data: "No data",
};

// outperform/underperform reuse the shared positive/negative tokens (same
// pattern as MoatPill). no_data matches tierColor.ts's flatChipClassFor
// null-score case (bg-surface-2/text-text-tertiary) -- the app's existing
// convention for "nothing to show" rather than inventing a new muted style.
const STYLES: Record<PerfVsSpyStatus, string> = {
  outperform: "bg-positive/16 text-positive border-positive/40",
  underperform: "bg-negative/16 text-negative border-negative/40",
  no_data: "bg-surface-2 text-text-tertiary border-border-subtle",
};

const STYLES_FLAT: Record<PerfVsSpyStatus, string> = {
  outperform: "bg-positive/16 text-positive",
  underperform: "bg-negative/16 text-negative",
  no_data: "bg-surface-2 text-text-tertiary",
};

const INSUFFICIENT_HISTORY_NOTE =
  "Reflects return since listing, not a full 5-year window -- this ticker has under 5 years of trading history. The same limitation affects the 5Y/10Y Performance figures above.";

interface Props {
  // null (or undefined while loading) renders nothing -- only SPY's own
  // page produces a null status (see ticker_summary.py::_resolve_perf_vs_spy),
  // since "SPY vs SPY" isn't a meaningful comparison. A genuinely
  // uncomputable spread for any other ticker still renders as "No data",
  // not hidden -- that's a real, informative state, not an absence.
  status: PerfVsSpyStatus | null | undefined;
  insufficientHistory?: boolean;
  // "chip" (default): bordered pill, used in TickerHeader's chip row.
  // "flat": borderless, same height as ScreenerCard/WatchlistTable's other pills.
  variant?: "chip" | "flat";
}

export function PerfVsSpyPill({ status, insufficientHistory = false, variant = "chip" }: Props) {
  if (!status) return null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        variant === "chip" ? STYLES[status] : STYLES_FLAT[status]
      )}
      title={insufficientHistory ? INSUFFICIENT_HISTORY_NOTE : undefined}
    >
      {PERF_VS_SPY_LABELS[status]}
    </span>
  );
}
