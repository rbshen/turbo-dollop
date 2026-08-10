import { FLAT_VERDICT_STYLES, VERDICT_STYLES } from "@/components/ticker/FairValuePill";
import { cn } from "@/lib/utils";
import type { ValuationSource } from "@/lib/api/types";

// Screener-card-specific labels -- deliberately category-only (no price or
// discount/premium %, which stay on the ticker page's Valuation tab). Same
// underlying verdict and colors as the ticker header's FairValuePill, just
// worded for a list view rather than a single-ticker detail view.
export const VALUATION_LABELS: Record<string, string> = {
  undervalued: "Undervalued",
  overvalued: "Overvalued",
  fair: "Fairvalued",
};

// Watchlist column only -- reclaims table width. Screener card and the
// filter dropdown keep the full VALUATION_LABELS wording above.
const VALUATION_LABELS_WATCHLIST: Record<string, string> = {
  undervalued: "Under",
  overvalued: "Over",
  fair: "Fair",
};

const LABEL_SETS: Record<"full" | "watchlist", Record<string, string>> = {
  full: VALUATION_LABELS,
  watchlist: VALUATION_LABELS_WATCHLIST,
};

interface Props {
  verdict: string | null;
  /** "custom" marks that this ticker's verdict came from an active,
   * user-saved custom valuation rather than Auto Calculation -- shown so a
   * Screener/Watchlist comparison across tickers doesn't silently mix an
   * Auto-derived verdict with a user's own override (see CLAUDE.md's Fork
   * B scope decision). Undefined/"auto"/null all render nothing extra. */
  source?: ValuationSource | null;
  // "chip" (default): bordered pill. "flat": borderless, same height as
  // ScreenerCard's other pills (company type, MoatPill's "flat" variant).
  variant?: "chip" | "flat";
  // Which label wording tier to use -- see LABEL_SETS above. Defaults to
  // the full "Overvalued"/"Fairvalued"/"Undervalued" wording.
  labelSet?: "full" | "watchlist";
}

export function ValuationBadge({ verdict, source, variant = "chip", labelSet = "full" }: Props) {
  if (!verdict) return null;
  const cls = variant === "chip" ? (VERDICT_STYLES[verdict] ?? VERDICT_STYLES.fair) : (FLAT_VERDICT_STYLES[verdict] ?? FLAT_VERDICT_STYLES.fair);
  const label = LABEL_SETS[labelSet][verdict] ?? verdict;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md text-xs font-semibold",
        variant === "chip" ? "border px-2 py-0.5" : "px-2 py-1",
        cls
      )}
    >
      {label}
      {source === "custom" && <span className="font-normal opacity-70">· Custom</span>}
    </span>
  );
}
